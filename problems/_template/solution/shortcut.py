"""TEMPLATE shortcut solver — the tempting wrong approach.

MUST FAIL against the oracle. If it passes, the task does not discriminate.
Authoring / calibration only. Never mount this under Preloaded Files.
"""


def solve(oracle):
    y = oracle.query("evaluate", x=0)
    return [y]  # replace with the naive near-miss path
