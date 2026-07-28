"""Generic MCP server for Inverse Task problems on Taiga.

One Docker image serves every problem under `problems/<problem_id>/`. Each
problem folder supplies its own hidden `oracle/setup.py` (an `Oracle` class)
and `golden/expected.json` (the graded answer); this server never bakes
problem-specific logic in — it only wires the generic Taiga hooks
(`setup_problem`, `grade_problem`) to whichever problem_id it's asked for.

The solver-facing tools (`evaluate`, `help`, `submit_answer`) only ever touch
the oracle through its `query()` method — they never import or expose
anything else from the problem folder, so the hidden constants and the
intended/shortcut solvers under `solution/` stay out of the model's reach.
"""
import importlib.util
import json
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

PROBLEMS_ROOT = Path(__file__).resolve().parent.parent / "problems"

mcp = FastMCP("inverse-tasks")

# Single active problem per container lifetime (one container == one ProblemRun).
_state: dict[str, Any] = {"problem_id": None, "oracle": None, "submission": None}


class Grade(BaseModel):
    subscores: dict[str, float]
    weights: dict[str, float]
    metadata: Optional[dict[str, Any]] = None
    env_internal_failure: Optional[bool] = None
    env_internal_failure_logs: Optional[list[str]] = None


def _problem_dir(problem_id: str) -> Path:
    problem_dir = PROBLEMS_ROOT / problem_id
    if not (problem_dir / "problem.md").exists():
        raise ValueError(f"Unknown problem_id: {problem_id!r}")
    return problem_dir


def _load_oracle(problem_id: str):
    setup_path = _problem_dir(problem_id) / "oracle" / "setup.py"
    spec = importlib.util.spec_from_file_location(f"oracle_{problem_id}", setup_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Oracle()


def _active_oracle():
    if _state["oracle"] is None:
        raise RuntimeError("No problem has been set up yet — call setup_problem first.")
    return _state["oracle"]


@mcp.tool()
def setup_problem(problem_id: str, use_hinted_problem: bool = False, extra_fields: Optional[dict] = None) -> str:
    """Initialize the oracle for `problem_id` and return the task prompt shown to the model."""
    problem_dir = _problem_dir(problem_id)
    _state["problem_id"] = problem_id
    _state["oracle"] = _load_oracle(problem_id)
    _state["submission"] = None
    return (problem_dir / "problem.md").read_text()


@mcp.tool()
def evaluate(x: int) -> int:
    """Query the black box at integer x. Budget-limited — see the task prompt for how many calls you get."""
    return _active_oracle().query("evaluate", x=x)


@mcp.tool()
def help(question: str = "") -> str:
    """Ask the black box for a general hint. Never reveals the hidden constants."""
    return _active_oracle().query("help")


@mcp.tool()
def submit_answer(a: int, b: int) -> str:
    """Submit your final answer for the pair (a, b). Only your most recent submission is graded."""
    _state["submission"] = [a, b]
    return f"Recorded answer a={a}, b={b}."


@mcp.tool()
def grade_problem(problem_id: str, transcript: str, extra_fields: Optional[dict] = None) -> Grade:
    """Score the submitted answer for `problem_id` against its golden answer."""
    golden_path = _problem_dir(problem_id) / "golden" / "expected.json"
    golden = json.loads(golden_path.read_text())
    expected = golden["answer"]
    tolerance = golden.get("tolerance", 0)

    if _state["problem_id"] != problem_id:
        return Grade(
            subscores={"correct": 0.0},
            weights={"correct": 1.0},
            env_internal_failure=True,
            env_internal_failure_logs=[
                f"grade_problem called for {problem_id!r} but active problem was {_state['problem_id']!r}"
            ],
        )

    submitted = _state["submission"]
    if submitted is None:
        return Grade(
            subscores={"correct": 0.0},
            weights={"correct": 1.0},
            metadata={"reason": "no answer submitted", "expected": expected},
        )

    correct = len(submitted) == len(expected) and all(
        abs(s - e) <= tolerance for s, e in zip(submitted, expected)
    )
    return Grade(
        subscores={"correct": 1.0 if correct else 0.0},
        weights={"correct": 1.0},
        metadata={"submitted": submitted, "expected": expected, "tolerance": tolerance},
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
