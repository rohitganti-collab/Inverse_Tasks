"""Intended solver for <problem-id> — the correct forward computation.

AUTHORING AND CALIBRATION ONLY. Never mount this under Preloaded Files.

A forward task has no oracle, so there is no engine-run proxy to call this
through. `tools/validate_problem.py` does not exercise forward tasks yet — this
file is your own proof that the correct path works, run manually:

    python3 solution/main.py

Contract: `solve()` returns the answer in the same shape and order as
golden/expected.json.

For a forward task the solver's job is the METHOD DECISION, not an inference:
read the inputs in ../simulation/, pick settings that are actually adequate,
demonstrate the result has converged, and only then commit.

  * Justify the settings in a comment. A reviewer must be able to see you did
    not simply pick the setting that happens to match the golden value.
  * Establish convergence yourself — nothing warns you if you haven't.
  * Run the same domain tool the model will have access to on Taiga.

Per the AI Use Policy, Claude implements this from YOUR spec. You review it.
"""
import math


def run_case(**settings):
    """Invoke the domain tool named in config.yaml against ../simulation/,
    under the given settings, and return the observed quantity.

    REPLACE with your tool's actual invocation, e.g.:
        subprocess.run(["pimpleFoam", "-case", "../simulation"], check=True)
        # then parse the result out of the case's output files
    """
    raise NotImplementedError


def solve():
    """Compute the answer correctly.

    Returns:
        The answer, matching golden/expected.json element for element, in order.
    """
    t = 1 # s
    omega = 1   # s^-1
    m = 5.00e-9 # kg
    d = 1.0e-6 # m
    G = 6.6743e-11 # m^3 kg^-1 s^-2

    delta = G * m / d**3 / omega**2
    omega_minus = omega * math.sqrt(1-2*delta)

    answer = math.cos(omega_minus * t)

    return answer


if __name__ == "__main__":
    print(solve())
