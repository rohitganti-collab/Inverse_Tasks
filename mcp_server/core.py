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
import contextlib
import copy
import hashlib
import hmac
import importlib.util
import inspect
import json
import math
import numbers
import os
import re
import stat as stat_module
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
        "query",
        "query_oracle",
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


@contextlib.contextmanager
def protected_stdout():
    """Run expert-authored code with stdout redirected to stderr.

    The MCP transport *is* stdout. A stray `print()` in an oracle — the kind of
    thing anyone leaves behind while debugging — would inject text into the
    protocol stream and break the run in a way that is very hard to trace back.
    Redirecting keeps the output visible in the container logs while leaving the
    transport clean, so an expert's debug print is harmless rather than fatal.
    """
    with contextlib.redirect_stdout(sys.stderr):
        yield


class InverseTaskError(Exception):
    """Base class for errors that should be reported to the caller."""


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
            # Any of these markers identifies a problem folder. `oracle/setup.py`
            # alone is enough because an expert using the Create Problem form may
            # keep the prompt in the form's Task Prompt field instead of
            # problem.md; `simulation/` is the equivalent marker for a forward
            # task, which has no oracle at all.
            if (
                not (child / "problem.md").is_file()
                and not (child / "oracle" / "setup.py").is_file()
                and not (child / "simulation").is_dir()
            ):
                continue
            found.setdefault(child.name, child)
    return found


def resolve_problem_dir(
    problem_id: str, roots: Optional[Iterable[os.PathLike | str]] = None
) -> Path:
    problems = discover_problems(roots)
    if problem_id in problems:
        return problems[problem_id]

    searched = [str(p) for p in problem_roots(roots)]
    if problems:
        raise ProblemNotFound(
            f"Unknown problem_id {problem_id!r}. Available: {', '.join(sorted(problems))}. "
            f"Searched: {searched}. The Problem ID field must match the mounted "
            "folder name exactly."
        )

    # Nothing found anywhere. By far the most common cause is the two
    # similarly-named upload boxes on Taiga's Create Problem form: only
    # "Preloaded Files" is mounted into the container. "Upload Supporting Files"
    # says it is for "golden answers", but those stay in remote storage for human
    # reviewers and never reach the filesystem the grader reads.
    raise ProblemNotFound(
        f"No problems found for {problem_id!r} — searched {searched} and found none.\n"
        f"Expected a folder at <root>/{problem_id}/ containing problem.md and/or "
        "oracle/setup.py.\n"
        "If you uploaded the problem folder through Taiga: use **Preloaded Files "
        "-> Mount files** (mounted into the container at run time), not **Upload "
        "Supporting Files** (remote storage only, never mounted — despite its "
        "mention of golden answers, that box is for material humans review)."
    )


# --------------------------------------------------------------------------- #
# Oracle loading and action normalisation
# --------------------------------------------------------------------------- #

# Custom graders are immutable within a problem run, so importing each one once
# avoids repeated module side effects if setup_problem is called again.
_GRADER_CACHE: dict[str, Optional[Callable]] = {}


def _cache_key(problem_dir: Path) -> str:
    return str(problem_dir.resolve())


def is_taiga_runtime() -> bool:
    """True inside the published image, where a real model is on the other end.

    The image sets `INVERSE_TASKS_RUNTIME=taiga`. Authoring checkouts and the
    build-time selftest do not, which is what keeps the hardening and
    anti-tamper paths from mutating a developer's working tree.
    """
    return os.environ.get("INVERSE_TASKS_RUNTIME", "").strip().lower() == "taiga"


def permission_hardening_enabled() -> bool:
    """Whether setup should make a problem tree private to its owner.

    This is deliberately limited to the Taiga image runtime. Running a local
    selftest against an authoring checkout must never mutate that checkout,
    even if a stale environment variable happens to be present.
    """
    if not is_taiga_runtime():
        return False
    return os.environ.get("INVERSE_TASKS_HARDEN_PERMISSIONS", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


# Subtrees a problem publishes to the model on purpose. A forward task hands
# over its inputs by design — locking these away would make the task unsolvable
# rather than secure. Everything outside them (oracle/, golden/, grader/,
# problem.md) stays owner-only.
PUBLIC_SUBTREES = ("simulation",)


def _is_public_path(problem_dir: Path, path: Path) -> bool:
    """True for files a forward task is supposed to hand the model."""
    if path == problem_dir:
        return False
    head = path.relative_to(problem_dir).parts[0]
    return head in PUBLIC_SUBTREES


def harden_problem_permissions(problem_dir: Path) -> list[str]:
    """Make a problem tree readable only by its owner, without changing data.

    Taiga starts the MCP server as root and runs model-side tools as uid/gid
    1000. Owner-only modes therefore keep oracle, golden, and grader data away
    from bash/editor tools while still allowing a newly started MCP process to
    reload everything before grading.

    `simulation/` is the deliberate exception: a forward task's whole premise is
    that the model gets those inputs and runs the tool itself, so that subtree
    is published world-readable while staying root-*owned* — readable, not
    editable, so a solver cannot rewrite its own inputs. The problem directory
    itself then becomes traversable-but-not-listable (0711), which lets the
    model open `simulation/...` by its documented name without being able to
    enumerate what else sits beside it.

    Refusing to overwrite or unlink task files is important: Taiga is allowed
    to restart the MCP process between setup and grade, and process-local
    caches do not survive that restart.
    """
    if not permission_hardening_enabled():
        return []

    problem_dir = problem_dir.resolve()
    if not problem_dir.is_dir():
        raise InverseTaskError(f"Cannot protect missing problem directory {problem_dir}")

    has_public = any((problem_dir / name).is_dir() for name in PUBLIC_SUBTREES)

    protected: list[str] = []
    failures: list[str] = []
    paths = [problem_dir, *sorted(problem_dir.rglob("*"))]
    for path in paths:
        relative = "." if path == problem_dir else str(path.relative_to(problem_dir))
        if path.is_symlink():
            failures.append(f"{relative} is a symlink")
            continue
        try:
            stat = path.stat()
            if os.geteuid() == 0 and (stat.st_uid != 0 or stat.st_gid != 0):
                os.chown(path, 0, 0)
            public = _is_public_path(problem_dir, path)
            if path.is_dir():
                if path == problem_dir:
                    # o+x only when something inside is meant to be reachable.
                    desired_mode = 0o711 if has_public else 0o700
                else:
                    desired_mode = 0o755 if public else 0o700
            elif path.is_file():
                desired_mode = 0o644 if public else 0o600
            else:
                continue
            if stat.st_mode & 0o777 != desired_mode:
                path.chmod(desired_mode)
            protected.append(relative)
        except OSError as exc:
            failures.append(f"{relative}: {exc}")
            continue

    if failures and os.environ.get(
        "INVERSE_TASKS_REQUIRE_PRIVATE_PROBLEMS", "1"
    ).strip().lower() not in {"0", "false", "no", "off"}:
        detail = "; ".join(failures[:5])
        if len(failures) > 5:
            detail += f"; and {len(failures) - 5} more"
        raise InverseTaskError(
            "Could not make the problem files private to the MCP server. "
            "Use a writable preloaded-files mount owned by the server, or keep "
            f"model filesystem tools disabled. Details: {detail}"
        )

    return protected


def seal_secret_files(problem_dir: Path) -> list[str]:
    """Compatibility alias for the old, destructive hardening function.

    Older integrations may still call this name. It now changes permissions
    only; it never overwrites or deletes authoring data.
    """
    return harden_problem_permissions(problem_dir)


def _load_oracle_class(problem_dir: Path):
    setup_path = problem_dir / "oracle" / "setup.py"

    if not setup_path.is_file():
        raise OracleContractError(f"Missing oracle at {setup_path}")

    module_name = f"inverse_oracle_{problem_dir.name.replace('-', '_')}"
    # Drop a prior import so a re-uploaded oracle is picked up on the next load.
    sys.modules.pop(module_name, None)

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
        with protected_stdout():
            spec.loader.exec_module(module)
    finally:
        if added:
            try:
                sys.path.remove(oracle_dir)
            except ValueError:  # pragma: no cover - defensive
                pass

    oracle_cls = getattr(module, "Oracle", None)
    if oracle_cls is not None:
        return oracle_cls

    # Module-level probe functions are also supported: query_oracle(mode,
    # parameters) or handle_query(mode, parameters). Adapt that shape so the
    # same task folder can run on Taiga without a hand-written wrapper class.
    query_fn = getattr(module, "query_oracle", None)
    if not callable(query_fn):
        query_fn = getattr(module, "handle_query", None)
    if not callable(query_fn):
        raise OracleContractError(
            f"{setup_path} exposes no supported oracle entry point. Define either "
            "`class Oracle`, `query_oracle(mode, parameters)`, or "
            "`handle_query(mode, parameters)`."
        )

    signature = inspect.signature(query_fn)
    parameters = list(signature.parameters.values())
    accepts_keyword_params = any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters
    )
    accepts_parameter_object = any(
        p.name in {"parameters", "params"} for p in parameters[1:]
    )

    class ModuleOracle:
        """Adapter for a module-level inverse-task query function."""

        def query(self, mode, **params):
            if accepts_parameter_object:
                return query_fn(mode, params)
            if accepts_keyword_params:
                return query_fn(mode, **params)
            if len(parameters) >= 2:
                return query_fn(mode, params)
            if params:
                raise OracleContractError(
                    f"Module-level oracle {query_fn.__name__} accepts only a mode, "
                    f"but action {mode!r} supplied parameters {sorted(params)}."
                )
            return query_fn(mode)

        def __getattr__(self, name: str):
            # Public module constants such as M remain available to validation
            # solvers. Private module state never passes through this adapter.
            if name.startswith("_"):
                raise AttributeError(name)
            return getattr(module, name)

    ModuleOracle.__name__ = "Oracle"
    ModuleOracle.__qualname__ = "Oracle"

    for source_name, target_name in (
        ("ACTIONS", "ACTIONS"),
        ("actions", "actions"),
        ("BUDGET", "BUDGET"),
        ("_BUDGET", "BUDGET"),
        ("QUERY_BUDGET", "QUERY_BUDGET"),
        ("ANSWER_SCHEMA", "ANSWER_SCHEMA"),
        ("answer_schema", "answer_schema"),
    ):
        if hasattr(module, source_name) and not hasattr(ModuleOracle, target_name):
            setattr(ModuleOracle, target_name, getattr(module, source_name))
    return ModuleOracle


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


def read_direction(problem_dir: Path) -> Optional[str]:
    """`direction:` from config.yaml, lowercased. None if absent/unreadable.

    Parsed by hand rather than with PyYAML so the engine keeps its stdlib-only
    guarantee (see the module docstring).
    """
    config = problem_dir / "config.yaml"
    if not config.is_file():
        return None
    try:
        text = config.read_text()
    except OSError:  # pragma: no cover - defensive
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("direction:", "directionality:")):
            continue
        value = stripped.split(":", 1)[1]
        value = value.split("#", 1)[0].strip().strip("'\"").lower()
        if value:
            return value
    return None


def detect_direction(problem_dir: Path) -> str:
    """Decide whether a problem folder is inverse or forward.

    Structure wins over metadata, because the structure is what the engine can
    actually serve: a folder with an oracle can be probed, one with only
    `simulation/` cannot. `config.yaml` breaks the tie when a folder somehow has
    both or neither, and the validator flags that disagreement separately.
    """
    has_oracle = (problem_dir / "oracle" / "setup.py").is_file()
    has_simulation = (problem_dir / "simulation").is_dir()
    if has_oracle and not has_simulation:
        return "inverse"
    if has_simulation and not has_oracle:
        return "forward"
    declared = read_direction(problem_dir)
    if declared in ("inverse", "forward"):
        return declared
    return "inverse" if has_oracle else "forward"


class Problem:
    """A loaded problem: its prompt, its oracle, and its declared surface.

    Two directions are served:

    * **inverse** — `oracle/setup.py` defines the hidden system; the model
      probes it through `query_oracle` under a budget, then submits.
    * **forward** — no oracle. The model is handed the inputs under
      `simulation/` and must run the domain tool itself, then submit. There is
      nothing to probe, so no probe surface is published; grading is the same
      exact-match path against `golden/expected.json`.
    """

    def __init__(self, problem_id: str, directory: Path):
        self.problem_id = problem_id
        self.directory = directory
        self.direction = detect_direction(directory)

        if self.direction == "forward":
            self._init_forward()
        else:
            self._init_inverse()

        # Read the runtime inputs before setup makes this tree owner-only.
        self._prompt_text = self._read_prompt()
        self._golden = self._read_or_cache_golden()
        self._custom_grader = self._read_or_cache_grader()

    def _init_forward(self) -> None:
        self.oracle_cls = None
        self.oracle = None
        self.actions = []
        self.actions_declared = False
        self.budget_total = None
        simulation = self.directory / "simulation"
        self.simulation_files = (
            sorted(
                str(p.relative_to(simulation))
                for p in simulation.rglob("*")
                if p.is_file() and "__pycache__" not in p.parts
            )
            if simulation.is_dir()
            else []
        )

    def _init_inverse(self) -> None:
        self.simulation_files = []
        self.oracle_cls = _load_oracle_class(self.directory)
        with protected_stdout():
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
                f"Oracle for {self.problem_id!r} exposes no probe surface: declare `ACTIONS`, "
                "expose public methods, or provide a `query(mode, **params)` method."
            )

        budget = _first_attr(self.oracle, ("BUDGET", "budget", "QUERY_BUDGET"))
        self.budget_total: Optional[int] = int(budget) if isinstance(budget, numbers.Integral) else None

    def _read_prompt(self) -> str:
        path = self.directory / "problem.md"
        if not path.is_file():
            return ""
        return path.read_text()

    def _read_or_cache_golden(self) -> dict[str, Any]:
        path = self.directory / "golden" / "expected.json"
        if not path.is_file():
            raise InverseTaskError(f"Missing golden answer at {path}")
        data = json.loads(path.read_text())
        if "answer" not in data:
            raise InverseTaskError(f"{path} must contain an 'answer' key")
        return copy.deepcopy(data)

    def _read_or_cache_grader(self) -> Optional[Callable]:
        key = _cache_key(self.directory)
        if key in _GRADER_CACHE:
            return _GRADER_CACHE[key]
        grader = _load_custom_grader(self.directory)
        _GRADER_CACHE[key] = grader
        return grader

    @property
    def prompt(self) -> str:
        """The task text from problem.md, or "" if the prompt comes from Taiga.

        Empty is legitimate: an expert filling in the Create Problem form may
        supply the prompt there, in which case it arrives via extra_fields.
        """
        return self._prompt_text

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
        return copy.deepcopy(self._golden)

    @property
    def custom_grader(self) -> Optional[Callable]:
        return self._custom_grader

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
        # How many times setup_problem has run against this attempt. The harness
        # calls it once; anything higher means something re-entered the scaffold
        # hook, which is recorded in the grade so calibration can see it.
        self.setup_calls = 0
        # Set once grading has run. Grading is terminal, so a submission after
        # it is not a correction — it is a second guess informed by the first
        # grade, which is the loop that turns a reachable grader into an answer
        # oracle. Recorded either way so calibration can see the attempt.
        self.graded = False
        self.post_grade_submissions = 0

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
        described = {
            "problem_id": self.problem.problem_id,
            "direction": self.problem.direction,
            "title": self.problem.title,
            "actions": actions,
            "actions_declared": self.problem.actions_declared,
            "budget_total": self.problem.budget_total,
            "budget_used": self.calls_used,
            "budget_remaining": self.remaining,
            "answer_shape": self.problem.answer_shape(),
        }
        if self.problem.direction == "forward":
            described["note"] = (
                "This is a forward task: there is no oracle to probe. Work from "
                "the provided input files and submit your result."
            )
            described["input_files"] = list(self.problem.simulation_files)
        return described

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
        if self.problem.direction == "forward":
            raise UnknownAction(
                "This is a forward task: there is no oracle to query. The inputs "
                "you need are in the provided files — run the tool yourself and "
                "report the result with submit_answer."
            )
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
            with protected_stdout():
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
        if self.graded:
            # Refuse, don't silently accept: a solver that can reach both
            # grade_problem and submit_answer would otherwise iterate against
            # the grade until it lands, which is a search over the answer space
            # rather than an inverse measurement.
            self.post_grade_submissions += 1
            if is_taiga_runtime():
                raise AnswerFormatError(
                    "This attempt has already been graded; grading is terminal. "
                    "Resubmission is only available before grading."
                )

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
        self.graded = True
        golden = self.problem.golden()
        custom = self.problem.custom_grader
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
                "metadata": _scrub_metadata(
                    {
                        "reason": "no answer submitted",
                        "problem_id": self.problem.problem_id,
                        "budget_total": self.problem.budget_total,
                        "budget_used": self.calls_used,
                        "expected_fingerprint": answer_fingerprint(golden["answer"]),
                        "setup_calls": self.setup_calls,
                        "post_grade_submissions": self.post_grade_submissions,
                        "call_log": self.call_log,
                    }
                ),
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
    with protected_stdout():
        spec.loader.exec_module(module)
    grade = getattr(module, "grade", None)
    if not callable(grade):
        raise InverseTaskError(f"{path} must expose a callable `grade(...)`")

    def call(**kwargs):
        accepted = inspect.signature(grade).parameters
        with protected_stdout():
            if any(p.kind == p.VAR_KEYWORD for p in accepted.values()):
                return grade(**kwargs)
            return grade(**{k: v for k, v in kwargs.items() if k in accepted})

    return call


def grade_discloses_expected() -> bool:
    """Whether grade metadata may echo the golden answer. Never on Taiga.

    Taiga persists the grade payload into run logs that model-side tools can
    read — `/workdir/app.log` is world-readable while solver tools run as uid
    1000 — so echoing the answer there turns any reachable grader into an answer
    oracle: submit a throwaway, call the grader, read the log, resubmit the
    value it printed. That loop was demonstrated end-to-end against a shipped
    image, so the answer must not enter the payload in the first place: we
    cannot control who can call `grade_problem`, or where Taiga writes what it
    returns, but we can control what we put in it.

    Local authoring keeps the disclosure — the author already owns
    `golden/expected.json`, and the validator compares against it.
    """
    if is_taiga_runtime():
        return False
    return os.environ.get("INVERSE_TASKS_DISCLOSE_EXPECTED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _fingerprint_key() -> Optional[bytes]:
    """The secret that makes a fingerprint non-invertible, or None if absent.

    A plain hash of the answer is not a secret. The answer space of a typical
    inverse task is small — four integers inside stated ranges — and enumerating
    it takes milliseconds, so an unkeyed digest in a model-readable payload *is*
    the answer. Keyed with a secret the model cannot read, the digest still
    tells calibration whether two rollouts shared an instance while telling a
    solver nothing. The image generates the key at build time, root-only.
    """
    configured = os.environ.get("INVERSE_TASKS_FINGERPRINT_KEY")
    if configured:
        return configured.encode("utf-8")
    path = Path(
        os.environ.get(
            "INVERSE_TASKS_FINGERPRINT_KEY_FILE", "/var/lib/inverse-tasks/fingerprint.key"
        )
    )
    try:
        if path.is_file():
            return path.read_bytes()
    except OSError:  # pragma: no cover - unreadable key behaves as absent
        pass
    return None


def answer_fingerprint(answer: Any) -> Optional[str]:
    """Keyed digest of a golden answer, or None when it cannot be made safe.

    Calibration needs to know whether two rollouts were graded against the same
    hidden instance — that is how a task with hardcoded constants is caught. A
    digest answers that without putting the value in the payload, but only if it
    cannot simply be inverted.
    """
    canonical = json.dumps(
        _jsonable(answer), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    key = _fingerprint_key()
    if key is not None:
        return hmac.new(key, canonical, hashlib.sha256).hexdigest()[:16]
    if not is_taiga_runtime():
        # Authoring: the answer is not a secret from its own author.
        return hashlib.sha256(canonical).hexdigest()[:16]
    # No key inside the image: omit rather than ship an invertible digest.
    return None


# Keys that describe *which parts* of an answer were right. Individually
# harmless-looking, collectively an answer oracle: with a reachable grader, a
# solver reads `details[i].match` (or watches `matches` climb) and solves the
# elements one at a time, never touching the oracle. Removed wholesale rather
# than redacted, because the leak is the per-element resolution itself, not the
# golden value that used to sit beside it.
_PER_ELEMENT_KEYS = ("details", "matches", "total")


def _scrub_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Strip everything a model-readable grade payload must not carry.

    Removes the golden answer, anything a custom grader added under `expected`,
    and the per-element correctness channel. What survives is the model's own
    submission, the budget it spent, and the aggregate verdict — enough to
    diagnose a rollout, not enough to search with.
    """
    if grade_discloses_expected():
        return metadata
    return {
        key: value
        for key, value in metadata.items()
        if key != "expected" and key not in _PER_ELEMENT_KEYS
    }


def _normalise_grade(result: Any, golden: dict[str, Any], session: "Session") -> dict[str, Any]:
    """Coerce a comparison/custom-grader result into Taiga's Grade shape."""
    base_metadata = {
        "problem_id": session.problem.problem_id,
        "budget_total": session.problem.budget_total,
        "budget_used": session.calls_used,
        "submitted_raw": session.submission_raw,
        "submitted": session.submission,
        "setup_calls": session.setup_calls,
        "post_grade_submissions": session.post_grade_submissions,
        "call_log": session.call_log,
    }
    # Never the answer itself — see grade_discloses_expected(). Omitted entirely
    # when it could not be keyed, rather than shipped invertible.
    fingerprint = answer_fingerprint(golden["answer"])
    if fingerprint is not None:
        base_metadata["expected_fingerprint"] = fingerprint
    if grade_discloses_expected():
        base_metadata["expected"] = golden["answer"]

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
        grade["metadata"] = _scrub_metadata({**base_metadata, **(result.get("metadata") or {})})
        for passthrough in (
            "env_internal_failure",
            "env_internal_failure_logs",
            "penalties",
            "allow_unbounded",
        ):
            if passthrough in result:
                grade[passthrough] = result[passthrough]

        # Taiga rejects a grade whose weighted sum of subscores exceeds 1.0 with a
        # type error, which would fail the episode rather than score it. Normalise
        # instead, and record that we did, so a custom grader returning e.g. two
        # subscores at weight 1.0 each degrades to a weighted average.
        if not grade.get("allow_unbounded"):
            # Normalise on the WEIGHTS, not on the score this particular
            # submission happened to achieve. Keying off the achieved value left
            # a hole: weights of {1.0, 1.0} only got rescaled once a solver did
            # well enough to exceed 1.0, so a custom grader reporting
            # correctness 0.0 alongside any other full-marks subscore reached a
            # weighted Taiga score of 1.0 — a pass for a wrong answer. Weights
            # are a property of the grader, so the check has to be too.
            total = sum(grade["weights"].values())
            if total > 1.0 + 1e-9:
                grade["weights"] = {k: w / total for k, w in grade["weights"].items()}
                grade["metadata"]["weights_normalised"] = (
                    f"weights summed to {total:.4f} (>1.0) and were rescaled by "
                    f"1/{total:.4f}, so the grade is a weighted average within "
                    "[0, 1] rather than a sum that can exceed it"
                )
        return grade

    score = _clamp(float(result.get("score", 0.0)))
    metadata = _scrub_metadata(
        {
            **base_metadata,
            "correct": result.get("correct"),
            "matches": result.get("matches"),
            "total": result.get("total"),
            "details": result.get("details"),
            "scoring": result.get("scoring"),
            "tolerance": result.get("tolerance", golden.get("tolerance", 0)),
        }
    )
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
        number = float(value)
        if not math.isfinite(number):
            # NaN and Infinity are not JSON. Python's own encoder emits them as
            # bare tokens and its decoder accepts them, but a strict parser
            # rejects the payload — which turns a submission that should score
            # 0.0 into an environment failure, quietly removing a real failure
            # from the calibration sample. Render as a string: still visible in
            # the transcript, never equal to a numeric golden value.
            return repr(number)
        return number
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


def clear_runtime_caches() -> None:
    """Drop process-lifetime caches (tests / selftest only)."""
    _GRADER_CACHE.clear()


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
        return f'`query_oracle(mode="{action["name"]}", parameters={{}})`'
    rendered = ", ".join(
        f'"{p["name"]}": {_TYPE_PLACEHOLDER.get(p["type"], "<value>")}' for p in params
    )
    return (
        f'`query_oracle(mode="{action["name"]}", '
        f"parameters={{{rendered}}})`"
    )


def render_tool_guide(session: "Session", mode: str = "query") -> str:
    """Generate the calling contract appended to a problem's prompt.

    Experts write the science in `problem.md`; this guarantees the *mechanics*
    the model is told are the mechanics actually published, which is otherwise
    the easiest thing in the whole setup to get out of sync.
    """
    problem = session.problem
    lines = ["---", "", "## Using your tools", ""]

    if problem.direction == "forward":
        shape = problem.answer_shape()
        lines.append(
            "This task has no oracle to probe. Everything you need is in the "
            "input files described above — run the tool yourself, then report "
            "your result."
        )
        if problem.simulation_files:
            listed = ", ".join(f"`{name}`" for name in problem.simulation_files[:12])
            if len(problem.simulation_files) > 12:
                listed += f", … ({len(problem.simulation_files)} files total)"
            lines += ["", f"Input files: {listed}"]
        lines += [
            "",
            f"- **`submit_answer(answer)`** — pass a JSON value with this shape: "
            f"`submit_answer(answer={answer_example(shape)})`. You may resubmit; "
            "only your last submission is graded.",
        ]
        return "\n".join(lines)

    if problem.actions:
        if mode == "named":
            lines.append(
                "Probe the black box with these tools. Where the task above names an "
                "operation, this is how you call it:"
            )
        else:
            lines.append(
                "Probe the black box with **`query_oracle(mode, parameters)`**. "
                "Where the task above names an operation, call it like this:"
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
            "Probe the black box with **`query_oracle(mode, parameters)`**: "
            "`query_oracle(mode=<string>, parameters=<object>)`. The task above "
            "states which operations exist."
        )

    shape = problem.answer_shape()
    lines += [
        "",
        f"- **`submit_answer(answer)`** — pass a JSON value with this shape: "
        f"`submit_answer(answer={answer_example(shape)})`. You may resubmit; "
        "only your last submission is graded.",
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
