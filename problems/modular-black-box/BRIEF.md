# BRIEF — the modular black box

> **Reference fixture — do not submit.** A complete, validator-clean inverse
> task kept so the engine has something to test against and so experts can read
> one before writing their own. Deliberately domain-neutral: no science
> background needed, so the *reasoning pattern* is what comes through.

One paragraph, in the author's words:

> There is a black box that turns a whole number into another whole number.
> Under the hood it multiplies by one hidden constant, adds a second hidden
> constant, and wraps the result around a known modulus. The solver can poke the
> box a handful of times and must recover both hidden constants. The
> investigation is interesting because the wrap-around is invisible in the
> outputs — every reading looks like a perfectly ordinary integer, so a solver
> who assumes the box is a plain straight line has no signal telling them
> otherwise.
