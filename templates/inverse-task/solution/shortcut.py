"""Shortcut (trap) solver for <problem-id> — the wrong path, made concrete.

AUTHORING AND CALIBRATION ONLY. Never mount this under Preloaded Files.

This file MUST FAIL. `tools/validate_problem.py` runs it and treats a pass as a
FAIL of the task: a trap that scores 1.0 means the task does not discriminate.

Failing is not enough. It must fail ONTO THE NAMED NEAR-MISS in
grader/grading_guide.md — that is what makes the ≥60% failure-concentration
check meaningful. Run it and look at what it returns.

The shortcut has to be genuinely TEMPTING: the error a competent colleague would
really make, not a strawman. It should also be CHEAPER in budget than the
intended path — that is what makes it attractive.

Same contract and proxy rules as main.py: `solve(oracle)` returns the answer in
golden/expected.json's shape, and `_`-prefixed attributes raise.

Common shortcuts worth implementing:
  * One mode only, no cross-check against a second observation
  * Two far-apart samples where the structure hides something in between
  * A default convention applied without checking (sign, denominator, units)
  * A memorised textbook constant instead of a measured one
  * Ignoring noise / not averaging when the reading is noisy
  * Stopping at the first plausible-looking value
"""

import math

def solve(oracle):
    """The tempting-but-wrong path. Must land on the named near-miss.

    Args:
        oracle: budgeted proxy over a fresh Oracle instance.

    Returns:
        The near-miss answer — right shape, wrong value.
    """
    # The cheap, unconsidered read. REPLACE with the error from reasoning_trap.md.
    #
    # Placeholder: reach for the lower-resolution mode because it looks like the
    # same measurement, and lose the precision the answer depends on.

    # given:
    omega = 1   # s^-1
    d = 1.0e-6 # m
    G = 6.6743e-11 # m^3 kg^-1 s^-2

    # 1. Discover the probe surface and budget. Free.
    help_info = oracle.help()

    # 2. Spend budget deliberately. Choose the modes and inputs that actually
    #    discriminate between the candidate answers enumerated in Step 3.
    #
    #    REPLACE: the placeholder system is (x + secret) % 100, so the full-
    #    resolution reading at x=0 returns the secret directly.
    T = 1
    t_samples = [0, T, T*math.sqrt(2), T*math.sqrt(3)]
    x = []
    for t in t_samples:
      x.append(oracle.evaluate(t))

    # 3. Invert: observations -> hidden values.

    # we know that the oracle has the form f(t) = a * cos(b t)
    a = x[0]

    if abs(a) < 1e-30:
        raise ValueError("a = 0, so b cannot be determined")

    c1 = x[1] / a

    # Protect against tiny floating-point excursions
    c1 = max(-1.0, min(1.0, c1))

    # Here b = Omega_- = omega*sqrt(1 - 2*delta).
    # Since delta >= 0 and Omega_- is real:
    #     0 <= b <= omega = 1 < pi
    # so there is no cosine aliasing.
    b = math.acos(c1) / T

    # rotating-wave approximation: b is Omega_- = omega * (1-delta)
    # NOTE: this is the intended error
    delta = 1 - (b / omega)

    # delta = omega_g / omega = G m / (omega^2 d^3)

    m = delta * omega**2 * d**3 / G
    m *= 1e9 # in microgram

    answer = [m]

    # 4. Validate against one more probe before committing, if budget remains.
    # N/A

    return answer
