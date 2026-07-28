# Expert Instructions

**Your job:** author one *inverse task* — a scientific puzzle with a hidden, provably unique answer that a competent scientist can get wrong in a specific, predictable way. You own the science. Claude writes the code.

## Forward vs. Inverse — the one thing to internalize

- **Forward** = given the cause, compute the consequence. (Given rate constants, find concentration at t=10.) This is what your tool already does. Not what we want.
- **Inverse** = given the consequence (observations), recover the hidden cause, by probing the tool under a tight budget. (Given concentration measurements, recover the rate constants.) **This is the task.**

Your tool is the forward computation. The task wraps it in a budgeted "black box" the model must query strategically to work backward.

## The 8 Steps, in order — don't skip ahead

1. **Lock the answer.** Fix the hidden ground truth. Write down *why no other answer is possible* — this is your uniqueness argument. If you can't prove uniqueness, stop and pick a different setup.
2. **Order the decisions.** What must be measured/known first? What does it unlock? Where does validation belong? This becomes the intended solution path.
3. **Enumerate the near-misses.** List every wrong answer a *competent* colleague might produce, and why each is tempting. At least one must look structurally correct (right shape, wrong number).
4. **Pick the trap.** Choose the single most common professional error from your list. This is what the task is actually testing.
5. **Spec the code.** Write a precise spec for: the hidden oracle, the intended (correct) solver, and the shortcut (trap) solver. Claude implements all three from your spec — you review, you don't write Python.
6. **Set the budget.** Tight enough that: the shortcut is cheap and tempting, brute force is impossible, and the correct path barely fits. If a model can afford to try everything, the task is broken.
7. **Calibrate.** Run the automated harness. It checks: intended solver passes 32/32, shortcut fails 32/32, pass rate lands in **0.15–0.40** (target ~0.30) across three model checkpoints, and failures concentrate (≥60%) on your labeled near-miss. If it doesn't clear this, revise — don't ship.
8. **Write the prompt — last, in your own words.** Never let Claude draft the solver-facing prompt. State the setup and the budget. **Never name the trap, the method, or hint at the fix** — not in the prompt, not in any tool's help text or diagnostic output.

## What "good" looks like (the gate you must clear)

| Check | Requirement |
|---|---|
| Uniqueness | Provably one answer — argued in `STATE.md` |
| Pass rate | 0.15–0.40 at N=32, across ≥3 checkpoints |
| Shortcut | Fails 32/32 — proven by running it, not asserted |
| Concentration | ≥60% of failures land on your named near-miss |
| Tolerance | Tighter than the distance to the nearest near-miss |
| Leakage | Prompt *and* tool outputs never name the trap or method |
| Budget | Excludes brute force; shortcut and intended path both fit |

## AI Use Policy

| You own | Claude does |
|---|---|
| The hidden answer + uniqueness argument | Oracle implementation |
| The near-miss taxonomy | Intended + shortcut solver code |
| The trap (why the shortcut is tempting) | Verifier script (you validate it against your ground truth) |
| The solver-facing prompt, written yourself | — |

## Common ways tasks get rejected

- Pass rate is 0/32 (impossible) or ≥25/32 (too easy) — not in the training band
- The trap is named or hinted anywhere the solver can see, including tool diagnostics
- Budget is loose enough that brute force or trial-and-error works
- The "shortcut" isn't actually tempting — no one would really make that mistake
- Tolerance is wide enough that the near-miss answer also passes

**When in doubt:** if a smart colleague reading only the prompt would fall into your trap roughly a third of the time, you've got it right.
