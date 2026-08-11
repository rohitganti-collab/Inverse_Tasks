# Grading guide — the modular black box

**Golden answer:** the pair `(a, b)`, graded element-wise, integer tolerance 0.

Tolerance rationale: the answer space is the integers mod 97 and the intended
solver recovers both constants exactly on every run, so any tolerance above 0
would admit a neighbouring residue. Exact match is both achievable and strictly
tighter than the distance to every near-miss below.

## Near-miss table

| Submitted | Looks right because | Why it loses |
|---|---|---|
| `[23, 58]` | Recovered from adjacent probes at x=0 and x=1, confirmed at a third point | — this is the answer |
| `[-1, 104]` | A clean linear fit through two widely spaced probes; two points always define a line | The internal value wrapped between them, so the observed difference is not `a·Δx`. **This is the trap** (`solution/shortcut.py`) |
| `[0, 58]` or `[58, 0]` | `b` falls straight out of `f(0)`, so half the answer is free | Incomplete — the task asks for both constants |
| `[58, 23]` | Both correct numbers are present | Order matters; the prompt specifies `a` then `b` |
| `[120, 58]` | `120 ≡ 23 (mod 97)` — the same box | Out of the stated range `0 <= a, b < 97`; the prompt asks for the canonical residue |

## Edge cases

- Accept `{"a": 23, "b": 58}` as well as `[23, 58]` — `golden/expected.json`
  declares `keys`, so the engine takes either form.
- Reject an answer that names the constants correctly in prose but submits a
  malformed array. Format failures are logged separately from reasoning
  failures; see the artefact-rate cap in `docs/CALIBRATION.md`.
