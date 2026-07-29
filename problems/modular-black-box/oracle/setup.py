"""oracle/setup.py — HIDDEN system. The model never sees this file.

Public probe API is `handle_query` / `query_oracle`, wrapped in a `class Oracle`
so the Inverse_Tasks / Taiga MCP engine can load it.

The box computes f(x) = (a*x + b) mod M for hidden a, b. The solver only sees
observations from budgeted probes — never the parameters, never judgments.
"""
from __future__ import annotations

import random

# === Hidden parameters (the thing the model must infer) ===
HIDDEN_PARAMS = {
    "a": 23,
    "b": 58,
}

# Known to the solver (stated in problem.md). Not hidden.
M = 97
_BUDGET = 6

# Module-level session used by the free functions (`handle_query` /
# `query_oracle`) when this file is imported from solution/main.py. Taiga
# always constructs a fresh Oracle() per attempt instead.
_MODULE_ORACLE = None


def _system_observation(mode: str, params: dict, hidden: dict, modulus: int):
    """The actual map — discrete modular affine transform."""
    if mode == "evaluate":
        if "x" not in params:
            return {"error": "parameter 'x' is required"}
        try:
            x = int(params["x"])
        except (TypeError, ValueError):
            return {"error": "parameter 'x' must be an integer"}
        return (hidden["a"] * x + hidden["b"]) % modulus
    return {"error": f"unknown mode {mode!r}"}


def handle_query(mode: str, parameters: dict | None = None):
    """Public probe interface. Routes to modes."""
    global _MODULE_ORACLE
    if _MODULE_ORACLE is None:
        _MODULE_ORACLE = Oracle()
    return _MODULE_ORACLE.handle_query(mode, parameters)


# Alias kept for solution scripts and local tooling that import query_oracle.
query_oracle = handle_query


class Oracle:
    """Taiga / Inverse_Tasks adapter around the same instrument.

    A fresh Oracle() is created per solver run / problem-run, so module-level
    state is never shared across attempts.
    """

    M = M
    BUDGET = _BUDGET
    _A = HIDDEN_PARAMS["a"]
    _B = HIDDEN_PARAMS["b"]

    # Probe surface handed to the solver. Names must match problem.md.
    # `sample` / noisy modes stay undeclared so they cannot be called.
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

    # Shape only — never the values. Drives submit_answer's format feedback.
    ANSWER_SCHEMA = {
        "type": "array",
        "length": 2,
        "item_types": ["integer"],
        "keys": ["a", "b"],
        "description": "The pair (a, b), in that order.",
    }

    def __init__(self):
        self._used = 0
        self._hidden = dict(HIDDEN_PARAMS)
        self._rng = random.Random(42)

    def handle_query(self, mode: str, parameters: dict | None = None):
        """Instrument entry point — observations only, never judgments."""
        parameters = parameters or {}

        if mode == "help":
            # Lists modes + signatures. Does NOT recommend a mode or name a method.
            return {
                "description": "Integer black box with a known modulus.",
                "modes": {
                    "evaluate": "{x: integer} -> {observation: integer}",
                    "help": "{} -> {description, modes, budget_remaining}",
                },
                "budget_remaining": self.BUDGET - self._used,
                "modulus": self.M,
            }

        self._used += 1
        if self._used > self.BUDGET:
            return {"error": "budget exceeded"}

        obs = _system_observation(mode, parameters, self._hidden, self.M)
        if isinstance(obs, dict) and "error" in obs:
            return obs
        return {"observation": obs, "unit": "integer"}

    # Thin wrappers so each declared ACTION is directly serviceable, and so
    # solution/*.py written against either contract keep working.
    def evaluate(self, x):
        result = self.handle_query("evaluate", {"x": x})
        if isinstance(result, dict) and "observation" in result:
            return result["observation"]
        if isinstance(result, dict) and "error" in result:
            raise RuntimeError(result["error"])
        return result

    def help(self, question=""):
        return self.handle_query("help", {"question": question})

    def query(self, mode, x=None, **params):
        """Dispatcher for Inverse_Tasks when no per-action method is preferred.

        Accepts both `query(mode, parameters={...})` kwargs and `query(mode, x=...)`.
        """
        if x is not None and "x" not in params:
            params["x"] = x
        result = self.handle_query(mode, params)
        # Keep evaluate return shape stable for existing solvers (bare int).
        if mode == "evaluate" and isinstance(result, dict) and "observation" in result:
            return result["observation"]
        if isinstance(result, dict) and "error" in result:
            raise RuntimeError(result["error"])
        return result
