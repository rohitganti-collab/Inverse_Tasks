"""Hidden system for <problem-id>. THE MODEL NEVER SEES THIS FILE.

Ships to Taiga (Preloaded Files). On Taiga it is root-owned and owner-only while
model-side tools run as uid 1000, so the model can only reach it through the
probe surface you declare below.

The engine builds a fresh Oracle() per attempt and calls, in order of preference:
  1. `oracle.evaluate(**params)`        — a method named after the action
  2. `oracle.query("evaluate", **params)` — a single dispatcher, if you prefer

Methods are recommended and are what this template uses.

WHAT THE ENGINE DOES FOR YOU — don't hand-roll these:
  * BUDGET is enforced by the engine. You do not need to count calls yourself.
    A call that reaches your oracle and then raises still spends its call.
    A rejection that never reaches you (unknown action, bad parameter) does not.
  * Only actions declared in ACTIONS are reachable. Anything you leave out is
    unreachable — that is how you keep a debug or noisy mode private.
  * Parameters are validated against your declarations before they reach you.

WHAT YOU MUST DO:
  * Put hidden ground truth in `_`-prefixed names. Solvers and the model cannot
    read them; the validator proxy raises on access.
  * Put ALL per-attempt state in __init__, never at class level.
  * SEED ANY RANDOMNESS (`random.Random(42)`). Taiga runs the same problem many
    times and needs the environment reproducible.
  * Never print. The return value is the whole interface.

THE ORACLE IS AN INSTRUMENT, NOT A GRADER. Return observations — never
accepted/rejected, never close-enough, never a hint. No `check_*` or
`validate_*` actions: the model will search against them instead of reasoning.

Dependencies: standard library only unless the image already carries the package.
"""

import math
import numpy as np

class Oracle:
    """<one line: what the hidden system is, without giving away the answer>"""

    # Budgeted calls allowed. The engine enforces this. Absent or None =
    # unlimited, which almost always makes an inverse task too easy.
    BUDGET = 4

    # --- hidden ground truth: `_` prefix makes it unreachable -------------- #
    _SECRET = 5.00

    # --- public constants: safe for the model, state them in problem.md ---- #
    # M = 97

    # The probe surface. Each entry becomes a tool the model can call, named
    # exactly as you name it. `describe_oracle()` renders this for the model, and
    # the container appends a generated calling guide to your prompt — which is
    # why problem.md must NOT document the call syntax itself.
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
            # A second informative mode. Multi-mode oracles force the model to
            # CHOOSE which observation is worth spending budget on — one mode
            # means no decision to make and no reasoning signal. Make this a
            # genuinely different measurement, not a variant of the first.
            "name": "coarse_reading",
            "description": "Return a lower-resolution reading of the same output.",
            "params": {
                "x": {"type": "integer", "description": "The input.", "required": True},
            },
            "costs_budget": True,
        },
        {
            "name": "help",
            "description": (
                "List available modes and remaining budget. Never reveals hidden "
                "values or the intended method."
            ),
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

    # Describes the answer shape. The engine surfaces this via describe_oracle()
    # so the model knows what to submit — keep it consistent with
    # golden/expected.json and with the Output format section of problem.md.
    ANSWER_SCHEMA = {
        "type": "array",
        "length": 1,
        "item_types": ["integer"],
        "description": "Describe the answer shape the model must submit.",
    }

    def __init__(self):
        # ALL per-attempt state here — never at class level, or it leaks between
        # rollouts. Seed any RNG: self._rng = random.Random(42)
        self._used = 0

    # ------------------------------------------------------------- actions #
    def evaluate(self, t: float):
        """Replace with your forward map. Return an observation, never the secret."""
        self._used += 1

        m = self._SECRET * 1e-9 # kg  -- the secret parameter to be found

        # given:
        omega = 1   # s^-1
        d = 1.0e-6 # m
        G = 6.6743e-11 # m^3 kg^-1 s^-2
        hbar = 6.62607e-34 # m^2 kg s^-1

        # prefactor sqrt(2 hbar/(m omega)) * alpha remains unknown:
        pre = 3.0

        delta = G * m / d**3 / omega**2
        omega_minus = omega * math.sqrt(1-2*delta)

        answer = pre * math.cos(omega_minus * t)

        return answer

    def coarse_reading(self, t: float):
        """Replace with a genuinely different, lossier view of the system."""
        self._used += 1
        max_error = 0.1
        n = 10
        errors = 2 * max_error * np.random.random_sample(n) - max_error
        vals = [self.evaluate(t+dt) for dt in errors]
        return sum(vals) / len(vals)

    def help(self, question: str = ""):
        """List modes and budget. Recommend nothing; explain no physics."""
        return {
            "description": "Expectation value for first oscillator position at given time t",
            "modes": {
                "evaluate": "{t: float} -> float",
                "coarse_reading": "{t: float} -> float",
                "help": "{} -> {description, modes, budget_remaining}",
            },
            "budget_remaining": self.BUDGET - self._used,
        }
