"""Hidden oracle for modular-black-box.

The model never sees this file. The gym imports `Oracle`, constructs one
instance per attempt, and forwards every probe through `query`.

Contract
--------
    Oracle().query(mode: str, **params) -> observation

Modes:
  evaluate(x: int) -> int   budgeted; the black-box observation
  help()           -> dict  free; available modes and remaining budget

Rules this oracle guarantees:
  * A fresh `Oracle()` is a fresh attempt — all mutable state lives on the
    instance, never at module or class level, so budget cannot leak between
    rollouts.
  * The budget is enforced here. Exceeding it raises RuntimeError rather than
    returning a value, so it holds even if the caller does not track it.
  * An unknown mode raises ValueError. Only the modes listed in ACTIONS are
    reachable, so the probe surface can never drift from what problem.md
    promises.
  * No output is ever printed; the return value is the whole interface.

Dependencies: standard library only.
"""
from __future__ import annotations


class Oracle:
    """f(x) = (a * x + b) mod M, with hidden a and b."""

    # --- public: stated in problem.md, safe for the model to know ---------- #
    M = 97
    BUDGET = 6

    # --- hidden ground truth ---------------------------------------------- #
    _A = 23
    _B = 58

    # Optional metadata. The gym may use it to enumerate the probe surface and
    # to know which modes cost budget; `query` works without reading it.
    ACTIONS = [
        {
            "name": "evaluate",
            "description": "Return the box's output for your chosen integer x.",
            "params": {
                "x": {
                    "type": "integer",
                    "description": "The input to the box.",
                    "required": True,
                }
            },
            "costs_budget": True,
        },
        {
            "name": "help",
            "description": (
                "List available modes and remaining budget. Never reveals a or b."
            ),
            "params": {},
            "costs_budget": False,
        },
    ]

    def __init__(self) -> None:
        self._used = 0

    # ---------------------------------------------------------------- probe #
    def query(self, mode: str, **params):
        """Stable probe entry point. Every observation flows through here."""
        if mode == "help":
            return {
                "description": "Integer black box with a known modulus.",
                "modes": {
                    "evaluate": "{x: integer} -> integer",
                    "help": "{} -> {description, modes, budget_remaining, modulus}",
                },
                "budget_remaining": self.BUDGET - self._used,
                "budget_total": self.BUDGET,
                "modulus": self.M,
            }

        if mode == "evaluate":
            if "x" not in params:
                raise ValueError("evaluate requires parameter 'x' (integer)")
            try:
                x = int(params["x"])
            except (TypeError, ValueError):
                raise ValueError(
                    f"evaluate parameter 'x' must be an integer, got {params['x']!r}"
                ) from None
            if self._used >= self.BUDGET:
                raise RuntimeError(f"Query budget exceeded ({self.BUDGET} calls).")
            self._used += 1
            return (self._A * x + self._B) % self.M

        raise ValueError(
            f"Unknown mode {mode!r}. Available modes: "
            f"{[a['name'] for a in self.ACTIONS]}"
        )

    # ------------------------------------------------------- optional sugar #
    # Convenience aliases if the gym prefers method dispatch over query().
    # Both routes are equivalent and share the same budget.
    def evaluate(self, x: int) -> int:
        return self.query("evaluate", x=x)

    def help(self) -> dict:
        return self.query("help")
