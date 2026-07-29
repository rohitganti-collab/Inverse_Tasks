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


def _generic_query(action: str, params: Optional[dict] = None) -> str:
    session = state.require()
    try:
        observation = session.query(action, params or {})
    except core.InverseTaskError as exc:
        return f"Error: {exc}"
    return _dump(observation)


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


def register_generic_tools() -> None:
    mcp.add_tool(
        _generic_query,
        name="query",
        description=(
            "Probe the black box. `action` names the operation (call "
            "`describe_oracle` to see which actions exist and what parameters "
            "they take); `params` is a JSON object of that action's arguments, "
            'e.g. action="evaluate", params={"x": 0}. Budgeted actions spend '
            "one unit of your query budget per call."
        ),
    )


# --------------------------------------------------------------------------- #
# Startup
# --------------------------------------------------------------------------- #


def resolve_startup_problem(explicit: Optional[str]) -> Optional[str]:
    """Decide whether this container is bound to one problem at startup."""
    if explicit:
        return explicit
    env = os.environ.get("PROBLEM_ID") or os.environ.get("INVERSE_TASKS_PROBLEM_ID")
    if env:
        return env
    available = core.discover_problems()
    if len(available) == 1:
        return next(iter(available))
    return None


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Inverse Task MCP server for Taiga")
    parser.add_argument(
        "--problem-id",
        default=None,
        help=(
            "Bind this container to one problem at startup so each of its oracle "
            "actions becomes a first-class MCP tool. Defaults to $PROBLEM_ID, or "
            "to the only problem present if the image ships exactly one."
        ),
    )
    args = parser.parse_args(argv)

    available = core.discover_problems()
    log(f"problem roots: {[str(p) for p in core.problem_roots()]}")
    log(f"problems available: {sorted(available) or '<none>'}")

    problem_id = resolve_startup_problem(args.problem_id)
    bound = False
    if problem_id:
        try:
            session = core.load_session(problem_id)
            bound = register_bound_tools(session)
            if bound:
                # Bind so setup_problem can reject a metadata/startup mismatch.
                state.bound_problem_id = problem_id
                state.session = session
                log(
                    f"bound mode: {problem_id} -> tools "
                    f"{[a['name'] for a in session.problem.actions]}"
                )
        except core.InverseTaskError as exc:
            log(f"WARNING: could not bind to {problem_id!r} ({exc}); using generic mode")

    if not bound:
        register_generic_tools()
        log("generic mode: exposing query() + describe_oracle()")

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
