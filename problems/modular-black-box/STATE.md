# STATE — modular-black-box

state: CALIBRATED
name: modular-black-box
directionality: Inverse

## Why this answer is the only answer

The box is fully determined by the pair `(a, b)` under the known modulus `M = 97`.
Two clean observations at `x = 0` and `x = 1` pin both constants exactly:
`f(0)` gives `b`, and `(f(1) - f(0)) mod M` gives `a`. No other pair in
`{0, …, M-1}²` reproduces those two outputs. The answer is therefore unique and
stable — it does not depend on which extra points you sample.

## Order of decisions

1. Establish the modulus is known and the form is `(a·x + b) mod M` (given).
2. Recover `b` first (it is the output at `x = 0`).
3. Recover `a` from the change between two *adjacent* inputs, taken modulo `M`.
4. Validate against one more point before committing.

## Candidate jobs

| Wrong answer | Why it loses |
|---|---|
| Naive-slope pair (e.g. `[-1, 104]`) | Fits a clean line through far-apart samples; modular wrap between them corrupts the slope. |
| `b` only / `a = 0` | `b` is easy to read off at `x = 0`; incomplete — the task asks for both. |
| Swapped `(b, a)` | Both numbers are present; order is specified as `(a, b)`. |
| Unreduced integers outside `0..M-1` | Congruent but not the canonical residues the golden expects. |

## Wrong paths catalogue

| Shortcut | Produces |
|---|---|
| Sample `x = 10` and `x = 30`, take `slope = (y30 - y10) / 20`, round, back out intercept | Naive-slope near-miss |
| Query only `x = 0`, submit `[0, b]` or `[?, b]` | Incomplete `b`-only answer |
| Recover both but swap order on submit | Swapped pair |

## Notes

Intended solver passes; naive shortcut fails. Preview recorded at 1/8.
Teaching fixture — no external simulator required.
