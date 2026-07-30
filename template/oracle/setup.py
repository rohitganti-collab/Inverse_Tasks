"""TEMPLATE oracle. Copy `template/` to `problems/<problem-id>/` and edit.

Keep the four guarantees the gym relies on:
  1. All mutable state on the instance (`__init__`), never module/class level —
     otherwise budget leaks between rollouts.
  2. Enforce BUDGET here; raise rather than return when it is exhausted.
  3. Raise ValueError on an unknown mode, so only intended probes are reachable.
  4. Never print; the return value is the whole interface.

Dependencies: standard library only. If this problem needs anything else, add a
`requirements.txt` beside this file and list it (see README).
"""
from __future__ import annotations


class Oracle:
    """One-line description of the hidden system."""

    # Public: stated in problem.md, safe for the model to know.
    BUDGET = 6

    # Hidden ground truth — underscore-prefixed by convention.
    _SECRET = 42

    ACTIONS = [
        {
            "name": "evaluate",
            "description": "Return the system's output for your chosen input.",
            "params": {
                "x": {"type": "integer", "description": "The input.", "required": True}
            },
            "costs_budget": True,
        },
        {
            "name": "help",
            "description": "List available modes and remaining budget.",
            "params": {},
            "costs_budget": False,
        },
    ]

    def __init__(self) -> None:
        self._used = 0

    def query(self, mode: str, **params):
        if mode == "help":
            return {
                "description": "Describe the system without revealing the answer.",
                "modes": {"evaluate": "{x: integer} -> integer", "help": "{} -> dict"},
                "budget_remaining": self.BUDGET - self._used,
                "budget_total": self.BUDGET,
            }

        if mode == "evaluate":
            if "x" not in params:
                raise ValueError("evaluate requires parameter 'x' (integer)")
            if self._used >= self.BUDGET:
                raise RuntimeError(f"Query budget exceeded ({self.BUDGET} calls).")
            self._used += 1
            return (int(params["x"]) + self._SECRET) % 100

        raise ValueError(
            f"Unknown mode {mode!r}. Available modes: "
            f"{[a['name'] for a in self.ACTIONS]}"
        )
