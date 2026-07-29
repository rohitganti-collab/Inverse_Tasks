#!/usr/bin/env python3
"""Exercise the inverse-task server through a real MCP stdio connection.

Unlike server.py --selftest, this launches the server as a child process and
uses MCP's ClientSession. It therefore verifies JSON-RPC framing, published
schemas, isError handling, and grading after an MCP-process restart.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_PATH = REPO_ROOT / "mcp_server" / "server.py"
sys.path.insert(0, str(REPO_ROOT / "mcp_server"))

import core  # noqa: E402


def result_text(result) -> str:
    """Join textual MCP content blocks for assertions and diagnostics."""
    return "\n".join(
        block.text for block in result.content if getattr(block, "type", None) == "text"
    )


@asynccontextmanager
async def connect(
    state_path: Path,
) -> AsyncIterator[ClientSession]:
    environment = dict(os.environ)
    environment.update(
        {
            "INVERSE_TASKS_PROBLEM_DIRS": str(REPO_ROOT / "problems"),
            "INVERSE_TASKS_RUNTIME": "build",
            "INVERSE_TASKS_STATE_PATH": str(state_path),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
        }
    )
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-u", str(SERVER_PATH)],
        cwd=REPO_ROOT,
        env=environment,
    )
    async with stdio_client(parameters) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            yield session


def probe_arguments(session: core.Session) -> tuple[str, dict]:
    """Choose a declared action and harmless arguments for the smoke probe."""
    action = next(
        (candidate for candidate in session.problem.actions if candidate["costs_budget"]),
        None,
    )
    if action is None:
        action = next(iter(session.problem.actions), None)
    if action is None:
        raise AssertionError("protocol smoke requires at least one declared ACTION")

    samples = {
        "integer": 0,
        "number": 0.0,
        "string": "",
        "boolean": False,
        "array": [],
        "object": {},
    }
    arguments = {
        parameter["name"]: parameter.get("default", samples[parameter["type"]])
        for parameter in action["params"]
        if parameter["required"] or "default" in parameter
    }
    return action["name"], arguments


async def smoke(problem_id: str) -> None:
    author_session = core.load_session(problem_id)
    action, parameters = probe_arguments(author_session)
    golden_answer = author_session.problem.golden()["answer"]

    with tempfile.TemporaryDirectory(prefix="inverse-mcp-smoke-") as temporary:
        state_path = Path(temporary) / "session.json"

        async with connect(state_path) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            required = {
                "setup_problem",
                "grade_problem",
                "query_oracle",
                "describe_oracle",
                "submit_answer",
            }
            missing = required - tools.keys()
            assert not missing, f"missing MCP tools: {sorted(missing)}"

            setup = await client.call_tool(
                "setup_problem",
                {"problem_id": problem_id, "extra_fields": {}},
            )
            assert not setup.isError, result_text(setup)
            assert "query_oracle" in result_text(setup)

            invalid = await client.call_tool(
                "query_oracle",
                {"mode": "__mcp_smoke_unknown_action__", "parameters": {}},
            )
            assert invalid.isError, "invalid tool input must return isError=true"

            observation = await client.call_tool(
                "query_oracle",
                {"mode": action, "parameters": parameters},
            )
            assert not observation.isError, result_text(observation)

            submitted = await client.call_tool(
                "submit_answer",
                {"answer": golden_answer},
            )
            assert not submitted.isError, result_text(submitted)
            assert state_path.is_file(), "attempt state was not persisted"
            assert state_path.stat().st_mode & 0o777 == 0o600

        # A second child process has no in-memory oracle or submission state.
        # grade_problem must reload the owner-only task and restore the snapshot.
        async with connect(state_path) as restarted_client:
            grade = await restarted_client.call_tool(
                "grade_problem",
                {"problem_id": problem_id, "transcript": "protocol smoke after restart"},
            )
            assert not grade.isError, result_text(grade)
            payload = json.loads(result_text(grade))
            assert payload["subscores"]["correct"] == 1.0, payload
            assert not payload.get("env_internal_failure"), payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "problem_id",
        nargs="?",
        default=None,
        help="Problem to exercise (default: first discovered problem)",
    )
    args = parser.parse_args()
    available = sorted(core.discover_problems())
    if not available:
        parser.error("no problems discovered")
    problem_id = args.problem_id or available[0]
    if problem_id not in available:
        parser.error(f"unknown problem {problem_id!r}; available: {available}")

    asyncio.run(smoke(problem_id))
    print(f"MCP protocol smoke passed: {problem_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
