"""Shortcut (trap) solver for <problem-id> — the default path, made concrete.

AUTHORING AND CALIBRATION ONLY. Never mount this under Preloaded Files.

This file MUST FAIL when run against your intended check (see main.py): if the
default is not wrong enough, or the tolerance is too wide, the task does not
discriminate. There is no oracle-based validator to run this through — prove it
fails yourself:

    python3 solution/shortcut.py

It must also fail ONTO THE NAMED NEAR-MISS in grader/grading_guide.md.

For a forward task the shortcut is almost always ONE RUN AT THE DEFAULTS,
reported without any convergence check. That is exactly what makes it tempting:
it is cheap, it completes cleanly, and the number looks entirely reasonable.

Common forward traps:
  * Default mesh/resolution — unconverged, but plausible
  * Default method — steady-state where the physics is unsteady
  * No convergence check at all; one run and report
  * A default convention (sign, reference quantity, denominator)
  * An instantaneous value where a time-average was required
"""

import math

def solve():
    """The default path. Must land on the named near-miss.

    Returns:
        The near-miss answer — right shape, wrong value.
    """
    t = 1 # s
    omega = 1   # s^-1
    m = 5.00e-9 # kg
    d = 1.0e-6 # m
    G = 6.6743e-11 # m^3 kg^-1 s^-2

    delta = G * m / d**3 / omega**2
    omega_minus = omega * (1-delta)  # rotating-wave approximation (invalid)

    answer = math.cos(omega_minus * t)

    return answer


if __name__ == "__main__":
    print(solve())
