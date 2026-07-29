"""MCP server for Inverse Task problems on Taiga.

Thin wrapper over `core.py`, which holds all the oracle-agnostic logic. This
module's only job is to decide *what tools the model sees* and to marshal
values across the MCP boundary.

Two modes, chosen automatically:

**Bound mode** (recommended) — the problem is known at startup, via
`--problem-id`, the `PROBLEM_ID` env var, or because the image ships exactly one
problem. Each action the oracle declares is registered as a real, first-class
MCP tool with its own name and typed parameters. An expert whose `problem.md`
says "call `evaluate(x)`" gets a tool literally named `evaluate` taking `x`.

**Generic mode** — the problem isn't known until Taiga calls `setup_problem`
(one image, many problems, chosen per problem-run). MCP publishes its tool list
during the initialize handshake, before `setup_problem` runs, so per-problem
tool names can't exist yet. The model instead gets `query(action, params)` plus
`describe_oracle()` to discover the surface at runtime.

Either way the model never sees `setup_problem` / `grade_problem` (Taiga hides
the scaffold hooks) and never reaches the oracle except through its declared
actions — the hidden constants, the intended solver, and the trap write-up all
stay out of reach.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core  # noqa: E402  (local module, needs the sys.path tweak above)


def log(message: str) -> None:
    """Diagnostics go to stderr — stdout is the MCP transport."""
    print(f"[inverse-tasks] {message}", file=sys.stderr, flush=True)


class Grade(BaseModel):
    """Matches Taiga's expected grade_problem response."""

    subscores: dict[str, float]
    weights: dict[str, float]
    metadata: Optional[dict[str, Any]] = None
    env_internal_failure: Optional[bool] = None
    env_internal_failure_logs: Optional[list[str]] = None
    penalties: Optional[dict[str, float]] = None
    allow_unbounded: bool = False


class _State:
    """The single active attempt. One container serves one problem-run."""

    def __init__(self) -> None:
        self.session: Optional[core.Session] = None
        self.bound_problem_id: Optional[str] = None

    def require(self) -> core.Session:
        if self.session is None:
            raise RuntimeError(
                "No problem is active yet — the harness must call setup_problem first."
            )
        return self.session


state = _State()
mcp = FastMCP("inverse-tasks")


def _dump(value: Any) -> str:
    """Render an observation for the model: scalars bare, structures as JSON."""
    value = core._jsonable(value)
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return json.dumps(value)
    return json.dumps(value, indent=2, sort_keys=True)


# --------------------------------------------------------------------------- #
# Taiga scaffold hooks (hidden from the model)
# --------------------------------------------------------------------------- #


@mcp.tool()
def setup_problem(
    problem_id: str,
    use_hinted_problem: bool = False,
    extra_fields: Optional[dict] = None,
) -> str:
    """Start a fresh attempt at `problem_id` and return the task prompt."""
    if state.bound_problem_id and problem_id != state.bound_problem_id:
        # A mismatch means the startup_command and the problems-metadata id
        # disagree; failing loudly beats silently grading the wrong task.
        raise ValueError(
            f"This container was started bound to problem {state.bound_problem_id!r} "
            f"but setup_problem was called with {problem_id!r}. Fix the problem's "
            "startup_command (--problem-id) or its metadata id so they agree."
        )

    session = core.load_session(problem_id)
    state.session = session
    log(
        f"setup_problem: {problem_id} "
        f"(actions={[a['name'] for a in session.problem.actions]}, "
        f"budget={session.problem.budget_total})"
    )

    extras = dict(extra_fields or {})

    # The prompt may come from Taiga's Task Prompt field (passed through
    # extra_fields) or from the problem folder's problem.md. The form wins when
    # both exist, so an expert can edit the prompt in the UI without touching
    # the mounted files.
    prompt = ""
    for key in ("task_prompt", "prompt", "problem_statement"):
        if isinstance(extras.get(key), str) and extras[key].strip():
            prompt = extras[key]
            break
    if not prompt.strip():
        prompt = session.problem.prompt
    if not prompt.strip():
        raise ValueError(
            f"Problem {problem_id!r} has no task prompt: add a problem.md to the "
            "problem folder, or fill in the Task Prompt field so it arrives in "
            "extra_fields."
        )

    # Append the calling contract, generated from the oracle. The expert writes
    # the science; this keeps the mechanics the model is told identical to the
    # mechanics actually published, whichever mode the server is in.
    if extras.get("append_tool_guide", True):
        mode = "named" if state.bound_problem_id else "query"
        prompt = f"{prompt.rstrip()}\n\n{core.render_tool_guide(session, mode)}\n"

    for suffix_key in ("prompt_suffix", "task_prompt_suffix"):
        if extras.get(suffix_key):
            prompt = f"{prompt}\n\n{extras[suffix_key]}"
    return prompt


@mcp.tool()
def grade_problem(
    problem_id: str,
    transcript: str = "",
    extra_fields: Optional[dict] = None,
) -> Grade:
    """Score the submitted answer against this problem's golden answer."""
    session = state.session
    if session is None:
        return Grade(
            subscores={"correct": 0.0},
            weights={"correct": 1.0},
            env_internal_failure=True,
            env_internal_failure_logs=["grade_problem called before setup_problem"],
        )
    if session.problem.problem_id != problem_id:
        return Grade(
            subscores={"correct": 0.0},
            weights={"correct": 1.0},
            env_internal_failure=True,
            env_internal_failure_logs=[
                f"grade_problem called for {problem_id!r} but the active problem is "
                f"{session.problem.problem_id!r}"
            ],
        )

    try:
        result = session.grade(transcript=transcript, extra_fields=extra_fields)
    except core.InverseTaskError as exc:
        return Grade(
            subscores={"correct": 0.0},
            weights={"correct": 1.0},
            env_internal_failure=True,
            env_internal_failure_logs=[f"grading failed: {exc}"],
        )

    log(f"grade_problem: {problem_id} -> {result['subscores']}")
    return Grade(**result)


@mcp.tool()
def list_problems() -> str:
    """List the problem ids this container can serve (harness-facing)."""
    return _dump(sorted(core.discover_problems()))


# --------------------------------------------------------------------------- #
# Model-facing tools, present in every mode
# --------------------------------------------------------------------------- #


@mcp.tool()
def describe_oracle() -> str:
    """Describe what you can ask the black box, and how much query budget is left.

    Costs nothing against your query budget.
    """
    return _dump(state.require().describe())


@mcp.tool()
def submit_answer(answer: str) -> str:
    """Submit your final answer, as JSON (e.g. `[23, 58]` or `{"a": 23, "b": 58}`).

    Call `describe_oracle` to see the expected answer shape. You may resubmit;
    only your most recent submission is graded.
    """
    session = state.require()
    try:
        result = session.submit(answer)
    except core.InverseTaskError as exc:
        return f"Answer rejected: {exc}"

    message = f"Recorded answer: {json.dumps(result['accepted'])}"
    if result["warnings"]:
        message += (
            "\n\nWarning — this does not match the expected answer shape: "
            + "; ".join(result["warnings"])
            + f"\nExpected shape: {json.dumps(result['answer_shape'], sort_keys=True)}"
            + "\nResubmit if that was not what you intended."
        )
    return message


@mcp.tool()
def query(action: str, params: Optional[dict] = None) -> str:
    """Probe the black box.

    `action` names the operation and `params` is a JSON object of that action's
    arguments, e.g. action="evaluate", params={"x": 0}. Call `describe_oracle`
    to see which actions exist, what parameters they take, and which spend query
    budget.

    This is the primary way to query the black box. It is registered with the
    same decorator as the scaffold hooks rather than added dynamically, so the
    critical path does not depend on any particular FastMCP `add_tool` signature.
    """
    session = state.require()
    try:
        observation = session.query(action, params or {})
    except core.InverseTaskError as exc:
        return f"Error: {exc}"
    return _dump(observation)


# Alias kept for the dynamically-synthesised named tools to dispatch through.
_generic_query = query


# --------------------------------------------------------------------------- #
# Bound mode: turn each declared action into a real named tool
# --------------------------------------------------------------------------- #


def register_bound_tools(session: core.Session) -> bool:
    """Register one MCP tool per declared action. Returns True on success."""
    if not session.problem.actions_declared or not session.problem.actions:
        return False
    try:
        for action in session.problem.actions:
            mcp.add_tool(core.synthesise_action_function(action, _generic_query))
    except Exception as exc:  # pragma: no cover - depends on installed FastMCP
        # Never let tool synthesis stop the container from booting: fall back to
        # the generic surface, which works for any oracle.
        log(f"WARNING: could not register named action tools ({exc!r}); using generic query()")
        return False
    return True


# --------------------------------------------------------------------------- #
# Startup
# --------------------------------------------------------------------------- #


def resolve_startup_problem(explicit: Optional[str]) -> Optional[str]:
    """The problem to bind to at startup, or None to stay in query mode.

    Deliberately does *not* auto-select when only one problem happens to be
    present: the published surface must depend on flags, not on how many problem
    folders a container happens to have mounted, or a task's tools would change
    the moment a second problem appeared beside it.
    """
    if explicit:
        return explicit
    return os.environ.get("PROBLEM_ID") or os.environ.get("INVERSE_TASKS_PROBLEM_ID")


def published_tool_names() -> list[str]:
    """Tool names the harness would receive, via the real FastMCP object."""
    import asyncio

    tools = asyncio.run(mcp.list_tools())
    return sorted(getattr(t, "name", str(t)) for t in tools)


def selftest(problem_id: Optional[str] = None) -> int:
    """Exercise the whole path against the real MCP objects. Returns an exit code.

    Run during `docker build`, which is the only place the genuine `mcp` package
    is guaranteed installed — the unit tests stub it. This turns "the FastMCP
    integration might be wrong" into a build failure rather than a mystery at
    job time.
    """
    failures: list[str] = []

    def check(condition: bool, description: str) -> None:
        log(f"  {'ok  ' if condition else 'FAIL'}  {description}")
        if not condition:
            failures.append(description)

    available = core.discover_problems()
    log(f"selftest: problems available: {sorted(available) or '<none>'}")
    if not available:
        log("selftest: FAIL no problems found")
        return 1
    problem_id = problem_id or sorted(available)[0]
    log(f"selftest: using {problem_id!r}")

    # 1. The harness can enumerate our tools, and the required surface is present.
    try:
        names = published_tool_names()
        log(f"selftest: published tools: {names}")
        for required in ("setup_problem", "grade_problem", "query", "submit_answer", "describe_oracle"):
            check(required in names, f"tool {required!r} is published")
    except Exception as exc:  # noqa: BLE001 - any failure here is a real defect
        check(False, f"mcp.list_tools() works ({type(exc).__name__}: {exc})")

    # 2. setup_problem returns a usable prompt including the generated guide.
    try:
        prompt = setup_problem(problem_id)
        check(bool(prompt.strip()), "setup_problem returns a non-empty prompt")
        check("Using your tools" in prompt, "prompt carries the generated tool guide")
    except Exception as exc:  # noqa: BLE001
        check(False, f"setup_problem works ({type(exc).__name__}: {exc})")
        return 1

    session = state.require()
    golden = session.problem.golden()

    # 3. describe_oracle is machine-readable and hides the answer.
    try:
        described = json.loads(describe_oracle())
        check("actions" in described, "describe_oracle reports actions")
        check(
            str(golden["answer"]) not in json.dumps(described),
            "describe_oracle does not leak the answer",
        )
    except Exception as exc:  # noqa: BLE001
        check(False, f"describe_oracle works ({type(exc).__name__}: {exc})")

    # 4. A real probe through the query tool reaches the oracle.
    budgeted = next((a for a in session.problem.actions if a["costs_budget"]), None)
    if budgeted:
        sample = {"integer": 0, "number": 0.0, "string": "", "boolean": False, "array": [], "object": {}}
        params = {
            p["name"]: p.get("default", sample[p["type"]])
            for p in budgeted["params"]
            if p["required"] or "default" in p
        }
        before = session.calls_used
        observation = query(budgeted["name"], params)
        check(not observation.startswith("Error:"), f"query({budgeted['name']!r}) returns an observation")
        check(session.calls_used == before + 1, "a budgeted query spends exactly one call")

    # 5. Grading: the golden answer scores 1.0, a wrong one scores 0.0.
    try:
        submit_answer(json.dumps(golden["answer"]))
        grade = grade_problem(problem_id, transcript="selftest")
        check(grade.subscores.get("correct") == 1.0, "golden answer grades 1.0")
        check(not grade.env_internal_failure, "grading reports no internal failure")
        json.dumps(grade.metadata)
        check(True, "grade metadata is JSON-serialisable")
        weighted = sum(grade.subscores[k] * w for k, w in grade.weights.items() if k in grade.subscores)
        check(0.0 <= weighted <= 1.0, f"weighted grade {weighted} is within [0, 1]")
    except Exception as exc:  # noqa: BLE001
        check(False, f"grading the golden answer works ({type(exc).__name__}: {exc})")

    try:
        setup_problem(problem_id)  # fresh attempt
        submit_answer('"definitely-not-the-answer"')
        check(
            grade_problem(problem_id).subscores.get("correct") == 0.0,
            "a wrong answer grades 0.0",
        )
    except Exception as exc:  # noqa: BLE001
        check(False, f"grading a wrong answer works ({type(exc).__name__}: {exc})")

    if failures:
        log(f"selftest: FAILED ({len(failures)} check(s)): {failures}")
        return 1
    log("selftest: all checks passed")
    return 0


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Inverse Task MCP server for Taiga")
    parser.add_argument(
        "--problem-id",
        default=None,
        help=(
            "With --named-tools, the problem whose actions become named tools. "
            "Also used by --selftest to pick a problem. Defaults to $PROBLEM_ID."
        ),
    )
    parser.add_argument(
        "--named-tools",
        action="store_true",
        help=(
            "Opt in to publishing one named MCP tool per declared oracle action "
            "(evaluate, help, ...) instead of only the generic query tool. "
            "Requires the problem to be known at startup via --problem-id, since "
            "MCP sends its tool list before Taiga calls setup_problem."
        ),
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="Run an end-to-end check against the real MCP objects and exit.",
    )
    args = parser.parse_args(argv)

    available = core.discover_problems()
    log(f"problem roots: {[str(p) for p in core.problem_roots()]}")
    log(f"problems available: {sorted(available) or '<none>'}")

    problem_id = resolve_startup_problem(args.problem_id)

    if args.named_tools:
        if not problem_id:
            log("WARNING: --named-tools needs --problem-id (or $PROBLEM_ID); staying in query mode")
        else:
            try:
                session = core.load_session(problem_id)
                if register_bound_tools(session):
                    # Bind so setup_problem can reject a metadata/startup mismatch.
                    state.bound_problem_id = problem_id
                    state.session = session
                    log(
                        f"named-tools mode: {problem_id} -> "
                        f"{[a['name'] for a in session.problem.actions]}"
                    )
                else:
                    log(f"WARNING: {problem_id!r} declares no ACTIONS; staying in query mode")
            except core.InverseTaskError as exc:
                log(f"WARNING: could not bind to {problem_id!r} ({exc}); staying in query mode")

    if args.selftest:
        sys.exit(selftest(problem_id))

    log("model-facing tools: query, submit_answer, describe_oracle")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
