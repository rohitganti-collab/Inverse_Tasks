#!/usr/bin/env python3
"""Check every problem folder against the oracle contract.

Standard library only; nothing here is needed at run time. It exists so a newly
dropped-in problem folder can be checked before it reaches the gym.

    python3 verify_problems.py                  # all problems
    python3 verify_problems.py modular-black-box

Checks per problem:
  * the three required files exist
  * golden/expected.json is {"answer": ..., "tolerance": N}
  * oracle/setup.py defines `Oracle`, importable with no third-party deps
  * Oracle().query("help") works and does not cost budget
  * every declared ACTION is reachable through query()
  * an unknown mode raises rather than returning
  * BUDGET is enforced (the call after the last one raises)
  * two Oracle() instances do not share budget
  * probing does not write to stdout
  * the golden answer does not appear verbatim in problem.md

Exit code is non-zero if any problem fails.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROBLEMS = ROOT / "problems"
REQUIRED = ("problem.md", "oracle/setup.py", "golden/expected.json")


def load_oracle_class(setup_path: Path):
    spec = importlib.util.spec_from_file_location(
        f"oracle_{setup_path.parent.parent.name.replace('-', '_')}", setup_path
    )
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(setup_path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return getattr(module, "Oracle", None)


def sample_params(action: dict) -> dict:
    defaults = {
        "integer": 0, "number": 0.0, "string": "",
        "boolean": False, "array": [], "object": {},
    }
    params = action.get("params") or {}
    return {
        name: spec.get("default", defaults.get(spec.get("type", "string"), 0))
        for name, spec in params.items()
        if spec.get("required", "default" not in spec) or "default" in spec
    }


def check(problem_id: str, directory: Path) -> list[str]:
    errors: list[str] = []

    def fail(message: str) -> None:
        errors.append(message)

    for relative in REQUIRED:
        if not (directory / relative).is_file():
            fail(f"missing required file: {relative}")
    if errors:
        return errors

    # golden/expected.json
    try:
        golden = json.loads((directory / "golden" / "expected.json").read_text())
    except json.JSONDecodeError as exc:
        return [f"golden/expected.json is not valid JSON: {exc}"]
    if "answer" not in golden:
        fail("golden/expected.json has no 'answer' key")
    if "tolerance" not in golden:
        fail("golden/expected.json has no 'tolerance' key")
    extra = set(golden) - {"answer", "tolerance"}
    if extra:
        fail(f"golden/expected.json has unexpected key(s) {sorted(extra)}; "
             'the agreed format is {"answer": ..., "tolerance": N}')

    # oracle
    try:
        oracle_cls = load_oracle_class(directory / "oracle" / "setup.py")
    except Exception as exc:  # noqa: BLE001 - report any import failure verbatim
        return errors + [f"oracle/setup.py failed to import: {type(exc).__name__}: {exc}"]
    if oracle_cls is None:
        return errors + ["oracle/setup.py defines no class named `Oracle`"]
    if not hasattr(oracle_cls, "query"):
        return errors + ["Oracle has no `query` method (the stable probe contract)"]

    actions = list(getattr(oracle_cls, "ACTIONS", []) or [])
    budget = getattr(oracle_cls, "BUDGET", None)

    # help() is free, and probing never writes to stdout
    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured):
            oracle = oracle_cls()
            oracle.query("help")
    except Exception as exc:  # noqa: BLE001
        fail(f'query("help") raised: {type(exc).__name__}: {exc}')
    else:
        if isinstance(budget, int) and getattr(oracle, "_used", 0) != 0:
            fail('query("help") consumed budget; it should be free')
    if captured.getvalue():
        fail(f"oracle wrote to stdout: {captured.getvalue()[:120]!r}")

    # every declared action is reachable
    for action in actions:
        name = action.get("name")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                oracle_cls().query(name, **sample_params(action))
        except (ValueError, TypeError) as exc:
            fail(f"declared action {name!r} is not serviceable by query(): {exc}")
        except RuntimeError:
            pass  # budget-related, still reached the oracle

    # unknown modes must raise
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            oracle_cls().query("__definitely_not_a_mode__")
    except Exception:  # noqa: BLE001 - any raise is correct
        pass
    else:
        fail("an unknown mode returned a value instead of raising")

    # budget is enforced, and not shared between instances
    budgeted = next((a for a in actions if a.get("costs_budget", True)), None)
    if isinstance(budget, int) and budgeted:
        params = sample_params(budgeted)
        instance = oracle_cls()
        enforced = False
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(budget + 1):
                try:
                    instance.query(budgeted["name"], **params)
                except RuntimeError:
                    enforced = True
                    break
                except Exception:  # noqa: BLE001
                    enforced = True
                    break
        if not enforced:
            fail(f"budget not enforced: {budget + 1} calls succeeded with BUDGET={budget}")

        fresh = oracle_cls()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                fresh.query(budgeted["name"], **params)
        except RuntimeError:
            fail("a fresh Oracle() inherited a spent budget — state is not per-instance")

    # the answer must not be printed in the prompt
    prompt = (directory / "problem.md").read_text()
    values = golden.get("answer")
    values = values if isinstance(values, list) else [values]
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if abs(value) < 10:
            continue  # too common in ordinary prose to be evidence
        if re.search(rf"(?<![\d.]){re.escape(str(value))}(?!\d)(?!\.\d)", prompt):
            fail(f"problem.md contains the answer value {value}")

    return errors


def main(argv: list[str]) -> int:
    if not PROBLEMS.is_dir():
        print(f"no problems/ directory at {PROBLEMS}", file=sys.stderr)
        return 1
    available = sorted(
        p.name for p in PROBLEMS.iterdir()
        if p.is_dir() and not p.name.startswith((".", "_"))
    )
    targets = argv[1:] or available
    unknown = [t for t in targets if t not in available]
    if unknown:
        print(f"unknown problem(s) {unknown}; available: {available}", file=sys.stderr)
        return 1
    if not targets:
        print("no problems found", file=sys.stderr)
        return 1

    failed = []
    for problem_id in targets:
        errors = check(problem_id, PROBLEMS / problem_id)
        if errors:
            failed.append(problem_id)
            print(f"FAIL  {problem_id}")
            for error in errors:
                print(f"        - {error}")
        else:
            print(f"ok    {problem_id}")

    print(f"\n{len(targets)} problem(s) checked, {len(failed)} failing.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
