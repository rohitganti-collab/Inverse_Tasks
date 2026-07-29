"""Oracle-agnostic engine for Inverse Task problems.

This module deliberately imports nothing outside the standard library so it can
be unit-tested and validated without the `mcp` package installed. `server.py`
is a thin MCP wrapper around what lives here.

The design goal: **experts write the oracle, not the plumbing.** An expert drops
a folder under `problems/<problem_id>/` containing their own `problem.md`,
`oracle/setup.py`, and `golden/expected.json`, and this engine figures out what
the oracle can do and exposes exactly that — no server code changes.

See docs/AUTHORING.md for the full contract. In brief, an oracle is any class
named `Oracle` that:

  * declares its probe surface via `ACTIONS` (recommended), or exposes public
    methods, or just a single `query(mode, **params)` dispatcher; and
  * optionally declares a query `BUDGET`.

Everything else — budget accounting, answer parsing, grading, leakage
containment — is handled here, identically for every problem.
"""
from __future__ import annotations

import ast
import copy
import importlib.util
import inspect
import json
import numbers
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

# Folders under a problems root that are never problems (templates, scratch).
_RESERVED_PREFIXES = ("_", ".")

# Action names we refuse to expose, because Taiga reserves them or they collide
# with the scaffold hooks / Anthropic-provided tools.
RESERVED_ACTION_NAMES = frozenset(
    {
        "setup_problem",
        "grade_problem",
        "agent_abandoned",
        "setup_agentic_grader",
        "list_problems",
        "submit_answer",
        "describe_oracle",
        "bash",
        "str_replace_editor",
        "computer",
        "browser",
        "tmux",
    }
)

# JSON-schema type name -> python annotation used when synthesising tool signatures.
JSON_TYPE_TO_PY = {
    "integer": "int",
    "number": "float",
    "string": "str",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}


class InverseTaskError(Exception):
    """Base class for engine errors that should be reported to the caller."""


class ProblemNotFound(InverseTaskError):
    pass


class OracleContractError(InverseTaskError):
    """The expert's oracle does not satisfy the documented contract."""


class BudgetExceeded(InverseTaskError):
    pass


class UnknownAction(InverseTaskError):
    pass


class AnswerFormatError(InverseTaskError):
    pass


# --------------------------------------------------------------------------- #
# Problem discovery
# --------------------------------------------------------------------------- #


def problem_roots(explicit: Optional[Iterable[os.PathLike | str]] = None) -> list[Path]:
    """Directories searched for problem folders, in precedence order.

    Overridable with `INVERSE_TASKS_PROBLEM_DIRS` (os.pathsep-separated) so a
    Taiga `preloaded_files` mount can add problems to a running container
    without rebuilding the image.
    """
    if explicit is not None:
        return [Path(p) for p in explicit]

    env = os.environ.get("INVERSE_TASKS_PROBLEM_DIRS")
    if env:
        return [Path(p) for p in env.split(os.pathsep) if p]

    return [Path(__file__).resolve().parent.parent / "problems"]


def discover_problems(roots: Optional[Iterable[os.PathLike | str]] = None) -> dict[str, Path]:
    """Map problem_id -> problem directory. Earlier roots win on collision."""
    found: dict[str, Path] = {}
    for root in problem_roots(roots):
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name.startswith(_RESERVED_PREFIXES):
                continue
            # Either marker identifies a problem folder. `oracle/setup.py` alone
            # is enough because an expert using the Create Problem form may keep
            # the prompt in the form's Task Prompt field instead of problem.md.
            if not (child / "problem.md").is_file() and not (
                child / "oracle" / "setup.py"
            ).is_file():
                continue
            found.setdefault(child.name, child)
    return found


def resolve_problem_dir(
    problem_id: str, roots: Optional[Iterable[os.PathLike | str]] = None
) -> Path:
    problems = discover_problems(roots)
    if problem_id not in problems:
        known = ", ".join(sorted(problems)) or "<none>"
        raise ProblemNotFound(f"Unknown problem_id {problem_id!r}. Available: {known}")
    return problems[problem_id]


# --------------------------------------------------------------------------- #
# Oracle loading and action normalisation
# --------------------------------------------------------------------------- #


def _load_oracle_class(problem_dir: Path):
    setup_path = problem_dir / "oracle" / "setup.py"
    if not setup_path.is_file():
        raise OracleContractError(f"Missing oracle at {setup_path}")

    module_name = f"inverse_oracle_{problem_dir.name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, setup_path)
    if spec is None or spec.loader is None:
        raise OracleContractError(f"Could not import oracle from {setup_path}")
    module = importlib.util.module_from_spec(spec)

    # Put the oracle's own directory on sys.path so an expert can split their
    # oracle across helper modules (`import helpers` next to setup.py).
    oracle_dir = str(setup_path.parent)
    added = oracle_dir not in sys.path
    if added:
        sys.path.insert(0, oracle_dir)
    try:
        spec.loader.exec_module(module)
    finally:
        if added:
            try:
                sys.path.remove(oracle_dir)
            except ValueError:  # pragma: no cover - defensive
                pass

    oracle_cls = getattr(module, "Oracle", None)
    if oracle_cls is None:
        raise OracleContractError(
            f"{setup_path} defines no class named `Oracle`. "
            "Every problem's oracle/setup.py must expose `class Oracle`."
        )
    return oracle_cls


def _normalise_param(name: str, spec: Any) -> dict[str, Any]:
    """Accept several shorthands for a parameter declaration."""
    if isinstance(spec, str):  # {"x": "integer"}
        spec = {"type": spec}
    elif isinstance(spec, type):  # {"x": int}
        spec = {"type": _py_type_to_json(spec)}
    elif not isinstance(spec, dict):
        raise OracleContractError(
            f"Parameter {name!r} must be declared as a dict, a type, or a type name; got {spec!r}"
        )
    else:
        spec = dict(spec)

    json_type = spec.get("type", "string")
    if isinstance(json_type, type):
        json_type = _py_type_to_json(json_type)
    if json_type not in JSON_TYPE_TO_PY:
        raise OracleContractError(
            f"Parameter {name!r} declares unsupported type {json_type!r}. "
            f"Supported: {sorted(JSON_TYPE_TO_PY)}"
        )

    normalised = {
        "name": name,
        "type": json_type,
        "description": spec.get("description", ""),
        "required": bool(spec.get("required", "default" not in spec)),
    }
    if "default" in spec:
        normalised["default"] = spec["default"]
        normalised["required"] = bool(spec.get("required", False))
    return normalised


PY_TYPE_TO_JSON = {
    bool: "boolean",  # before int: bool is a subclass of int
    int: "integer",
    float: "number",
    str: "string",
    list: "array",
    tuple: "array",
    dict: "object",
}


def _py_type_to_json(tp: Any) -> str:
    return PY_TYPE_TO_JSON.get(tp, "string")


def _normalise_action(raw: Any, name_hint: Optional[str] = None) -> dict[str, Any]:
    if isinstance(raw, str):
        raw = {"name": raw}
    if not isinstance(raw, dict):
        raise OracleContractError(f"Action declaration must be a dict or a name; got {raw!r}")
    raw = dict(raw)

    name = raw.get("name", name_hint)
    if not name:
        raise OracleContractError(f"Action declaration is missing a name: {raw!r}")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise OracleContractError(
            f"Action name {name!r} is not a valid identifier; it has to be usable as a tool name."
        )
    if name in RESERVED_ACTION_NAMES or name.startswith("_scaffold_"):
        raise OracleContractError(
            f"Action name {name!r} is reserved by Taiga or by this engine. Pick another name."
        )

    params_decl = raw.get("params", raw.get("parameters", {})) or {}
    if isinstance(params_decl, list):  # [{"name": "x", ...}, ...]
        params = [_normalise_param(p.get("name", ""), p) for p in params_decl]
    elif isinstance(params_decl, dict):
        params = [_normalise_param(k, v) for k, v in params_decl.items()]
    else:
        raise OracleContractError(f"Action {name!r}: `params` must be a dict or list")

    # Required params must precede optional ones so a synthesised signature is legal.
    params.sort(key=lambda p: (not p["required"],))

    return {
        "name": name,
        "description": raw.get("description", "") or f"Probe the oracle via {name!r}.",
        "params": params,
        "costs_budget": bool(raw.get("costs_budget", raw.get("costs_query", True))),
        "method": raw.get("method"),  # optional explicit oracle method name
    }


def _actions_from_declaration(decl: Any) -> list[dict[str, Any]]:
    if isinstance(decl, dict):
        return [_normalise_action(v, name_hint=k) for k, v in decl.items()]
    if isinstance(decl, (list, tuple)):
        return [_normalise_action(item) for item in decl]
    raise OracleContractError(f"`ACTIONS` must be a list or dict; got {type(decl).__name__}")


def _actions_from_introspection(oracle: Any) -> list[dict[str, Any]]:
    """Fallback: treat the oracle's public methods as the probe surface."""
    actions: list[dict[str, Any]] = []
    for name, member in inspect.getmembers(oracle, predicate=callable):
        if name.startswith("_") or name in RESERVED_ACTION_NAMES or name == "query":
            continue
        try:
            sig = inspect.signature(member)
        except (TypeError, ValueError):
            continue
        params: dict[str, Any] = {}
        skip = False
        for pname, param in sig.parameters.items():
            if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                skip = True
                break
            annotation = param.annotation
            json_type = (
                _py_type_to_json(annotation) if isinstance(annotation, type) else "string"
            )
            spec: dict[str, Any] = {"type": json_type}
            if param.default is not inspect.Parameter.empty:
                spec["default"] = param.default
                spec["required"] = False
            else:
                spec["required"] = True
            params[pname] = spec
        if skip:
            continue
        actions.append(
            _normalise_action(
                {
                    "name": name,
                    "description": (inspect.getdoc(member) or "").strip().split("\n")[0],
                    "params": params,
                },
            )
        )
    return actions


# --------------------------------------------------------------------------- #
# Problem + Session
# --------------------------------------------------------------------------- #


class Problem:
    """A loaded problem: its prompt, its oracle, and its declared surface."""

    def __init__(self, problem_id: str, directory: Path):
        self.problem_id = problem_id
        self.directory = directory
        self.oracle_cls = _load_oracle_class(directory)
        self.oracle = self.oracle_cls()

        decl = _first_attr(self.oracle, ("ACTIONS", "actions"))
        if callable(decl):
            decl = decl()
        if decl:
            self.actions = _actions_from_declaration(decl)
            self.actions_declared = True
        else:
            introspected = _actions_from_introspection(self.oracle)
            self.actions = introspected
            self.actions_declared = bool(introspected)

        if not self.actions and not hasattr(self.oracle, "query"):
            raise OracleContractError(
                f"Oracle for {problem_id!r} exposes no probe surface: declare `ACTIONS`, "
                "expose public methods, or provide a `query(mode, **params)` method."
            )

        budget = _first_attr(self.oracle, ("BUDGET", "budget", "QUERY_BUDGET"))
        self.budget_total: Optional[int] = int(budget) if isinstance(budget, numbers.Integral) else None

    @property
    def prompt(self) -> str:
        """The task text from problem.md, or "" if the prompt comes from Taiga.

        Empty is legitimate: an expert filling in the Create Problem form may
        supply the prompt there, in which case it arrives via extra_fields.
        """
        path = self.directory / "problem.md"
        return path.read_text() if path.is_file() else ""

    @property
    def title(self) -> str:
        config = self.directory / "config.yaml"
        if config.is_file():
            for line in config.read_text().splitlines():
                if line.strip().startswith("title:"):
                    return line.split(":", 1)[1].strip()
        return self.problem_id

    def action(self, name: str) -> Optional[dict[str, Any]]:
        for candidate in self.actions:
            if candidate["name"] == name:
                return candidate
        return None

    def golden(self) -> dict[str, Any]:
        path = self.directory / "golden" / "expected.json"
        if not path.is_file():
            raise InverseTaskError(f"Missing golden answer at {path}")
        data = json.loads(path.read_text())
        if "answer" not in data:
            raise InverseTaskError(f"{path} must contain an 'answer' key")
        return data

    def answer_shape(self) -> dict[str, Any]:
        """Shape-only description of the expected answer — never its values."""
        declared = _first_attr(self.oracle, ("ANSWER_SCHEMA", "answer_schema"))
        if callable(declared):
            declared = declared()
        if isinstance(declared, dict) and declared:
            return copy.deepcopy(declared)

        golden = self.golden()
        expected = golden["answer"]
        shape: dict[str, Any] = {"type": _shape_type(expected)}
        if isinstance(expected, (list, tuple)):
            shape["length"] = len(expected)
            shape["item_types"] = sorted({_shape_type(item) for item in expected})
        elif isinstance(expected, dict):
            shape["keys"] = sorted(expected)
        if golden.get("keys"):
            shape["keys"] = list(golden["keys"])
        if golden.get("tolerance") is not None:
            shape["tolerance"] = golden["tolerance"]
        return shape


def _shape_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, numbers.Integral):
        return "integer"
    if isinstance(value, numbers.Real):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _first_attr(obj: Any, names: Iterable[str]) -> Any:
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return None


class Session:
    """One problem attempt: budget accounting, dispatch, submission, grading.

    A Session owns a freshly constructed oracle, so no state leaks between
    attempts even though a container may be reused.
    """

    def __init__(self, problem: Problem):
        self.problem = problem
        self.calls_used = 0
        self.call_log: list[dict[str, Any]] = []
        self.submission_raw: Optional[str] = None
        self.submission: Any = None
        self.submitted = False

    # -- introspection ---------------------------------------------------- #

    @property
    def remaining(self) -> Optional[int]:
        if self.problem.budget_total is None:
            return None
        return max(0, self.problem.budget_total - self.calls_used)

    def describe(self) -> dict[str, Any]:
        actions = [
            {
                "name": a["name"],
                "description": a["description"],
                "params": [dict(p) for p in a["params"]],
                "costs_budget": a["costs_budget"],
            }
            for a in self.problem.actions
        ]
        return {
            "problem_id": self.problem.problem_id,
            "title": self.problem.title,
            "actions": actions,
            "actions_declared": self.problem.actions_declared,
            "budget_total": self.problem.budget_total,
            "budget_used": self.calls_used,
            "budget_remaining": self.remaining,
            "answer_shape": self.problem.answer_shape(),
        }

    # -- probing ---------------------------------------------------------- #

    def _resolve_callable(self, action_name: str, action: Optional[dict[str, Any]]) -> Callable:
        oracle = self.problem.oracle
        explicit = (action or {}).get("method")
        if explicit:
            method = getattr(oracle, explicit, None)
            if method is None:
                raise OracleContractError(
                    f"Action {action_name!r} declares method={explicit!r} but the oracle has no such method."
                )
            return lambda **params: method(**params)

        method = getattr(oracle, action_name, None)
        if callable(method) and not action_name.startswith("_"):
            return lambda **params: method(**params)

        query = getattr(oracle, "query", None)
        if callable(query):
            return lambda **params: query(action_name, **params)

        raise OracleContractError(
            f"Oracle cannot service action {action_name!r}: no method of that name and no `query`."
        )

    def query(self, action_name: str, params: Optional[dict[str, Any]] = None) -> Any:
        params = dict(params or {})
        action = self.problem.action(action_name)

        if action is None and self.problem.actions_declared:
            known = ", ".join(a["name"] for a in self.problem.actions) or "<none>"
            raise UnknownAction(f"Unknown action {action_name!r}. Available actions: {known}")

        if action is not None:
            params = self._validate_params(action, params)

        costs_budget = action["costs_budget"] if action else True
        if costs_budget and self.remaining == 0:
            raise BudgetExceeded(
                f"Query budget exhausted: {self.problem.budget_total} "
                f"budgeted call(s) already used."
            )

        fn = self._resolve_callable(action_name, action)
        # Count before dispatch so a raising oracle still consumes its call —
        # otherwise a solver could probe for free by triggering errors.
        if costs_budget:
            self.calls_used += 1
        try:
            observation = fn(**params)
        except TypeError as exc:
            raise OracleContractError(
                f"Oracle rejected action {action_name!r} with params {params!r}: {exc}"
            ) from exc

        self.call_log.append(
            {
                "action": action_name,
                "params": params,
                "observation": _jsonable(observation),
                "costs_budget": costs_budget,
                "budget_used_after": self.calls_used,
            }
        )
        return observation

    def _validate_params(self, action: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        declared = {p["name"]: p for p in action["params"]}
        unexpected = set(params) - set(declared)
        if unexpected:
            raise UnknownAction(
                f"Action {action['name']!r} got unexpected parameter(s) {sorted(unexpected)}. "
                f"Expected: {sorted(declared) or 'none'}"
            )

        resolved: dict[str, Any] = {}
        for name, spec in declared.items():
            if name in params:
                resolved[name] = _coerce(params[name], spec["type"], f"{action['name']}.{name}")
            elif "default" in spec:
                resolved[name] = spec["default"]
            elif spec["required"]:
                raise UnknownAction(
                    f"Action {action['name']!r} requires parameter {name!r} ({spec['type']})."
                )
        return resolved

    # -- submission ------------------------------------------------------- #

    def submit(self, answer: Any) -> dict[str, Any]:
        raw = answer if isinstance(answer, str) else json.dumps(_jsonable(answer))
        parsed = parse_answer(answer) if isinstance(answer, str) else _jsonable(answer)

        shape = self.problem.answer_shape()
        problems = check_answer_shape(parsed, shape)

        self.submission_raw = raw
        self.submission = parsed
        self.submitted = True
        return {"accepted": parsed, "warnings": problems, "answer_shape": shape}

    # -- grading ---------------------------------------------------------- #

    def grade(
        self, transcript: str = "", extra_fields: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        golden = self.problem.golden()
        custom = _load_custom_grader(self.problem.directory)
        if custom is not None:
            result = custom(
                submission=self.submission,
                expected=golden["answer"],
                golden=golden,
                transcript=transcript,
                extra_fields=dict(extra_fields or {}),
                session=self,
            )
            return _normalise_grade(result, golden, self)

        if not self.submitted:
            return {
                "subscores": {"correct": 0.0},
                "weights": {"correct": 1.0},
                "metadata": {
                    "reason": "no answer submitted",
                    "budget_used": self.calls_used,
                    "call_log": self.call_log,
                },
            }

        return _normalise_grade(
            compare_answers(self.submission, golden),
            golden,
            self,
        )


# --------------------------------------------------------------------------- #
# Answer parsing / shape checking / comparison
# --------------------------------------------------------------------------- #

_FENCE_RE = re.compile(r"^\s*```(?:json|python)?\s*(.*?)\s*```\s*$", re.DOTALL)


def parse_answer(text: str) -> Any:
    """Parse a submitted answer string into JSON-ish data.

    Deliberately conservative: JSON first, then a Python literal. We do *not*
    scrape numbers out of prose — silently reinterpreting a malformed answer
    could turn a wrong submission into a passing one.
    """
    if not isinstance(text, str):
        return _jsonable(text)

    candidate = text.strip()
    fenced = _FENCE_RE.match(candidate)
    if fenced:
        candidate = fenced.group(1).strip()

    for loader in (json.loads, ast.literal_eval):
        try:
            return _jsonable(loader(candidate))
        except (ValueError, SyntaxError, TypeError):
            continue
    return candidate


def check_answer_shape(answer: Any, shape: dict[str, Any]) -> list[str]:
    """Shape-only validation. Returns human-readable warnings (never the answer)."""
    warnings: list[str] = []
    expected_type = shape.get("type")
    actual_type = _shape_type(answer)

    numeric = {"integer", "number"}
    if expected_type and expected_type != actual_type:
        if not (expected_type in numeric and actual_type in numeric):
            warnings.append(
                f"expected a {expected_type} answer but got a {actual_type}"
            )

    if expected_type == "array" and isinstance(answer, (list, tuple)):
        length = shape.get("length")
        if isinstance(length, int) and len(answer) != length:
            warnings.append(f"expected {length} element(s) but got {len(answer)}")

    if isinstance(answer, dict) and shape.get("keys"):
        missing = [k for k in shape["keys"] if k not in answer]
        if missing:
            warnings.append(f"missing expected key(s): {missing}")

    return warnings


def compare_answers(submission: Any, golden: dict[str, Any]) -> dict[str, Any]:
    """Generic structural comparison driven entirely by golden/expected.json."""
    expected = golden["answer"]
    tolerance = golden.get("tolerance", 0) or 0
    keys = golden.get("keys")
    scoring = (golden.get("scoring") or "binary").lower()

    normalised = submission
    # A dict answer is accepted for a list golden when the golden names its keys.
    if isinstance(submission, dict) and isinstance(expected, (list, tuple)) and keys:
        if all(k in submission for k in keys):
            normalised = [submission[k] for k in keys]

    matches, total, details = _compare(normalised, expected, tolerance, keys)
    all_correct = total > 0 and matches == total

    if scoring == "partial" and total > 0:
        score = matches / total
    else:
        score = 1.0 if all_correct else 0.0

    return {
        "score": score,
        "correct": all_correct,
        "matches": matches,
        "total": total,
        "details": details,
        "scoring": "partial" if scoring == "partial" else "binary",
        "tolerance": tolerance,
    }


def _compare(
    submission: Any, expected: Any, tolerance: float, keys: Optional[list[str]]
) -> tuple[int, int, list[dict[str, Any]]]:
    if isinstance(expected, (list, tuple)):
        details: list[dict[str, Any]] = []
        matches = 0
        seq = submission if isinstance(submission, (list, tuple)) else []
        for index, exp in enumerate(expected):
            got = seq[index] if index < len(seq) else None
            ok = _scalar_match(got, exp, tolerance)
            matches += int(ok)
            label = keys[index] if keys and index < len(keys) else str(index)
            details.append({"element": label, "expected": exp, "submitted": got, "match": ok})
        if isinstance(submission, (list, tuple)) and len(submission) != len(expected):
            details.append(
                {
                    "element": "length",
                    "expected": len(expected),
                    "submitted": len(submission),
                    "match": False,
                }
            )
            return 0, len(expected), details  # wrong arity is never partially right
        return matches, len(expected), details

    if isinstance(expected, dict):
        details = []
        matches = 0
        got_map = submission if isinstance(submission, dict) else {}
        for key, exp in expected.items():
            got = got_map.get(key)
            ok = _scalar_match(got, exp, tolerance)
            matches += int(ok)
            details.append({"element": key, "expected": exp, "submitted": got, "match": ok})
        return matches, len(expected), details

    ok = _scalar_match(submission, expected, tolerance)
    return int(ok), 1, [{"element": "answer", "expected": expected, "submitted": submission, "match": ok}]


def _scalar_match(got: Any, expected: Any, tolerance: float) -> bool:
    if isinstance(expected, bool) or isinstance(got, bool):
        return got is expected or got == expected
    if isinstance(expected, numbers.Real) and isinstance(got, numbers.Real):
        return abs(float(got) - float(expected)) <= float(tolerance)
    if isinstance(expected, str) and isinstance(got, str):
        return got.strip() == expected.strip()
    if isinstance(expected, (list, tuple, dict)):
        matches, total, _ = _compare(got, expected, tolerance, None)
        return total > 0 and matches == total
    return got == expected


def _load_custom_grader(problem_dir: Path) -> Optional[Callable]:
    """Optional per-problem grader: `grader/grade.py` exposing `grade(**kwargs)`."""
    path = problem_dir / "grader" / "grade.py"
    if not path.is_file():
        return None
    module_name = f"inverse_grader_{problem_dir.name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    grade = getattr(module, "grade", None)
    if not callable(grade):
        raise InverseTaskError(f"{path} must expose a callable `grade(...)`")

    def call(**kwargs):
        accepted = inspect.signature(grade).parameters
        if any(p.kind == p.VAR_KEYWORD for p in accepted.values()):
            return grade(**kwargs)
        return grade(**{k: v for k, v in kwargs.items() if k in accepted})

    return call


def _normalise_grade(result: Any, golden: dict[str, Any], session: "Session") -> dict[str, Any]:
    """Coerce a comparison/custom-grader result into Taiga's Grade shape."""
    base_metadata = {
        "problem_id": session.problem.problem_id,
        "budget_total": session.problem.budget_total,
        "budget_used": session.calls_used,
        "submitted_raw": session.submission_raw,
        "submitted": session.submission,
        "expected": golden["answer"],
        "call_log": session.call_log,
    }

    if isinstance(result, numbers.Real) and not isinstance(result, bool):
        score = _clamp(float(result))
        return {
            "subscores": {"correct": score},
            "weights": {"correct": 1.0},
            "metadata": base_metadata,
        }

    if not isinstance(result, dict):
        raise InverseTaskError(f"Grader returned an unsupported result type: {type(result).__name__}")

    if "subscores" in result:
        grade = {
            "subscores": {k: _clamp(float(v)) for k, v in result["subscores"].items()},
            "weights": {k: float(v) for k, v in (result.get("weights") or {}).items()},
        }
        if not grade["weights"]:
            n = len(grade["subscores"]) or 1
            grade["weights"] = {k: 1.0 / n for k in grade["subscores"]}
        grade["metadata"] = {**base_metadata, **(result.get("metadata") or {})}
        for passthrough in ("env_internal_failure", "env_internal_failure_logs", "penalties"):
            if passthrough in result:
                grade[passthrough] = result[passthrough]
        return grade

    score = _clamp(float(result.get("score", 0.0)))
    metadata = {
        **base_metadata,
        "correct": result.get("correct"),
        "matches": result.get("matches"),
        "total": result.get("total"),
        "details": result.get("details"),
        "scoring": result.get("scoring"),
        "tolerance": result.get("tolerance", golden.get("tolerance", 0)),
    }
    return {
        "subscores": {"correct": score},
        "weights": {"correct": 1.0},
        "metadata": metadata,
    }


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _coerce(value: Any, json_type: str, label: str) -> Any:
    """Best-effort coercion so a stringy tool argument still reaches the oracle."""
    try:
        if json_type == "integer":
            if isinstance(value, bool):
                raise ValueError("boolean is not an integer")
            if isinstance(value, numbers.Integral):
                return int(value)
            if isinstance(value, numbers.Real) and float(value).is_integer():
                return int(value)
            return int(str(value).strip())
        if json_type == "number":
            if isinstance(value, bool):
                raise ValueError("boolean is not a number")
            return float(value)
        if json_type == "boolean":
            if isinstance(value, bool):
                return value
            lowered = str(value).strip().lower()
            if lowered in ("true", "1", "yes"):
                return True
            if lowered in ("false", "0", "no"):
                return False
            raise ValueError("not a boolean")
        if json_type == "string":
            return value if isinstance(value, str) else json.dumps(_jsonable(value))
        if json_type == "array":
            if isinstance(value, (list, tuple)):
                return list(value)
            parsed = parse_answer(value) if isinstance(value, str) else value
            if isinstance(parsed, (list, tuple)):
                return list(parsed)
            raise ValueError("not an array")
        if json_type == "object":
            if isinstance(value, dict):
                return value
            parsed = parse_answer(value) if isinstance(value, str) else value
            if isinstance(parsed, dict):
                return parsed
            raise ValueError("not an object")
    except (TypeError, ValueError) as exc:
        raise UnknownAction(f"Parameter {label} expects a {json_type}: {exc}") from exc
    return value


def _jsonable(value: Any) -> Any:
    """Convert an oracle observation into something JSON-serialisable."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        return float(value)
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if hasattr(value, "tolist"):  # numpy arrays / scalars, without importing numpy
        try:
            return _jsonable(value.tolist())
        except Exception:  # pragma: no cover - defensive
            pass
    return str(value)


def load_session(
    problem_id: str, roots: Optional[Iterable[os.PathLike | str]] = None
) -> Session:
    """Load a problem and start a fresh attempt against a brand-new oracle."""
    directory = resolve_problem_dir(problem_id, roots)
    return Session(Problem(problem_id, directory))


# --------------------------------------------------------------------------- #
# Prompt tool guide
# --------------------------------------------------------------------------- #

# Placeholder rendering for parameter and answer types. Types only — a guide that
# echoed real values would hand the model the answer.
_TYPE_PLACEHOLDER = {
    "integer": "<integer>",
    "number": "<number>",
    "string": "<string>",
    "boolean": "<true|false>",
    "array": "<array>",
    "object": "<object>",
}


def answer_example(shape: dict[str, Any]) -> str:
    """A shape-only example submission, e.g. `[<integer>, <integer>]`."""
    kind = shape.get("type", "string")
    if kind == "array":
        length = shape.get("length")
        item_types = shape.get("item_types") or ["integer"]
        if not isinstance(length, int) or length <= 0:
            return f"[{_TYPE_PLACEHOLDER.get(item_types[0], '<value>')}, ...]"
        items = [
            _TYPE_PLACEHOLDER.get(item_types[min(i, len(item_types) - 1)], "<value>")
            for i in range(length)
        ]
        return "[" + ", ".join(items) + "]"
    if kind == "object":
        keys = shape.get("keys") or ["key"]
        return "{" + ", ".join(f'"{k}": <value>' for k in keys) + "}"
    return _TYPE_PLACEHOLDER.get(kind, "<value>")


def _call_example(action: dict[str, Any], mode: str) -> str:
    params = action["params"]
    if mode == "named":
        args = ", ".join(
            f"{p['name']}={_TYPE_PLACEHOLDER.get(p['type'], '<value>')}" for p in params
        )
        return f"`{action['name']}({args})`"
    if not params:
        return f'`query(action="{action["name"]}")`'
    rendered = ", ".join(
        f'"{p["name"]}": {_TYPE_PLACEHOLDER.get(p["type"], "<value>")}' for p in params
    )
    return f'`query(action="{action["name"]}", params={{{rendered}}})`'


def render_tool_guide(session: "Session", mode: str = "query") -> str:
    """Generate the calling contract appended to a problem's prompt.

    Experts write the science in `problem.md`; this guarantees the *mechanics*
    the model is told are the mechanics actually published, which is otherwise
    the easiest thing in the whole setup to get out of sync.
    """
    problem = session.problem
    lines = ["---", "", "## Using your tools", ""]

    if problem.actions:
        if mode == "named":
            lines.append(
                "Probe the black box with these tools. Where the task above names an "
                "operation, this is how you call it:"
            )
        else:
            lines.append(
                "Probe the black box with the **`query`** tool. Where the task above "
                "names an operation, call it through `query` like this:"
            )
        lines += ["", "| Call | What it does | Budget |", "| --- | --- | --- |"]
        for action in problem.actions:
            cost = "costs 1 query" if action["costs_budget"] else "free"
            description = " ".join(action["description"].split())
            optional = [p["name"] for p in action["params"] if not p["required"]]
            if optional:
                description += f" (optional: {', '.join(optional)})"
            lines.append(f"| {_call_example(action, mode)} | {description} | {cost} |")
    else:
        lines.append(
            "Probe the black box with the **`query`** tool: `query(action=<string>, "
            "params=<object>)`. The task above states which operations exist."
        )

    shape = problem.answer_shape()
    lines += [
        "",
        f"- **`submit_answer(answer)`** — record your final answer as JSON: "
        f"`{answer_example(shape)}`. You may resubmit; only your last submission is graded.",
        "- **`describe_oracle()`** — re-read this list and check your remaining budget. Free.",
    ]

    if problem.budget_total is not None:
        free = [a["name"] for a in problem.actions if not a["costs_budget"]]
        note = (
            f"\n**Query budget: {problem.budget_total} call(s).** "
            "Calls marked free above do not count against it."
            if free
            else f"\n**Query budget: {problem.budget_total} call(s).**"
        )
        lines.append(note)

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Tool-signature synthesis (used by server.py to publish named action tools)
# --------------------------------------------------------------------------- #


def synthesise_action_function(action: dict[str, Any], dispatch: Callable) -> Callable:
    """Build a function whose *real* signature mirrors a declared action.

    Generated with exec rather than by patching `__signature__` so that whatever
    introspection the installed FastMCP/pydantic version performs sees a genuine
    signature and derives a correct JSON schema from it.

    `dispatch(action_name, params)` is called with the collected arguments.
    """
    name = action["name"]
    namespace: dict[str, Any] = {"_dispatch": dispatch, "_action_name": name}

    sig_parts: list[str] = []
    call_parts: list[str] = []
    for index, param in enumerate(action["params"]):
        annotation = JSON_TYPE_TO_PY[param["type"]]
        if "default" in param:
            default_ref = f"_default_{index}"
            namespace[default_ref] = param["default"]
            sig_parts.append(f"{param['name']}: {annotation} = {default_ref}")
        elif not param["required"]:
            sig_parts.append(f"{param['name']}: {annotation} = None")
        else:
            sig_parts.append(f"{param['name']}: {annotation}")
        call_parts.append(f"{param['name']!r}: {param['name']}")

    doc = action["description"].replace("\\", "\\\\").replace('"""', "'''")
    doc += (
        "\n\nEach call spends one unit of your query budget."
        if action["costs_budget"]
        else "\n\nThis call does not spend query budget."
    )

    source = (
        f"def {name}({', '.join(sig_parts)}) -> str:\n"
        f'    """{doc}"""\n'
        f"    return _dispatch(_action_name, {{{', '.join(call_parts)}}})\n"
    )
    # dont_inherit=True keeps this module's `from __future__ import annotations`
    # out of the generated code, so the synthesised function carries real type
    # objects rather than lazy strings — schema derivation then needs no
    # annotation resolution, whatever FastMCP version is installed.
    exec(compile(source, f"<action:{name}>", "exec", dont_inherit=True), namespace)  # noqa: S102
    return namespace[name]
