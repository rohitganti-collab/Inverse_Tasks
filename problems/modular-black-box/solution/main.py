"""Intended solver — proves the task is solvable within budget.

Local calibration only. Never ships in the Docker image.
"""


def solve(oracle):
    help_info = oracle.query("help")
    modulus = int(getattr(oracle, "M", 97))
    if isinstance(help_info, dict) and "modulus" in help_info:
        modulus = int(help_info["modulus"])

    b = oracle.query("evaluate", x=0)
    y1 = oracle.query("evaluate", x=1)
    a = (y1 - b) % modulus

    y2 = oracle.query("evaluate", x=2)
    assert y2 == (a * 2 + b) % modulus
    return [a, b]
