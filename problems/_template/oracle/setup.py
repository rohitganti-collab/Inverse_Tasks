"""TEMPLATE oracle — copy this folder to problems/<your-problem-id>/ and edit.

The engine only requires a class named `Oracle`. Everything below is either
required (`ACTIONS` or public methods or `query`) or optional-with-a-default.

Rules that matter for task quality (see sample_experts_instructions.md):
  * Keep the hidden ground truth in private attributes (leading underscore).
  * Never let a description, hint, or error message name the method or the trap.
  * Seed any randomness so a run is reproducible.
"""


class Oracle:
    # ---- Public constants the solver is allowed to know ------------------- #
    # Anything without a leading underscore may be read by the intended
    # solver in solution/main.py, so put stated-in-the-prompt facts here.

    BUDGET = 6          # Budgeted calls allowed. Set to None for unlimited.

    # ---- Hidden ground truth --------------------------------------------- #
    _SECRET = 42

    # ---- The probe surface ------------------------------------------------ #
    # Each entry becomes a tool the model can call. Names must match what your
    # problem.md tells the solver to call.
    #
    # params: {name: {"type": integer|number|string|boolean|array|object,
    #                 "description": str,
    #                 "required": bool,        # default True unless a default is given
    #                 "default": ...}}
    # costs_budget: whether a call spends query budget (default True).
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
            "description": "Return a general hint. It never reveals the hidden values.",
            "params": {
                "question": {"type": "string", "description": "What to hint about.", "default": ""},
            },
            "costs_budget": False,
        },
    ]

    # Shape of the expected answer — shape only, never the values. Optional; if
    # omitted it is inferred from golden/expected.json.
    ANSWER_SCHEMA = {
        "type": "array",
        "length": 1,
        "item_types": ["integer"],
        "description": "Describe the answer's shape for the solver.",
    }

    def __init__(self):
        # A fresh Oracle is constructed for every attempt, so per-run state
        # belongs here rather than at class level.
        self._used = 0

    # ---- Implementation --------------------------------------------------- #
    # You may implement one method per action (recommended, shown here) or a
    # single `query(mode, **params)` dispatcher. The engine supports both.

    def evaluate(self, x):
        return (x + self._SECRET) % 100

    def help(self, question=""):
        return "Hint: think about what a single probe can and cannot pin down."
