# Task setup

You are given access to a black box. It accepts one integer `x` and returns one
integer. Internally it computes

```
output = (a * x + b) mod 97
```

where `a` and `b` are fixed whole numbers you cannot see, and `97` is a known
modulus.

# What you can use

You have access to a hidden `query(mode, **params)` function on the oracle.
Call `query("help")` to discover available modes and your remaining query budget.
You may call budgeted modes at most **6** times in total.

# Your task

Recover the hidden pair `(a, b)`.

# Output format

Submit a JSON array of two integers, in this order: `a`, then `b`.
Exact integers — no tolerance.
