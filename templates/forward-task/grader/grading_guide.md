# Grading guide — Gravitationally coupled coherent states

<!-- YOU own this file. Per the AI Use Policy, Claude must not write it.
     DOES NOT SHIP to Taiga — it names the trap outright. Upload it only as a
     Supporting File, for human review. -->

**Golden answer:** 0.84

**Verified by:** arXiv:2410.21009 eq. (12d)

**Graded:** single number
**Tolerance:** 0.01
**Scoring:** `binary`

<!-- Keep scoring binary unless you really mean otherwise: "partial" awards the
     fraction of matching elements, which rewards the incomplete near-miss. -->


<!-- The tolerance must EXCLUDE the naive-default answer while still admitting a
     genuinely converged solve that made reasonable implementation choices.
     Those two constraints squeeze it from both sides — state both numbers. -->

| | Value |
|---|---|
| Correct answer | `0.84` |
| Naive default produces | `0.79` |
| Separation | `0.05` |
| Tolerance (inside the separation) | `0.01` |

## Near-miss table

<!-- One row per naive path. Every row needs a reason it loses. The row marked
     TRAP is what shortcut.py produces and what ≥60% of failures should hit. -->

| Candidate answer | Looks right because | Why it loses |
|---|---|---|
| `0.84` | — | — (this is the answer) |
| `0.79` **(TRAP)** | Typical textbook treatment using rotating-wave approximation, no signal that points to an incorrect answer | The RWA is valid for $\omega_g/\omega \ll 1$ but here we have $omega_g/\omega \approx 1/3$ close to unity |

## Edge cases the judge should know

<!-- e.g. "Accept the value inside a JSON wrapper iff unambiguous. Reject a
     range or multiple candidates. A correct value reported in the wrong units
     is wrong — units were stated." -->
