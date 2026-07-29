#!/usr/bin/env python3
"""Validate expert-authored inverse-task problems against the engine contract.

Run this before uploading a problem to Taiga:

    python3 tools/validate_problem.py                    # every problem
    python3 tools/validate_problem.py modular-black-box   # just one

Checks, per problem:
  contract    — oracle loads, declares a usable probe surface, budget sane
  golden      — golden/expected.json parses and matches the declared answer shape
  intended    — solution/main.py::solve passes, inside budget
  shortcut    — solution/shortcut.py::solve fails (a trap that isn't a trap
                is a broken task)
  budget      — the budget is actually enforced
  leakage     — the answer isn't printed in problem.md, and no hint/description
                names the method or the trap
  packaging   — the files the Docker image ships are all present

Exit code is non-zero if any problem has a FAIL. WARNs are advisory: they flag
things a human should look at (e.g. a hint that may give away the method).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "mcp_server"))

import core  # noqa: E402

# Files the Dockerfile copies into the image. Keep in sync with docker/collect_problems.sh.
SHIPPED_FILES = ("problem.md", "oracle/setup.py", "golden/expected.json")

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


def _dummy_params(action: dict[str, Any]) -> dict[str, Any]:
    """Plausible arguments for probing an action during validation."""
    sample = {"integer": 0, "number": 0.0, "string": "", "boolean": False, "array": [], "object": {}}
    return {
        p["name"]: p.get("default", sample[p["type"]])
        for p in action["params"]
        if p["required"] or "default" in p
    }


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
    return "\n".join(
        [
            f"\n--- Taiga Create Problem form values for {problem_id} ---",
            f"  Problem ID        {problem_id}",
            f"  Task Prompt       {prompt_note}",
            "  Tools             (LEAVE EMPTY)",
            "                    Giving the model bash or str_replace_editor lets it read",
            "                    oracle/setup.py and golden/expected.json straight off disk.",
            "  Grading Strategy  mcp   (NOT the default Rubric (Itemwise) — that ignores",
            "                    your golden answer and asks an LLM to judge the transcript)",
            "  Docker Image      the published inverse-tasks image",
            "  Startup Command   python -u /app/mcp_server/server.py",
            f"  Preloaded Files   mount this folder at /mnt/problems/{problem_id}/",
            "                    (ship problem.md, oracle/, golden/ — never solution/)",
            "  Tell model about uploaded files   OFF",
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
