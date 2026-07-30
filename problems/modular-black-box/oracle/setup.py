"""Hidden oracle for modular-black-box.

The model never imports this file. Taiga's MCP server loads `class Oracle` and
exposes probes only through `query_oracle(mode, parameters)`.

Contract used by the gym / MCP engine:

    Oracle().query(mode, **params) -> observation

Modes:
  - evaluate(x=int)  — budgeted integer observation
  - help()           — free; lists modes + remaining budget
"""
from __future__ import annotations


class Oracle:
    """f(x) = (a * x + b) mod M, with hidden a, b."""

    M = 97
    BUDGET = 6
    _A = 23
    _B = 58

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
            "description": "List available modes and remaining budget. Never reveals a or b.",
            "params": {
                "question": {
                    "type": "string",
                    "description": "Unused; accepted for a uniform calling shape.",
                    "default": "",
                }
            },
            "costs_budget": False,
        },
    ]

    ANSWER_SCHEMA = {
        "type": "array",
        "length": 2,
        "item_types": ["integer"],
        "keys": ["a", "b"],
        "description": "The pair (a, b), in that order.",
    }

    def __init__(self) -> None:
        # Fresh instance per attempt — budget must not leak across runs.
        self._used = 0

    def query(self, mode: str, **params):
        """Stable probe entry point. MCP `query_oracle` forwards here."""
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

    # Named methods so ACTIONS can dispatch without going through query().
    def evaluate(self, x: int):
        return self.query("evaluate", x=x)

    def help(self, question: str = ""):
        return self.query("help", question=question)


# Optional module-level alias for local scripts (same shape as the MCP tool).
_MODULE_ORACLE = None


def query_oracle(mode: str, parameters=None):
    global _MODULE_ORACLE
    if _MODULE_ORACLE is None:
        _MODULE_ORACLE = Oracle()
    return _MODULE_ORACLE.query(mode, **(parameters or {}))
