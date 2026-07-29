"""solution/main.py — reference solve.

Uses `query_oracle(mode, parameters)`. Also accepts an Inverse_Tasks Oracle /
proxy (has `.query`) so `tools/validate_problem.py` can run it unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _as_query_fn(query_oracle):
    """Normalise a free function vs an Oracle/proxy into one calling shape."""
    if callable(query_oracle) and not hasattr(query_oracle, "query"):
        return query_oracle

    def query_fn(mode, parameters=None):
        parameters = parameters or {}
        return query_oracle.query(mode, **parameters)

    return query_fn


def _observation(result):
    """Unwrap `{"observation": ...}` or accept a bare value."""
    if isinstance(result, dict) and "observation" in result:
        return result["observation"]
    if isinstance(result, dict) and "error" in result:
        raise RuntimeError(result["error"])
    return result


def solve(query_oracle):
    """Reference solve. Receives the oracle function (or Inverse_Tasks proxy)."""
    q = _as_query_fn(query_oracle)

    # 1. Discover modes / modulus (free).
    help_info = q("help", {})
    modulus = 97
    if isinstance(help_info, dict) and "modulus" in help_info:
        modulus = int(help_info["modulus"])
    elif hasattr(query_oracle, "M"):
        modulus = int(query_oracle.M)

    # 2. Adjacent probes — no room for a hidden wrap between them.
    b = _observation(q("evaluate", {"x": 0}))
    y1 = _observation(q("evaluate", {"x": 1}))
    a = (y1 - b) % modulus

    # 3. Validate before committing.
    y2 = _observation(q("evaluate", {"x": 2}))
    assert y2 == (a * 2 + b) % modulus

    return [a, b]


def main():
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from oracle.setup import query_oracle  # type: ignore[import-not-found]

    answer = solve(query_oracle)
    print(f"SUBMIT_ANSWER: {answer}")
    print(answer)


if __name__ == "__main__":
    main()
