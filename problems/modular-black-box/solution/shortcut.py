"""solution/shortcut.py — the deliberately-naive solver.

Authoring/calibration only — does not ship in the Docker image.
This file MUST FAIL against the oracle. If it passes, the task is too easy.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _as_query_fn(query_oracle):
    if callable(query_oracle) and not hasattr(query_oracle, "query"):
        return query_oracle

    def query_fn(mode, parameters=None):
        parameters = parameters or {}
        return query_oracle.query(mode, **parameters)

    return query_fn


def _observation(result):
    if isinstance(result, dict) and "observation" in result:
        return result["observation"]
    if isinstance(result, dict) and "error" in result:
        raise RuntimeError(result["error"])
    return result


def naive_solve(query_oracle):
    """Wrong path: fit a plain line through far-apart points, ignore the modulus."""
    q = _as_query_fn(query_oracle)

    y10 = _observation(q("evaluate", {"x": 10}))
    y30 = _observation(q("evaluate", {"x": 30}))
    a = round((y30 - y10) / (30 - 10))  # wrap between x=10 and x=30 is invisible
    b = y10 - a * 10  # no modulus applied
    return [a, b]


# Inverse_Tasks validate_problem.py looks for `solve`.
def solve(query_oracle):
    return naive_solve(query_oracle)


def main():
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from oracle.setup import query_oracle  # type: ignore[import-not-found]

    answer = naive_solve(query_oracle)
    print(f"SUBMIT_ANSWER: {answer}")
    print(answer)


if __name__ == "__main__":
    main()
