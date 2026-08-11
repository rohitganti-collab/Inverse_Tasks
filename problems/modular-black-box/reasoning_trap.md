# Reasoning trap

## The trap

Sample two convenient points far apart — say x=10 and x=30 — compute
`slope = (output_30 - output_10) / (30 - 10)`, round it to get `a`, then back
out `b` from either reading. Two probes, a clean linear fit, budget to spare.

It fails because between two widely separated inputs the internal value
`a*x + b` almost certainly crosses a multiple of the modulus. The *observed*
difference is therefore not `a * (30 - 10)` — it has been wrapped, and nothing
in the two readings says so. The recovered pair is a near-miss in the exact
sense the playbook means: structurally the right shape (a slope and an
intercept) and numerically wrong.

The wrap leaves no trace. There is no residual to inspect, no goodness-of-fit
that degrades, no diagnostic that fires. Two points always define a line.

## Why a careful solver succeeds

The insight is that spacing is the variable under the solver's control, and that
a wrap can only hide *between* the points you chose. Probe two **adjacent**
inputs and there is no room for one: `f(1) - f(0)` is `a` modulo the modulus,
exactly. Read `b` directly at x=0, then confirm at a third point before
committing — which the budget comfortably allows and which turns a derivation
into a checked one.
