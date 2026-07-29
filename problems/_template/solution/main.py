"""TEMPLATE intended solver — the correct path, within budget.

`solve(oracle)` receives a fresh Oracle and must return the answer in the same
shape as golden/expected.json. The validator runs this and requires it to pass.

You may call oracle methods directly (oracle.evaluate(...)) or go through
oracle.query("evaluate", x=...) — whichever your oracle implements.
"""


def solve(oracle):
    y = oracle.evaluate(0)
    return [y % 100]
