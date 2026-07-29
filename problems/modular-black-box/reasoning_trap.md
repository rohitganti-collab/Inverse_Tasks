# Reasoning Trap

## The trap

The naive textbook move is to treat the box as an ordinary straight line: sample
two convenient points far apart (say `x = 10` and `x = 30`), compute
`slope = (output_30 - output_10) / (30 - 10)`, round it to get `a`, then back
out `b`. Between two far-apart inputs the internal value `a·x + b` almost
certainly crosses a multiple of the modulus, so the *observed* difference is
not `a · (30 - 10)` at all — it has been wrapped. The recovered pair is a
near-miss: structurally the right shape (a slope and an intercept) but
numerically wrong.

## Why a careful solver succeeds

A careful solver recovers `b` at `x = 0` and the per-step change between two
*adjacent* inputs, where no wrap can hide between them, then checks one more
point before committing.
