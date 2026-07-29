"""TEMPLATE shortcut solver — the tempting professional error.

This must produce a structurally-plausible but numerically wrong answer. The
validator runs it and requires it to FAIL. If it passes, your trap isn't a trap.
"""


def solve(oracle):
    y = oracle.evaluate(1)
    return [y % 100]  # off by the input offset — plausible, wrong
