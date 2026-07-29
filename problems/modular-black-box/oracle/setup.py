"""Hidden system for the sample inverse task (TEACHING FIXTURE).

The box computes f(x) = (A*x + B) mod M for hidden A, B. The solver never sees A or B;
it only sees outputs from evaluate(), under a query budget, plus non-committal help().

A fresh Oracle() is created per solver run, so module-level state is never shared across
runs (the same isolation everglades-multitask's preview eval requires per attempt).
"""
import random


class Oracle:
    M = 97          # known modulus (stated in problem.md)
    BUDGET = 6      # evaluate() calls allowed
    _A = 23         # hidden
    _B = 58         # hidden

    # The probe surface handed to the solver. The engine turns each entry into a
    # tool the model can call, so these names/descriptions must match what
    # problem.md promises — and must not hint at the method or the trap.
    #
    # `sample` is intentionally absent: problem.md documents only two ways to
    # call the box, so the noisy mode stays unexposed.
    ACTIONS = [
        {
            "name": "evaluate",
            "description": "Return the box's output for your chosen integer x.",
            "params": {
                "x": {"type": "integer", "description": "The input to the box.", "required": True}
            },
            "costs_budget": True,
        },
        {
            "name": "help",
            "description": "Return a general hint. It will never tell you a or b.",
            "params": {
                "question": {
                    "type": "string",
                    "description": "What you want a hint about.",
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
        self._rng = random.Random(42)  # seeded: deterministic noise for the 'sample' mode

    def _spend(self):
        if self._used >= self.BUDGET:
            raise RuntimeError("Query budget exceeded (6 query calls).")
        self._used += 1

    # Thin wrappers so each declared ACTION is directly serviceable with the
    # parameters it declares. query() below remains the implementation and the
    # interface solution/*.py use.
    def evaluate(self, x):
        return self.query("evaluate", x=x)

    def help(self, question=""):
        return self.query("help")

    def query(self, mode, x=None):
        if mode in ("evaluate", "sample") and x is None:
            raise ValueError("x is required for evaluate/sample modes.")
        if mode == "evaluate":
            self._spend()
            return (self._A * x + self._B) % self.M
        if mode == "sample":
            # A noisy reading: realistic but deterministic via the seeded RNG.
            self._spend()
            noise = self._rng.choice([-1, 0, 1])
            return ((self._A * x + self._B) % self.M + noise) % self.M
        if mode == "help":
            return ("Hint: the output you read may have wrapped around the modulus. "
                    "Adjacent inputs leave no room for a hidden wrap between them. "
                    "(This hint does not reveal the constants.)")
        raise ValueError(f"Unknown mode: {mode!r}")
