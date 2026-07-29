"""TEMPLATE intended solver — proves the task is solvable within budget.

Authoring / calibration only. Never mount this under Preloaded Files.
"""


def solve(oracle):
    # Prefer query_oracle-style calls; the validator proxy also accepts methods.
    help_info = oracle.query("help")  # free
    _ = help_info
    y = oracle.query("evaluate", x=0)
    return [y]  # replace with your inversion
