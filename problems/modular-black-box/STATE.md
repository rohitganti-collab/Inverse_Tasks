# STATE — the modular black box

> **Reference fixture — do not submit this as your authored task.** It exists so
> you can read a complete, validator-clean inverse task before writing your own,
> and so the engine has an inverse problem to regression-test against. It has
> **not** been calibrated on Taiga; see "Calibration" below.

## Why this answer is the only answer

The box computes `f(x) = (a*x + b) mod 97` and the prompt states the modulus and
constrains both constants to `0 <= a, b < 97`. Two probes pin them exactly:

- `f(0) = b mod 97`, and since `0 <= b < 97`, that reading **is** `b`.
- `f(1) - f(0) = a mod 97`, and since `0 <= a < 97`, that residue **is** `a`.

No other pair inside the stated range reproduces those two readings, so the
answer is unique and independent of which extra points get sampled.

**The range statement is load-bearing, not decoration.** Without it the
observations only determine `a` and `b` up to congruence mod 97 — the pairs
`(23, 58)`, `(120, 58)`, `(23, 155)` are indistinguishable to *any* sequence of
probes, while the grader accepts exactly one. An earlier version of this prompt
omitted the range and was correctly flagged for it. Uniqueness has to hold over
the answer space the prompt actually declares; "the answer is obviously the
small one" is a convention, not an argument.

## Order of decisions

1. Establish that the form is `(a*x + b) mod m` with `m` known — given in the
   prompt, so no budget is spent on it.
2. Recover `b`: it is the reading at `x = 0`.
3. Recover `a`: the change between two **adjacent** inputs, taken mod `m`.
4. Validate against a third point before committing.

Steps 2 and 3 are order-independent in principle but 2 is free of any modular
reasoning, so doing it first leaves only one unknown for step 3.

## Candidate jobs

See `grader/grading_guide.md` for the full near-miss table with reasons. In
brief: the naive-slope pair `[-1, 104]` is the structurally-plausible near-miss
required by playbook step 3; `[0, 58]` is the partial recovery; `[58, 23]` is the
ordering error; `[120, 58]` is the congruent-representative error the range
statement exists to exclude.

## Wrong paths catalogue

- **Two widely spaced probes, linear fit** → `[-1, 104]`. Implemented in
  `solution/shortcut.py`. This is the trap.
- **Stop after `f(0)`** → `[0, 58]`. Reads the free half and calls it done.
- **Brute force** → excluded by budget: recovering `a` by search costs 97 probes
  against a budget of 6.

## Budget

6 budgeted probes. The intended path costs 3 (two to derive, one to confirm);
the shortcut costs 2, so the trap is cheaper than the correct method and stays
tempting. Brute force needs 97. `help` is free and lists modes without
recommending one.

## Calibration

**Not calibrated.** This is a structural reference, not a training task, and it
would not clear the gate if it were one: a frontier model goes straight to the
adjacent-probe path, so the measured pass rate sits far above the band and the
trap never fires. Kept because it demonstrates every artifact correctly, not
because it is difficult.

Your task must clear the gate in `docs/CALIBRATION.md`. Do not copy this one's
difficulty — copy its structure.
