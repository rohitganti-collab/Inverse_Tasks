# Calibration — the shipping gate

**This file is the single source of truth for the bar.** Where any other
document disagrees with it, this one wins. If you find a disagreement, fix the
other document rather than averaging the two.

---

## Why a pass rate at all

A task is training data for reinforcement learning, and RL learns from
disagreement between rollouts. Under group-relative policy optimisation with a
binary reward, a group where every rollout agrees contributes an advantage of
identically zero — no gradient, whatever the task cost to author. That is true
at 0/32 and equally true at 32/32.

So "hard" is not the target. **In-band** is the target.

| Pass rate | Gradient magnitude (% of peak) |
|---|---|
| 0.125 | 66% |
| 0.15 | 71% |
| 0.20 | 80% |
| 0.30 | 92% |
| 0.40 | 98% |
| 0.50 | 100% |

Pure gradient argument says aim at 0.5. We aim lower, at **0.15–0.40 centred
near 0.30**, for three reasons that have nothing to do with variance:

1. **Shelf life.** A task at 0.5 today is at 0.85 in two model generations. A
   corpus bought at 0.5 is a depreciating asset.
2. **Teaching above current competence.** Data at the model's existing
   capability level reweights very little.
3. **Curriculum headroom.** The corpus has to stay useful across a training
   run, not saturate inside it.

At p ≈ 0.30 the model already possesses the correct reasoning path — it finds
it about a third of the time — and RL is shifting mass from the shortcut toward
the correct method. That only works if the failures are clean, which is what the
concentration requirement below is for.

---

## The gate

A task is **ADMITTED** if and only if all of these hold:

```
intended solver passes            32 / 32
shortcut solver(s) fail           32 / 32
pass rate (frontier, N=32)        0.15 <= p <= 0.40
measured on                       >= 3 checkpoints spanning capability
failure concentration             >= 0.60 on the modal labelled near-miss
artefact failure rate             <= 0.10
tolerance                         < distance to nearest labelled near-miss
                                  > spread of intended solver across seeds
lint                              no answer leakage, no method leakage,
                                  no regime disclosure in tool output
reproducibility                   identical result, 3 clean runs
wall clock                        recorded
```

Anything outside that is not "nearly there" — it is a task that does not ship
until it is fixed.

### On the two numbers you may have seen elsewhere

Older material quotes **`<= 4/16`** as the bar. That is not the same
requirement, and it is not a substitute:

- `<= 4/16` is 25%, so it sits inside the band at the top — fine as far as it
  goes.
- But it has **no floor**. It admits 0/16, which is the dead zone: no positive
  trajectory to reinforce, zero gradient, and no evidence the task is solvable
  at all.

If you are working against a 16-rollout harness, the equivalent of this gate is
**2/16 to 6/16 inclusive**, with 0/16 and 1/16 treated as *too hard* and sent
back, not passed. Use N=32 for the admission decision; 16 is for iterating.

---

## Sample size, honestly

N=16 for your own fast loop. **N=32 for the admission decision.**

Even N=32 is loose: at 10/32 the Wilson 95% interval is roughly
**[0.18, 0.49]**. That is why the gate is on *band membership plus
concentration* rather than on hitting a point estimate, and why you should
report the interval rather than a bare number.

A task at 0.30 against a public reference model is not guaranteed to be at 0.30
against an internal checkpoint mid-training run. Say which ladder you measured
on.

---

## Failure concentration — the number that matters most

Pass rate tells you a gradient exists. It does not tell you it points anywhere.

A generic hard task fails for scattered, unrelated reasons: the negative
gradient is divided across causes, the direction varies group to group, and you
get high-variance, low-efficiency learning. A task whose failures land on one
labelled near-miss turns every group into a **paired contrast between the wrong
method and the right method, on the same problem, under unambiguous reward.**

**Failure concentration** = (failing rollouts landing on the modal labelled
near-miss) / (failing rollouts, excluding artefacts).

Target **>= 0.60**. A task at p = 0.30 with concentration 0.85 is worth
substantially more per rollout than a task at p = 0.30 with failures spread
across six unrelated modes.

To compute it you have to classify every failure, which means your near-miss
table has to be real. This is why `grader/grading_guide.md` is a deliverable and
not paperwork.

### Failure taxonomy

Tag every failing rollout:

| Category | Tags | Meaning |
|---|---|---|
| Reasoning — regime | `REGIME_UNCHECKED`, `REGIME_MISIDENTIFIED`, `CONFIDENT_TOOL_TRUSTED` | Applied the default without testing it / tested and concluded wrongly / believed a confidence statistic attached to a wrong result |
| Reasoning — design | `BUDGET_MISALLOCATED`, `UNINFORMATIVE_MEASUREMENT`, `NO_VALIDATION` | Spent budget refining a wrong fit / measurements couldn't discriminate / committed with no confirmatory check |
| Answer — near-miss | `NM_<nn>`, `PARTIAL_RECOVERY` | Landed on a specific labelled near-miss / recovered a subset |
| Numeric | `TOLERANCE_MISS`, `UNIT_ERROR` | Right method, outside tolerance / right magnitude, wrong scale |
| Artefact | `FORMAT_INVALID`, `BUDGET_EXCEEDED`, `TOOL_MISUSE` | Schema failure / ran out without submitting / couldn't drive the interface |

**Artefacts are excluded from the concentration numerator and capped at 10%.**
A task where a large share of failures are format or budget-accounting errors is
calibrated on harness noise rather than reasoning, and is rejected regardless of
its pass rate. If you are over the cap, the fix is almost always in your prompt's
Output format section or in an oracle that raises where it should return.

---

## Tolerance

Two constraints, both mechanical:

```
tolerance  <  distance from the answer to the nearest labelled near-miss
tolerance  >  spread of your intended solver across noise seeds / discretisations
```

Measure both. Write both into `STATE.md`.

If no value satisfies both, the near-miss is too close to the answer to grade
and the task is rejected — that is a real outcome, not a failure of effort. Move
the near-miss, change what you ask for, or pick a different observable.

This is what converts "shortcut-resistant" from a claim into a checked property.

---

## Before you believe any number

- **Seed everything.** An unseeded RNG makes the pass rate a property of the
  weather.
- **Per-attempt state in `__init__`,** never at module level. Shared budget
  counters across attempts produce a pass rate that describes your harness.
- **Pin the image by tag or digest, immutably.** A number measured against
  `:dev` describes an image that may no longer exist.
- **Pass rates are per ProblemVersion.** Editing a problem creates a new
  version; do not compare across them.
- **Three clean runs, identical result,** before you record anything.

---

## Recording it

Put this in `STATE.md`, filled in, with job ids:

```
task: my-problem-id (version v3)
checkpoints: [weak, mid, frontier]
pass_rate: 0.03 / 0.16 / 0.31   (N=32 each)
wilson_95 (frontier): [0.180, 0.486]
concentration: 0.82  (18/22 failures -> NM-02)
artefact_rate: 0.05  (1/22 malformed submission)
wall_clock: 7.4 s/rollout (median)
verdict: ADMIT
job_ids: [...]
```

A task without this record is not finished, however good it looks.
