"""Intended solver for <problem-id> — the correct path.

AUTHORING AND CALIBRATION ONLY. Never mount this under Preloaded Files; it does
not ship to Taiga.

Contract: `solve(oracle)` returns the answer in the same shape and order as
golden/expected.json. Return it; do not print it.

The validator runs this through the SAME budgeted path the model uses, so
`oracle` is a proxy, not the raw class:
  * declared actions work either way — `oracle.evaluate(0)` or
    `oracle.query("evaluate", x=0)`
  * public constants pass through — `oracle.M`, `oracle.BUDGET`
  * `_`-prefixed attributes RAISE. You cannot read `_SECRET` to "prove" this
    works, and an undeclared action is an error.

It must pass within budget. See Step 7 in ../INSTRUCTIONS.md.

Per the AI Use Policy, Claude implements this from YOUR spec. You review it.
"""

import math

def solve(oracle):
    """Recover the hidden values from budgeted observations.

    Args:
        oracle: budgeted proxy over a fresh Oracle instance.

    Returns:
        The answer, matching golden/expected.json element for element, in order.
    """
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
    print('x:', x)

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

    # b is Omega_- = omega * sqrt(1-2 delta)
    delta = (1 - (b / omega)**2) / 2

    # delta = omega_g / omega = G m / (omega^2 d^3)

    m = delta * omega**2 * d**3 / G
    m *= 1e9 # in microgram

    answer = [m]

    # 4. Validate against one more probe before committing, if budget remains.
    # N/A

    return answer

