# Brief — modular-black-box

**Domain:** Samples
**Subdomain:** modular arithmetic / discrete inverse problems
**Tool:** none (pure oracle; no external simulator)
**Directionality:** Inverse
**Source paper (if any):** none — teaching fixture

## The idea

There is a black box that turns a whole number into another whole number. Under
the hood it multiplies by one hidden constant, adds a second hidden constant,
and wraps the result around a known modulus. The solver can poke the box a
handful of times and must recover both hidden constants. The investigation is
interesting because the wrap-around is invisible in the outputs — a solver who
assumes a plain straight line will be fooled.

## What the model must report

The pair `(a, b)` as a JSON array of two integers, in that order — e.g. `[23, 58]`.
Exact match (tolerance 0).
