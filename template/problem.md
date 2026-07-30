# Task setup

Describe the black box: what it accepts, what it returns, and the form of its
internal computation. State every constant the solver is allowed to know.

State the setup and the budget, and nothing about how to solve it — the solver
must not be able to read the intended method, or the error it discriminates
against, out of your wording.

# What you can use

You have access to `query_oracle(mode, parameters)`. Call
`query_oracle(mode="help", parameters={})` to discover available modes and your
remaining budget. Budgeted probes may be used at most **N** times.

# Your task

State exactly what to recover.

# Output format

Describe the submission shape, matching `golden/expected.json` element for
element and in the same order. State the tolerance.

Submit your answer via `submit_answer(answer)`.
