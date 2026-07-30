"""Shortcut solver — the tempting wrong path. Must FAIL.

Local calibration only. Never ships in the Docker image.
"""


def solve(oracle):
    y10 = oracle.query("evaluate", x=10)
    y30 = oracle.query("evaluate", x=30)
    a = round((y30 - y10) / (30 - 10))
    b = y10 - a * 10
    return [a, b]
