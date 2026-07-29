"""TEMPLATE oracle — copy this folder to problems/<your-problem-id>/ and edit.

The model never sees this file. In Taiga it is root-owned and owner-only while
model-side tools run as uid 1000. The model may only probe through
`query_oracle(mode, parameters)`.

Contract (pick one entry point):
  * `class Oracle` with `ACTIONS` + methods  (recommended for Inverse_Tasks)
  * or module-level `query_oracle(mode, parameters)` / `handle_query(...)`

Rules:
  * Hidden ground truth in underscore-prefixed names or HIDDEN_PARAMS.
  * Never return judgments (no check_*/validate_* modes).
  * `help` lists modes + budget only — no method names, no strategy hints.
  * Seed randomness. A fresh Oracle() is built per attempt.
"""


class Oracle:
    BUDGET = 6

    # Hidden ground truth — underscore = unreachable by solvers / the model.
    _SECRET = 42

    ACTIONS = [
        {
            "name": "evaluate",
            "description": "Return the system's output for your chosen input.",
            "params": {
                "x": {"type": "integer", "description": "The input.", "required": True},
            },
            "costs_budget": True,
        },
        {
            "name": "help",
            "description": "List available modes and remaining budget. Never reveals hidden values.",
            "params": {
                "question": {
                    "type": "string",
                    "description": "Unused; accepted for a uniform calling shape.",
                    "default": "",
                },
            },
            "costs_budget": False,
        },
    ]

    ANSWER_SCHEMA = {
        "type": "array",
        "length": 1,
        "item_types": ["integer"],
        "description": "Describe the answer shape the model must submit.",
    }

    def __init__(self):
        self._used = 0

    def evaluate(self, x: int):
        # Replace with your forward map. Return an observation, never the secret.
        return (int(x) + self._SECRET) % 100

    def help(self, question: str = ""):
        return {
            "description": "Replace with one neutral line about the system.",
            "modes": {
                "evaluate": "{x: integer} -> {observation: integer}",
                "help": "{} -> {description, modes, budget_remaining}",
            },
            "budget_remaining": self.BUDGET - self._used,
        }

    def query(self, mode: str, **params):
        """Stable dispatcher — same shape the MCP `query_oracle` tool forwards."""
        if mode == "evaluate":
            if "x" not in params:
                raise ValueError("evaluate requires parameter x")
            return self.evaluate(params["x"])
        if mode == "help":
            return self.help(params.get("question", ""))
        raise ValueError(f"Unknown mode: {mode!r}")


# Optional module-level alias (same contract as MCP query_oracle).
_MODULE_ORACLE = None


def query_oracle(mode: str, parameters=None):
    global _MODULE_ORACLE
    if _MODULE_ORACLE is None:
        _MODULE_ORACLE = Oracle()
    return _MODULE_ORACLE.query(mode, **(parameters or {}))

