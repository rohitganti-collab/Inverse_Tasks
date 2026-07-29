"""Hidden oracle for the modular black box.

Stable gym contract — core_gym owns setup/grade. This module only exposes:

    Oracle().query(mode, **params) -> observation | dict

Modes:
  - evaluate(x=int)  — returns integer observation (budgeted)
  - help()           — returns mode list + budget remaining (free)

A fresh Oracle() must be constructed per attempt so budget state never leaks.
"""
from __future__ import annotations


class Oracle:
    """Integer black box: f(x) = (a * x + b) mod M."""

    M = 97
    BUDGET = 6

    _A = 23
    _B = 58

    def __init__(self) -> None:
        self._used = 0

    def query(self, mode: str, **params):
        """Stable probe entry point used by the gym harness."""
        if mode == "help":
            return {
                "description": "Integer black box with a known modulus.",
                "modes": {
                    "evaluate": "{x: integer} -> observation: integer",
                    "help": "{} -> {description, modes, budget_remaining, modulus}",
                },
                "budget_remaining": self.BUDGET - self._used,
                "modulus": self.M,
            }

        if mode == "evaluate":
            if "x" not in params:
                raise ValueError("evaluate requires parameter x")
            if self._used >= self.BUDGET:
                raise RuntimeError(f"Query budget exceeded ({self.BUDGET} calls).")
            self._used += 1
            x = int(params["x"])
            return (self._A * x + self._B) % self.M

        raise ValueError(f"Unknown mode: {mode!r}")
