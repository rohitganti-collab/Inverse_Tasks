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
tool names can't exist yet. The model instead gets
`query_oracle(mode, parameters)` plus `describe_oracle()` to discover the
surface at runtime. `query(action, params)` remains as a compatibility alias.

Either way the model never sees `setup_problem` / `grade_problem` (Taiga hides
the scaffold hooks) and never reaches the oracle except through its declared
actions — the hidden constants, the intended solver, and the trap write-up all
stay out of reach.
"""
import argparse
import json
import os
import stat
import sys
from pathlib import Path
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
        # Container-lifetime count, so switching problem ids cannot reset it.
        self.setup_calls = 0

    def require(self) -> core.Session:
        if self.session is None:
            raise RuntimeError(
                "No problem is active yet — the harness must call setup_problem first."
            )
        return self.session


state = _State()
mcp = FastMCP("inverse-tasks")

_STATE_VERSION = 1


def _dump(value: Any) -> str:
    """Render an observation for the model: scalars bare, structures as JSON."""
    value = core._jsonable(value)
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return json.dumps(value)
    return json.dumps(value, indent=2, sort_keys=True)


def _state_path() -> Path:
    """Root-owned snapshot used if Taiga restarts MCP before grading."""
    configured = os.environ.get("INVERSE_TASKS_STATE_PATH")
    return Path(configured or "/tmp/inverse-tasks/session.json")


def _own_private_dir(path: Path) -> bool:
    """Ensure `path` is a directory this process owns and only it can use.

    `mkdir(exist_ok=True)` accepts a directory somebody else created, and
    chmod-ing afterwards fixes the mode but not the owner — so a pre-created,
    solver-owned directory at a predictable path would still be accepted, and
    the attempt state (including `calls_used`) written inside it. Verify
    ownership explicitly and refuse to write through anything we do not own.
    """
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = os.lstat(path)
    except OSError as exc:
        log(f"WARNING: cannot use state directory {path}: {exc}")
        return False
    if not stat.S_ISDIR(info.st_mode):
        log(f"WARNING: state path {path} is not a directory; refusing to use it")
        return False
    if info.st_uid != os.geteuid():
        log(
            f"WARNING: state directory {path} is owned by uid {info.st_uid}, not "
            f"{os.geteuid()}; refusing to use it"
        )
        return False
    if info.st_mode & 0o077:
        try:
            os.chmod(path, 0o700)
        except OSError as exc:
            log(f"WARNING: cannot restrict state directory {path}: {exc}")
            return False
    return True


def _save_session(session: core.Session) -> bool:
    """Persist the grading-relevant attempt state without the golden answer."""
    payload = {
        "version": _STATE_VERSION,
        "problem_id": session.problem.problem_id,
        "problem_dir": str(session.problem.directory.resolve()),
        "calls_used": session.calls_used,
        "call_log": core._jsonable(session.call_log),
        "submission_raw": session.submission_raw,
        "submission": core._jsonable(session.submission),
        "submitted": session.submitted,
        "setup_calls": session.setup_calls,
    }
    path = _state_path()
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        if not _own_private_dir(path.parent):
            return False
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        return True
    except Exception as exc:  # noqa: BLE001 - persistence must not break a live attempt
        log(f"WARNING: could not persist attempt state to {path}: {exc}")
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _restore_session(problem_id: str) -> Optional[core.Session]:
    """Restore submission state after an MCP-process restart.

    Taiga may restart the MCP process between setup and grading while keeping
    the container filesystem. The problem directory is checked as well as the
    id so a stale local-development snapshot can never attach to another task.
    """
    path = _state_path()
    if not path.is_file():
        return None
    # Only trust a snapshot we wrote ourselves. `calls_used` is restored from
    # this file, so a solver-writable copy would be a budget reset.
    try:
        info = os.lstat(path)
    except OSError as exc:
        log(f"WARNING: cannot stat attempt state {path}: {exc}")
        return None
    if not stat.S_ISREG(info.st_mode):
        log(f"WARNING: attempt state {path} is not a regular file; ignoring it")
        return None
    if info.st_uid != os.geteuid() or info.st_mode & 0o077:
        log(
            f"WARNING: attempt state {path} is uid {info.st_uid} mode "
            f"{info.st_mode & 0o777:04o} and not exclusively ours; ignoring it"
        )
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != _STATE_VERSION:
            return None
        if payload.get("problem_id") != problem_id:
            return None

        current_directory = core.resolve_problem_dir(problem_id).resolve()
        saved_directory = Path(payload.get("problem_dir", "")).resolve()
        if saved_directory != current_directory:
            return None

        session = core.load_session(problem_id)
        calls_used = int(payload.get("calls_used", 0))
        if calls_used < 0:
            raise ValueError("calls_used cannot be negative")
        call_log = payload.get("call_log", [])
        if not isinstance(call_log, list):
            raise ValueError("call_log must be a list")

        session.calls_used = calls_used
        session.call_log = call_log
        session.submission_raw = payload.get("submission_raw")
        session.submission = payload.get("submission")
        session.submitted = bool(payload.get("submitted", False))
        session.setup_calls = int(payload.get("setup_calls", 1) or 1)
        state.session = session
        log(f"restored attempt state for {problem_id!r} from {path}")
        return session
    except Exception as exc:  # noqa: BLE001 - malformed state becomes an internal failure
        log(f"WARNING: could not restore attempt state from {path}: {exc}")
        return None


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

    # Re-entry guard. The scaffold hooks are supposed to be harness-only, but
    # that is Taiga-side configuration we do not control, and a shipped image
    # has already been observed publishing `grade_problem` to the model. If
    # `setup_problem` were reachable too, calling it again would hand back a
    # brand-new Session — resetting `calls_used` to zero and making the query
    # budget, the whole difficulty mechanism, unlimited. Refuse once an attempt
    # is genuinely under way. Outside the image this stays permissive so the
    # selftest and validator can start successive attempts in one process.
    # The guard is on ANY live attempt, not on a matching problem id. Comparing
    # ids left a trivial bypass: setup(A) -> probe -> setup(B) -> setup(A) reset
    # A's budget, because neither hop was "the same problem" as the one before
    # it. One container serves one problem-run, so a second setup of any kind is
    # already anomalous.
    previous = state.session
    if (
        previous is not None
        and core.is_taiga_runtime()
        and (previous.calls_used > 0 or previous.submitted or previous.graded)
    ):
        raise ValueError(
            f"An attempt at {previous.problem.problem_id!r} is already in "
            f"progress ({previous.calls_used} budgeted call(s) used, "
            f"submitted={previous.submitted}). setup_problem starts a fresh "
            "attempt and is called once by the harness; refusing to reset a "
            "live attempt's query budget."
        )

    session = core.load_session(problem_id)
    # Counted on the container, not the session, so pivoting between problems
    # cannot reset the tamper trail either.
    state.setup_calls += 1
    session.setup_calls = state.setup_calls
    state.session = session
    protected = core.harden_problem_permissions(session.problem.directory)
    log(
        f"setup_problem: {problem_id} "
        f"(actions={[a['name'] for a in session.problem.actions]}, "
        f"budget={session.problem.budget_total}"
        f"{f', protected_files={len(protected)}' if protected else ''})"
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
    _save_session(session)
    return prompt


@mcp.tool()
def grade_problem(
    problem_id: str,
    transcript: str = "",
    extra_fields: Optional[dict] = None,
) -> Grade:
    """Score the submitted answer against this problem's golden answer."""
    session = state.session or _restore_session(problem_id)
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
def submit_answer(answer: dict | list | str | float | bool) -> str:
    """Submit your final answer as a JSON value.

    Call `describe_oracle` to see the expected shape. Arrays, objects, numbers,
    strings, and booleans are accepted directly; a JSON-encoded string is also
    accepted for compatibility. You may resubmit; only your most recent
    submission is graded.
    """
    session = state.require()
    result = session.submit(answer)
    _save_session(session)

    message = f"Recorded answer: {json.dumps(result['accepted'])}"
    if result["warnings"]:
        message += (
            "\n\nWarning — this does not match the expected answer shape: "
            + "; ".join(result["warnings"])
            + f"\nExpected shape: {json.dumps(result['answer_shape'], sort_keys=True)}"
            + "\nResubmit if that was not what you intended."
        )
    return message


def _probe(action: str, params: Optional[dict] = None) -> str:
    """Shared implementation for both generic probe spellings."""
    session = state.require()
    try:
        observation = session.query(action, params or {})
    finally:
        # A call that raises inside the oracle still spends budget; persist that
        # counter before FastMCP turns the exception into an isError response.
        _save_session(session)
    return _dump(observation)


@mcp.tool()
def query_oracle(mode: str, parameters: Optional[dict] = None) -> str:
    """Probe the hidden system.

    `mode` names the operation and `parameters` is a JSON object containing its
    arguments. Call `describe_oracle` for the available modes, parameter types,
    and remaining query budget.
    """
    return _probe(mode, parameters)


@mcp.tool()
def query(action: str, params: Optional[dict] = None) -> str:
    """Compatibility alias for `query_oracle(mode, parameters)`.

    New inverse tasks should use `query_oracle`; this spelling remains available
    so older task prompts and metadata continue to run unchanged.
    """
    return _probe(action, params)


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
        for required in (
            "setup_problem",
            "grade_problem",
            "query_oracle",
            "query",
            "submit_answer",
            "describe_oracle",
        ):
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
        observation = query_oracle(budgeted["name"], params)
        check(
            bool(observation),
            f"query_oracle({budgeted['name']!r}) returns an observation",
        )
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

    log(
        "model-facing tools: query_oracle, submit_answer, describe_oracle "
        "(query is a compatibility alias)"
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
