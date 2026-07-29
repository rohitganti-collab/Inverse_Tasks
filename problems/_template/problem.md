# Task setup

<!-- Experts: paste this into Taiga's Task Prompt field (preferred), or keep it
     here as problem.md. The container appends the query_oracle calling guide. -->

Describe the hidden system in your own words: what the box accepts, what it
returns, and what is known about its internal form. State the query budget.

Do **not** name the intended method, the trap, or how to solve it.

# What you can use

You have access to `query_oracle(mode, parameters)`. Call
`query_oracle(mode="help", parameters={})` to discover available modes and your
remaining budget.

# Your task

State exactly what to recover, in what format and order.

# Output format

State the exact JSON shape (e.g. a length-2 integer array).

Submit your answer via `submit_answer(answer)`.
