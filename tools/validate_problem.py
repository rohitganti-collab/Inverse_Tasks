#!/usr/bin/env python3
"""Validate expert-authored problems against the engine contract.

Run this before uploading a problem to Taiga:

    python3 tools/validate_problem.py                    # every problem
    python3 tools/validate_problem.py modular-black-box   # just one

Inverse tasks (`oracle/setup.py`):
  contract    — oracle loads, declares a usable probe surface, budget sane
  golden      — golden/expected.json parses and matches the declared answer shape
  intended    — solution/main.py::solve(oracle) passes, inside budget
  shortcut    — solution/shortcut.py::solve(oracle) fails (a trap that isn't a
                trap is a broken task)
  budget      — the budget is actually enforced
  leakage     — the answer isn't printed in problem.md, and no hint/description
                names the method or the trap
  packaging   — the files the Docker image ships are all present

Forward tasks (`simulation/`, no oracle):
  inputs      — simulation/ exists and is non-empty
  golden      — as above
  intended    — solution/main.py::solve(simulation_dir) passes
  shortcut    — solution/shortcut.py::solve(simulation_dir) fails
  leakage     — the answer isn't printed in problem.md, and the prompt doesn't
                hand over the method/discretisation choice being tested
  packaging   — as above, with simulation/ in place of oracle/

Exit code is non-zero if any problem has a FAIL. WARNs are advisory: they flag
things a human should look at (e.g. a hint that may give away the method).
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "mcp_server"))

import core  # noqa: E402

# Runtime files the container needs. problem.md is optional when the Task Prompt
# is supplied on the Taiga form.
SHIPPED_FILES = ("oracle/setup.py", "golden/expected.json")
SHIPPED_FILES_FORWARD = ("golden/expected.json",)

# Words that, in a *solver-visible* string, risk naming the method or the trap.
# Advisory only — the expert decides. See step 8 of the authoring instructions.
LEAKAGE_TERMS = (
    "adjacent",
    "consecutive",
    "shortcut",
    "trap",
    "naive",
    "mistake",
    "instead of",
    "don't use",
    "do not use",
    "the trick",
)

# Forward-task equivalent: phrases that hand over the method/discretisation
# decision the task exists to test. Advisory only.
LEAKAGE_TERMS_FORWARD = LEAKAGE_TERMS + (
    "refine the mesh",
    "mesh refinement",
    "too coarse",
    "use a transient",
    "steady-state is",
    "converged",
    "convergence check",
    "time step",
    "timestep",
    "stability criterion",
    "must be smaller than",
)

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


class Report:
    def __init__(self, problem_id: str):
        self.problem_id = problem_id
        self.rows: list[tuple[str, str, str]] = []

    def add(self, status: str, check: str, detail: str = "") -> None:
        self.rows.append((status, check, detail))

    @property
    def failed(self) -> bool:
        return any(status == FAIL for status, _, _ in self.rows)

    def render(self) -> str:
        icon = {PASS: "  ok  ", WARN: " warn ", FAIL: " FAIL "}
        lines = [f"\n=== {self.problem_id} ==="]
        for status, check, detail in self.rows:
            line = f"[{icon[status]}] {check}"
            if detail:
                line += f"\n           {detail}"
            lines.append(line)
        return "\n".join(lines)


def _load_solver(path: Path):
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"solver_{path.parent.parent.name}_{path.stem}", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, "solve", None)


def _run_solver(problem_id: str, solver, roots) -> tuple[Optional[Any], Optional[str], int]:
    """Run a solver against a fresh session. Returns (answer, error, budget_used)."""
    session = core.load_session(problem_id, roots)
    proxy = _OracleProxy(session)
    try:
        answer = solver(proxy)
    except Exception as exc:  # noqa: BLE001 - report any solver failure verbatim
        return None, f"{type(exc).__name__}: {exc}", session.calls_used
    return core._jsonable(answer), None, session.calls_used


class _OracleProxy:
    """Presents a Session as an oracle, so solvers are metered like the model is.

    Solvers written either way work: `proxy.evaluate(0)` and
    `proxy.query("evaluate", x=0)` both route through the budgeted Session.
    Public oracle constants (M, BUDGET, ...) pass through; private ones do not,
    so a solver can't cheat by reading `_A`.
    """

    def __init__(self, session: core.Session):
        self._session = session

    def query(self, mode, *args, **params):
        action = self._session.problem.action(mode)
        return self._session.query(mode, self._bind(action, args, params, mode))

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(
                f"{name!r} is hidden from solvers — the intended solution may not read "
                "the oracle's private state."
            )
        action = self._session.problem.action(name)
        if action is not None:
            def call(*args, **params):
                return self._session.query(name, self._bind(action, args, params, name))

            return call
        value = getattr(self._session.problem.oracle, name)
        if callable(value):
            raise AttributeError(
                f"{name!r} is not a declared action; add it to the oracle's ACTIONS "
                "if the solver is meant to call it."
            )
        return value

    @staticmethod
    def _bind(action, args, params, label: str) -> dict[str, Any]:
        """Map positional args onto the declared parameter order.

        Lets a solver write either `oracle.evaluate(0)` or
        `oracle.evaluate(x=0)`, matching what the authoring guide documents.
        """
        if not args:
            return dict(params)
        if action is None:
            raise TypeError(
                f"{label!r} is not a declared action, so positional arguments cannot be "
                "mapped to parameter names — pass them by keyword."
            )
        names = [p["name"] for p in action["params"]]
        if len(args) > len(names):
            raise TypeError(
                f"{label!r} takes at most {len(names)} argument(s) ({', '.join(names) or 'none'}), "
                f"got {len(args)}"
            )
        bound = dict(zip(names, args))
        clashes = set(bound) & set(params)
        if clashes:
            raise TypeError(f"{label!r} got multiple values for {sorted(clashes)}")
        bound.update(params)
        return bound


def validate(problem_id: str, directory: Path, roots) -> Report:
    report = Report(problem_id)

    # ---- contract ---------------------------------------------------------- #
    try:
        session = core.load_session(problem_id, roots)
    except core.InverseTaskError as exc:
        report.add(FAIL, "contract: oracle loads", str(exc))
        return report

    problem = session.problem

    # ---- direction ---------------------------------------------------------- #
    # The engine decides direction from structure; config.yaml is documentation.
    # When they disagree, one of the two is a typo and the expert should know.
    declared = core.read_direction(directory)
    if declared and declared not in ("inverse", "forward"):
        report.add(
            WARN,
            "direction: config.yaml value understood",
            f"direction: {declared!r} is neither 'inverse' nor 'forward'; the engine "
            f"is treating this as {problem.direction}.",
        )
    elif declared and declared != problem.direction:
        report.add(
            FAIL,
            "direction: config.yaml matches the folder",
            f"config.yaml says direction: {declared}, but the folder looks "
            f"{problem.direction} "
            f"({'oracle/setup.py present' if problem.direction == 'inverse' else 'simulation/ present, no oracle'}).",
        )
    else:
        report.add(PASS, f"direction: {problem.direction}")

    if problem.direction == "forward":
        _validate_forward(report, problem, directory)
        return report

    names = [a["name"] for a in problem.actions]
    if not problem.actions_declared:
        report.add(
            WARN,
            "contract: ACTIONS declared",
            "No ACTIONS on the oracle. The engine falls back to introspection/generic "
            "query(), so the model won't get named tools. Declaring ACTIONS is recommended.",
        )
    report.add(PASS, f"contract: actions = {names or '<generic query passthrough>'}")

    if problem.budget_total is None:
        report.add(
            WARN,
            "contract: BUDGET declared",
            "No BUDGET on the oracle — the task is unbudgeted, so brute force may be "
            "possible. Set BUDGET unless that is intentional.",
        )
    else:
        report.add(PASS, f"contract: budget = {problem.budget_total}")

    # ---- every declared action is actually serviceable --------------------- #
    # A declaration the oracle can't service is the most common authoring bug:
    # ACTIONS promises a parameter that the oracle's method or query() signature
    # doesn't accept, and the model gets an error instead of an observation.
    unserviceable = []
    for action in problem.actions:
        probe = core.load_session(problem_id, roots)  # fresh: don't share budget
        try:
            probe.query(action["name"], _dummy_params(action))
        except (core.OracleContractError, core.UnknownAction) as exc:
            unserviceable.append(f"{action['name']}: {exc}")
        except core.InverseTaskError:
            pass  # budget/domain errors are fine; the call reached the oracle
    if unserviceable:
        report.add(
            FAIL,
            "contract: declared actions are serviceable",
            "\n           ".join(unserviceable),
        )
    elif problem.actions:
        report.add(PASS, "contract: every declared action reaches the oracle")

    # ---- observations survive the MCP boundary ----------------------------- #
    # A shipped image once declared the probe tool as `-> str | int | dict`.
    # FastMCP builds its output schema from that annotation, so an oracle
    # returning a float failed validation on *every* reading and the value
    # reached the model only inside an error string. Runs still scored 1.0
    # because the models parsed the number out of the error text, so nothing
    # looked broken. Check the values an oracle actually produces can be
    # rendered and read back unchanged.
    untransportable = []
    for action in problem.actions:
        probe = core.load_session(problem_id, roots)
        try:
            observation = probe.query(action["name"], _dummy_params(action))
        except core.InverseTaskError:
            continue  # already reported above, or a legitimate domain error
        try:
            rendered = json.dumps(core._jsonable(observation))
            if json.loads(rendered) != core._jsonable(observation):
                raise ValueError("value changed on round trip")
        except (TypeError, ValueError) as exc:
            untransportable.append(
                f"{action['name']} returned {type(observation).__name__}: {exc}"
            )
    if untransportable:
        report.add(
            FAIL,
            "transport: observations survive the MCP boundary",
            "\n           ".join(untransportable),
        )
    elif problem.actions:
        report.add(PASS, "transport: observations round-trip unchanged")

    # ---- golden ----------------------------------------------------------- #
    try:
        golden = problem.golden()
    except core.InverseTaskError as exc:
        report.add(FAIL, "golden: expected.json", str(exc))
        return report

    shape = problem.answer_shape()
    shape_problems = core.check_answer_shape(golden["answer"], shape)
    if shape_problems:
        report.add(
            FAIL,
            "golden: matches declared ANSWER_SCHEMA",
            "; ".join(shape_problems) + f" (schema: {json.dumps(shape, sort_keys=True)})",
        )
    else:
        report.add(PASS, f"golden: shape {json.dumps(shape, sort_keys=True)}")

    if golden.get("keys") and isinstance(golden["answer"], list):
        if len(golden["keys"]) != len(golden["answer"]):
            report.add(
                FAIL,
                "golden: keys align with answer",
                f"{len(golden['keys'])} key(s) for {len(golden['answer'])} answer element(s)",
            )

    # ---- the grade payload must not carry the answer ----------------------- #
    # Taiga writes grade output to /workdir/app.log, which is world-readable
    # while solver tools run as uid 1000. If the payload contains the golden
    # answer and `grade_problem` is reachable, the task is a four-step exploit:
    # submit a throwaway, grade, read the log, resubmit. Grade a deliberately
    # wrong answer under the image's runtime and confirm nothing golden appears.
    previous_runtime = os.environ.get("INVERSE_TASKS_RUNTIME")
    os.environ["INVERSE_TASKS_RUNTIME"] = "taiga"
    try:
        privacy_probe = core.load_session(problem_id, roots)
        privacy_probe.submit(_deliberately_wrong(golden["answer"]))
        payload = json.dumps(core._jsonable(privacy_probe.grade()), sort_keys=True)
    except core.InverseTaskError as exc:
        report.add(WARN, "privacy: could not grade a probe answer", str(exc))
        payload = ""
    finally:
        if previous_runtime is None:
            os.environ.pop("INVERSE_TASKS_RUNTIME", None)
        else:
            os.environ["INVERSE_TASKS_RUNTIME"] = previous_runtime

    if payload:
        leaked = _answer_literals_in(payload, golden["answer"])
        if '"expected"' in payload or leaked:
            # Built outside the f-string: the image runs Python 3.11, where a
            # backslash inside an f-string expression is a syntax error.
            where = ", ".join(leaked) if leaked else 'under an "expected" key'
            report.add(
                FAIL,
                "privacy: grade payload hides the answer",
                f"golden value(s) {where} appear in the grade metadata, which "
                "Taiga logs where the model can read it",
            )
        else:
            report.add(PASS, "privacy: grade payload carries no golden values")

    # ---- fixed instance vs. seeded family ---------------------------------- #
    # A task whose hidden constants are hardcoded grades against the same golden
    # answer in every episode, so a model that has seen it once can submit from
    # memory with zero probes. That is what an 8/8, zero-variance pass rate on a
    # task labelled "hard" actually means.
    if not _oracle_varies_per_episode(directory):
        report.add(
            WARN,
            "instance: hidden values look fixed across episodes",
            "oracle/setup.py takes no seed/instance argument and reads no "
            "environment, so every rollout has the same answer "
            f"(fingerprint {core.answer_fingerprint(golden['answer'])}). A model "
            "that has seen this task can score 1.0 without querying. Consider a "
            "seeded family: draw the hidden values per episode and write the "
            "matching golden/expected.json at setup time.",
        )
    else:
        report.add(PASS, "instance: oracle can vary per episode")

    # ---- intended solver -------------------------------------------------- #
    intended = _load_solver(directory / "solution" / "main.py")
    if intended is None:
        report.add(
            WARN,
            "intended: solution/main.py",
            "No intended solver found — nothing proves the task is solvable within budget.",
        )
    else:
        answer, error, used = _run_solver(problem_id, intended, roots)
        if error:
            report.add(FAIL, "intended: solve() runs", error)
        else:
            verdict = core.compare_answers(answer, golden)
            if verdict["correct"]:
                report.add(
                    PASS,
                    f"intended: passes using {used}/{problem.budget_total or '∞'} budgeted call(s)",
                )
            else:
                report.add(
                    FAIL,
                    "intended: passes",
                    f"returned {json.dumps(answer)}, expected {json.dumps(golden['answer'])}",
                )
            if problem.budget_total is not None and used > problem.budget_total:
                report.add(
                    FAIL,
                    "intended: stays within budget",
                    f"used {used} of {problem.budget_total}",
                )

    # ---- shortcut solver -------------------------------------------------- #
    shortcut = _load_solver(directory / "solution" / "shortcut.py")
    if shortcut is None:
        report.add(
            WARN,
            "shortcut: solution/shortcut.py",
            "No shortcut solver — the named near-miss is unproven. The authoring guide "
            "requires demonstrating that the trap actually fails.",
        )
    else:
        answer, error, _ = _run_solver(problem_id, shortcut, roots)
        if error:
            report.add(PASS, f"shortcut: fails ({error})")
        else:
            verdict = core.compare_answers(answer, golden)
            if verdict["correct"]:
                report.add(
                    FAIL,
                    "shortcut: fails",
                    f"the shortcut PASSED with {json.dumps(answer)} — the trap does not "
                    "discriminate, so the task is broken",
                )
            else:
                report.add(
                    PASS,
                    f"shortcut: fails as intended (returned {json.dumps(answer)})",
                )
                if verdict["score"] > 0:
                    report.add(
                        WARN,
                        "shortcut: scores zero",
                        f"the near-miss earns partial credit ({verdict['score']:.2f}); with "
                        "scoring='partial' a wrong answer is still rewarded",
                    )

    # ---- budget enforcement ----------------------------------------------- #
    if problem.budget_total is not None and names:
        budgeted = next((a for a in problem.actions if a["costs_budget"]), None)
        if budgeted is None:
            report.add(
                WARN,
                "budget: some action spends budget",
                "BUDGET is set but no action has costs_budget=True, so it can never bind.",
            )
        else:
            probe = core.load_session(problem_id, roots)
            params = _dummy_params(budgeted)
            enforced = False
            for _ in range(problem.budget_total + 1):
                try:
                    probe.query(budgeted["name"], params)
                except core.BudgetExceeded:
                    enforced = True
                    break
                except core.InverseTaskError as exc:
                    report.add(
                        WARN,
                        "budget: enforcement probe",
                        f"could not probe {budgeted['name']!r}: {exc}",
                    )
                    enforced = True  # inconclusive, not a failure
                    break
            if enforced:
                report.add(PASS, f"budget: enforced after {problem.budget_total} call(s)")
            else:
                report.add(
                    FAIL,
                    "budget: enforced",
                    f"made {problem.budget_total + 1} budgeted calls without being cut off",
                )

    # ---- leakage ---------------------------------------------------------- #
    prompt = problem.prompt
    leaked = _answer_literals_in(prompt, golden["answer"])
    if leaked:
        report.add(
            FAIL,
            "leakage: answer absent from problem.md",
            f"problem.md contains the answer value(s) {leaked}. If that is a "
            "coincidence (a stated constant that happens to equal an answer "
            "element), reword the prompt or the task so the two can't be confused.",
        )
    else:
        report.add(PASS, "leakage: answer not printed in problem.md")

    solver_visible = [("problem.md", prompt)]
    for action in problem.actions:
        solver_visible.append((f"ACTIONS[{action['name']}].description", action["description"]))
    # Hint/diagnostic output is solver-visible too, and the authoring guide is
    # explicit that it must not name the method either.
    for action in problem.actions:
        if action["costs_budget"]:
            continue
        try:
            observed = core.load_session(problem_id, roots).query(
                action["name"], _dummy_params(action)
            )
        except core.InverseTaskError as exc:
            report.add(
                WARN,
                f"leakage: could not read {action['name']}() output",
                f"{exc} — its text was not scanned for method/trap vocabulary",
            )
            continue
        solver_visible.append((f"{action['name']}() output", str(observed)))

    suspicious = []
    for where, text in solver_visible:
        for term in LEAKAGE_TERMS:
            if re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE):
                suspicious.append(f"{where}: {term!r}")
    if suspicious:
        report.add(
            WARN,
            "leakage: solver-visible text may name the method or trap",
            "; ".join(suspicious)
            + "\n           Step 8 of the authoring guide: never hint at the fix, "
            "including in tool help text.",
        )
    else:
        report.add(PASS, "leakage: no method/trap vocabulary in solver-visible text")

    # ---- packaging -------------------------------------------------------- #
    missing = [f for f in SHIPPED_FILES if not (directory / f).is_file()]
    if missing:
        report.add(FAIL, "packaging: image files present", f"missing {missing}")
    else:
        report.add(PASS, f"packaging: ships {list(SHIPPED_FILES)}")

    return report


def _validate_forward(report: Report, problem, directory: Path) -> None:
    """Checks for a forward task: no oracle, inputs handed to the model directly.

    The solver contract mirrors the inverse one but takes the input directory
    instead of an oracle proxy:

        def solve(simulation_dir: Path) -> answer

    There is no budget and no probe surface, so difficulty has to live entirely
    in the method decision the prompt declines to make for the model. The
    shortcut solver is what proves that decision actually matters.
    """
    simulation = directory / "simulation"
    files = problem.simulation_files
    if not files:
        report.add(
            FAIL,
            "inputs: simulation/ is non-empty",
            f"{simulation} has no files. A forward task must hand the model "
            "something to run.",
        )
        return
    report.add(PASS, f"inputs: simulation/ ships {len(files)} file(s): {files[:6]}")

    try:
        golden = problem.golden()
    except core.InverseTaskError as exc:
        report.add(FAIL, "golden: expected.json", str(exc))
        return

    shape = problem.answer_shape()
    shape_problems = core.check_answer_shape(golden["answer"], shape)
    if shape_problems:
        report.add(
            FAIL,
            "golden: matches inferred answer shape",
            "; ".join(shape_problems) + f" (shape: {json.dumps(shape, sort_keys=True)})",
        )
    else:
        report.add(PASS, f"golden: shape {json.dumps(shape, sort_keys=True)}")

    if golden.get("tolerance", 0) == 0 and shape.get("type") in ("number", "array"):
        report.add(
            WARN,
            "golden: tolerance is 0 on a floating-point answer",
            "A simulation result rarely reproduces bit-for-bit across platforms. "
            "Set a tolerance derived from the distance to your nearest near-miss, "
            "or state the required rounding in problem.md.",
        )

    # ---- solvers ----------------------------------------------------------- #
    intended = _load_solver(directory / "solution" / "main.py")
    if intended is None:
        report.add(
            WARN,
            "intended: solution/main.py",
            "No intended solver — nothing proves the task is solvable from the "
            "inputs alone.",
        )
    else:
        answer, error = _run_forward_solver(intended, simulation)
        if error:
            report.add(FAIL, "intended: solve() runs", error)
        elif core.compare_answers(answer, golden)["correct"]:
            report.add(PASS, f"intended: passes (returned {json.dumps(answer)})")
        else:
            report.add(
                FAIL,
                "intended: passes",
                f"returned {json.dumps(answer)}, expected {json.dumps(golden['answer'])}",
            )

    shortcut = _load_solver(directory / "solution" / "shortcut.py")
    if shortcut is None:
        report.add(
            WARN,
            "shortcut: solution/shortcut.py",
            "No shortcut solver. For a forward task this is the only evidence that "
            "the default method choice actually fails — without it the task may be "
            "testing nothing but the ability to run the tool.",
        )
    else:
        answer, error = _run_forward_solver(shortcut, simulation)
        if error:
            report.add(PASS, f"shortcut: fails ({error})")
        else:
            verdict = core.compare_answers(answer, golden)
            if verdict["correct"]:
                report.add(
                    FAIL,
                    "shortcut: fails",
                    f"the shortcut PASSED with {json.dumps(answer)} — the naive "
                    "method choice gets the right answer, so the task does not "
                    "discriminate",
                )
            else:
                report.add(
                    PASS, f"shortcut: fails as intended (returned {json.dumps(answer)})"
                )

    # ---- leakage ------------------------------------------------------------ #
    prompt = problem.prompt
    leaked = _answer_literals_in(prompt, golden["answer"])
    if leaked:
        report.add(
            FAIL,
            "leakage: answer absent from problem.md",
            f"problem.md contains the answer value(s) {leaked}.",
        )
    else:
        report.add(PASS, "leakage: answer not printed in problem.md")

    suspicious = [
        term
        for term in LEAKAGE_TERMS_FORWARD
        if re.search(rf"\b{re.escape(term)}\b", prompt, re.IGNORECASE)
    ]
    if suspicious:
        report.add(
            WARN,
            "leakage: problem.md may hand over the method choice",
            f"found {suspicious}\n           A forward task's difficulty IS the "
            "discretisation/solver/convergence decision. Naming it removes the task.",
        )
    else:
        report.add(PASS, "leakage: no method vocabulary in problem.md")

    missing = [f for f in SHIPPED_FILES_FORWARD if not (directory / f).is_file()]
    if missing:
        report.add(FAIL, "packaging: image files present", f"missing {missing}")
    else:
        report.add(
            PASS, f"packaging: ships {list(SHIPPED_FILES_FORWARD)} + simulation/"
        )


def _run_forward_solver(solver, simulation: Path) -> tuple[Optional[Any], Optional[str]]:
    """Run a forward solver against the input directory. Returns (answer, error)."""
    try:
        return solver(simulation), None
    except Exception as exc:  # noqa: BLE001 - report any solver failure verbatim
        return None, f"{type(exc).__name__}: {exc}"


def _dummy_params(action: dict[str, Any]) -> dict[str, Any]:
    """Plausible arguments for probing an action during validation."""
    sample = {"integer": 0, "number": 0.0, "string": "", "boolean": False, "array": [], "object": {}}
    return {
        p["name"]: p.get("default", sample[p["type"]])
        for p in action["params"]
        if p["required"] or "default" in p
    }


def _deliberately_wrong(answer: Any) -> Any:
    """An answer shaped like the golden one but certainly not equal to it.

    Used to grade a probe submission without accidentally scoring 1.0, so the
    privacy check exercises the same code path a failing rollout takes — which
    is the path that leaked, since Taiga logs the payload on failures too.
    """
    def nudge(value: Any) -> Any:
        if isinstance(value, bool):
            return not value
        if isinstance(value, (int, float)):
            return value + 12345.6789
        if isinstance(value, str):
            return value + "-wrong"
        return value

    if isinstance(answer, (list, tuple)):
        return [nudge(v) for v in answer]
    if isinstance(answer, dict):
        return {k: nudge(v) for k, v in answer.items()}
    return nudge(answer)


# Names whose presence in __init__ means the hidden values can differ per run.
_VARIABILITY_NAMES = frozenset(
    {
        "random",
        "randrange",
        "randint",
        "uniform",
        "choice",
        "sample",
        "shuffle",
        "seed",
        "default_rng",
        "environ",
        "getenv",
        "uuid",
        "uuid4",
        "urandom",
        "token_hex",
    }
)


def _oracle_varies_per_episode(directory: Path) -> bool:
    """Whether the oracle's hidden values can differ between rollouts.

    Read from the syntax tree rather than by grepping the text: an early
    substring version of this check passed `modular-black-box` — whose secrets
    are the class constants `_A = 23` / `_B = 58` — purely because the word
    "instance" appeared in a comment. Comments cannot reseed an oracle.

    The task is fixed when it has private class-level constants for its secrets,
    `__init__` takes nothing that could select an instance, and nothing in the
    constructor touches randomness or the environment. Anything less certain
    returns True, so this warns only where it is sure.
    """
    source_path = directory / "oracle" / "setup.py"
    if not source_path.is_file():
        return True
    try:
        tree = ast.parse(source_path.read_text())
    except (OSError, SyntaxError):  # pragma: no cover - defensive
        return True

    oracle = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "Oracle"),
        None,
    )
    if oracle is None:
        return True  # module-level oracle; not enough structure to judge

    literal_secrets: list[str] = []
    dynamic = False

    for node in oracle.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.startswith("_"):
                    if isinstance(node.value, ast.Constant):
                        literal_secrets.append(target.id)
                    else:
                        dynamic = True
        elif isinstance(node, ast.FunctionDef) and node.name == "__init__":
            takes_selector = (
                [a for a in node.args.args if a.arg != "self"]
                or node.args.kwonlyargs
                or node.args.vararg is not None
                or node.args.kwarg is not None
            )
            if takes_selector:
                return True
            for sub in ast.walk(node):
                if isinstance(sub, ast.Attribute) and sub.attr in _VARIABILITY_NAMES:
                    dynamic = True
                elif isinstance(sub, ast.Name) and sub.id in _VARIABILITY_NAMES:
                    dynamic = True

    if dynamic:
        return True
    return not literal_secrets


def _answer_literals_in(text: str, answer: Any) -> list[str]:
    """Find golden answer values quoted verbatim in solver-visible text.

    Only flags values distinctive enough to matter — a modulus of 97 or an
    answer of 0/1 shows up in ordinary prose constantly.
    """
    values = answer if isinstance(answer, (list, tuple)) else [answer]
    hits = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if abs(value) < 10:  # too common to be evidence
            continue
        # Reject matches inside a longer number (14271, 1.4271, 42710, 4271.5)
        # but still catch a value ending a sentence ("a is 4271.").
        pattern = rf"(?<![\d.]){re.escape(str(value))}(?!\d)(?!\.\d)"
        if re.search(pattern, text):
            hits.append(str(value))
    return hits


def taiga_form_values(problem_id: str, directory: Path) -> str:
    """The exact values to type into Taiga's Create Problem form."""
    has_prompt = (directory / "problem.md").is_file()
    prompt_note = (
        "paste the contents of problem.md (the container appends the tool "
        "instructions automatically)"
        if has_prompt
        else "write the task prompt here — this problem folder has no problem.md"
    )
    direction = core.detect_direction(directory)

    if direction == "forward":
        return "\n".join(
            [
                f"\n--- Taiga Create Problem form values for {problem_id} (FORWARD) ---",
                f"  Problem ID        {problem_id}",
                f"  Task Prompt       {prompt_note}",
                "  Tools             bash   (the model MUST be able to run the tool)",
                "  Grading Strategy  mcp   (NOT Agentic Grader, NOT Rubric Itemwise)",
                "  Docker Image      an image that contains your domain toolchain",
                "                    (see docs/TAIGA_RUNBOOK.md §7 — the default",
                "                     inverse-tasks image has no scientific tools)",
                "  Startup Command   python -u /app/mcp_server/server.py",
                f"  Preloaded Files   mount simulation/ + golden/ at /mnt/problems/{problem_id}/",
                "                    NEVER mount solution/, BRIEF, STATE, or reasoning_trap",
                "  Supporting Files  optional human review only (NOT mounted)",
                "  Tell model about uploaded files   ON   (it must know the inputs exist)",
                "  Security          golden/ stays root-only; bash runs as uid 1000",
            ]
        )

    return "\n".join(
        [
            f"\n--- Taiga Create Problem form values for {problem_id} (INVERSE) ---",
            f"  Problem ID        {problem_id}",
            f"  Task Prompt       {prompt_note}",
            "  Tools             EMPTY   (delete bash and str_replace_editor)",
            "  Grading Strategy  mcp   (NOT Agentic Grader, NOT Rubric Itemwise)",
            "  Docker Image      the published inverse-tasks image",
            "  Startup Command   python -u /app/mcp_server/server.py",
            f"  Preloaded Files   mount oracle/ + golden/ at /mnt/problems/{problem_id}/",
            "                    NEVER mount solution/, BRIEF, STATE, or reasoning_trap",
            "  Supporting Files  optional human review only (NOT mounted)",
            "  Tell model about uploaded files   OFF",
            "  Security          MCP/problem files are root-only; model tools run as uid 1000",
        ]
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("problem_ids", nargs="*", help="Problem ids to check (default: all)")
    parser.add_argument(
        "--problems-dir",
        action="append",
        default=None,
        help="Override where problems are searched for (repeatable)",
    )
    parser.add_argument(
        "--no-form-values",
        action="store_true",
        help="Skip printing the Taiga Create Problem form values for passing problems",
    )
    args = parser.parse_args(argv)

    roots = args.problems_dir
    available = core.discover_problems(roots)
    if not available:
        print(f"No problems found in {[str(p) for p in core.problem_roots(roots)]}", file=sys.stderr)
        return 1

    targets = args.problem_ids or sorted(available)
    unknown = [t for t in targets if t not in available]
    if unknown:
        print(
            f"Unknown problem id(s) {unknown}. Available: {sorted(available)}",
            file=sys.stderr,
        )
        return 1

    reports = [validate(pid, available[pid], roots) for pid in targets]
    for report in reports:
        print(report.render())
        if not report.failed and not args.no_form_values:
            print(taiga_form_values(report.problem_id, available[report.problem_id]))

    failures = [r.problem_id for r in reports if r.failed]
    warnings = sum(1 for r in reports for status, _, _ in r.rows if status == WARN)
    print(
        f"\n{len(reports)} problem(s) checked, {len(failures)} failing, {warnings} warning(s)."
    )
    if failures:
        print(f"FAILING: {failures}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
