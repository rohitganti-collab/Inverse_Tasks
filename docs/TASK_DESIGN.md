# Designing the task

The scientific requirements. `docs/AUTHORING.md` is the engineering contract;
this document takes precedence on task *design*, and `docs/CALIBRATION.md` takes
precedence on the bar.

**Your job:** author one task — a scientific puzzle with a hidden, provably
unique answer that a competent scientist can get wrong in a specific,
predictable way.

You own the science. Claude writes the code (`docs/AI_USE_POLICY.md`).

---

## Forward vs inverse — the one thing to internalise

- **Forward** = given the cause, compute the consequence. Given rate constants,
  find the concentration at t=10. This is what your tool already does.
- **Inverse** = given the consequence, recover the hidden cause, by probing the
  tool under a tight budget. Given concentration measurements, recover the rate
  constants.

Frontier models are trained overwhelmingly on the forward direction. They are
strong at applying a known relation and weak at inferring which relation
actually governs the evidence.

**Inverse is the default.** It gives a cleaner reasoning signal, because the
model's own measurement choices are part of what's being tested. Choose forward
only when the task genuinely requires *running* a specific tool and the
difficulty lives in the mesh / solver / convergence / boundary-condition
decision — and be aware that forward tasks come back easier on the same
ensemble and usually need an extra hardening pass.

Both directions ship as **separate problems** on Taiga, with their own folders,
their own prompts, and their own calibration.

---

## The eight steps, in order

The ordering is load-bearing. The answer is locked before any code exists; the
failure modes are enumerated before the prompt is written.

### 1. Lock the answer

Fix the hidden ground truth. Write down **why no other answer is possible**.

State the answer space explicitly and prove uniqueness *over that space*. If
your observations only pin the answer up to an equivalence — a modulus, a sign,
a scale factor, a permutation of labels — then either constrain the space in
`problem.md` or grade the invariant instead. "The intended answer is obviously
the canonical one" is a convention, not an argument, and it is the most common
way a uniqueness claim fails review.

If you can't prove uniqueness, stop and pick a different setup. Do not build
around it.

→ `golden/expected.json`, `STATE.md`

### 2. Order the decisions

What must be measured or known first? What does it unlock? Where does validation
belong? This becomes the intended solution path, and the budget is sized against
it.

→ `STATE.md`

### 3. Enumerate the near-misses

Every wrong answer a **competent** colleague might produce, and why each is
tempting. At least one must look structurally correct — right shape, wrong
number.

Not typos. Not carelessness. The answers a good practitioner gets on a normal
day.

→ `grader/grading_guide.md`

### 4. Pick the trap

The single most common professional error from your list. This is what the task
actually tests. Write it out in prose before any code exists.

→ `reasoning_trap.md`, then `solution/shortcut.py`

### 5. Spec the code

A precise spec for the oracle, the intended solver, and the shortcut solver.
Claude implements from your spec; you review.

→ `oracle/setup.py`, `solution/main.py`, `solution/shortcut.py`

### 6. Set the budget

Tight enough that the shortcut is cheap and tempting, brute force is impossible,
and the correct path barely fits:

```
cost(shortcut) < BUDGET < cost(brute force)
cost(intended) <~ BUDGET
```

If a model can afford to try everything, the task is broken. A budget the
intended path uses a quarter of isn't a constraint — it's decoration, and
"experimental design under cost" isn't being tested at all.

### 7. Calibrate

Local first:

```bash
python3 tools/validate_problem.py my-problem-id
```

intended passes · shortcut fails · answer stable across noise seeds · nothing
leaks. Then Taiga, against the gate in `docs/CALIBRATION.md`. If it doesn't
clear, revise — don't ship.

### 8. Write the prompt — last, in your own words

State the setup and the budget. **Never name the trap, the method, or hint at
the fix** — not in the prompt, not in an action description, not in `help()`
output, not in any diagnostic the model can read.

Never let Claude draft it. See `docs/AI_USE_POLICY.md`.

→ `problem.md`

---

## What good looks like

| Check | Requirement |
|---|---|
| Uniqueness | Provably one answer over the stated answer space — argued in `STATE.md` |
| Pass rate | 0.15–0.40 at N=32, across ≥3 checkpoints |
| Shortcut | Fails 32/32 — proven by running it, not asserted |
| Concentration | ≥60% of failures land on your named near-miss |
| Artefacts | ≤10% of failures are format/budget errors |
| Tolerance | Tighter than the distance to the nearest near-miss; wider than your solver's own spread |
| Leakage | Prompt *and* tool outputs never name the trap or the method |
| Budget | Excludes brute force; shortcut and intended path both fit |

---

## Five ways to harden a task

When the eval says your task is too easy, apply these in order. Each catches a
specific way a model gets the right answer without doing the reasoning.

**1. Hide the method, not the science.** Catches *retrieval*. Describe
operationally; never name the method.
- ✗ "Compute via ΔSCF with MOM constraints"
- ✓ "Use a self-consistent procedure for the excited state that preserves the
  chosen orbital occupation"

**2. Hide the target.** Catches *memorisation*. Pick scientifically valid but
non-canonical examples.
- ✗ Formaldehyde n→π*, 2D Ising at T_c, the repressilator at Elowitz parameters
- ✓ A donor-substituted heterocycle, a 1D chain with an unusual coupling ratio

**3. Narrow-boolean final-answer validation.** Catches *per-component search*.
For the final-answer check only — never the observation oracle — accept or
reject with no diagnostic.

**4. Force convention commitments.** Catches *default-convention drift*. Set the
tolerance tight enough that the default-convention answer fails, and state the
convention in the prompt.
- "Standard deviation using the n−1 denominator"
- "Vertical excitation at the ground-state equilibrium geometry, not relaxed"

**5. Compositional difficulty.** Catches *per-stage checkpointing*. Require all
components in one submission, with no per-stage feedback.
- Topology **and** component values together
- All six orbital elements as a single tuple

**A sixth lever — near-degeneracies.** Put the answer near a degeneracy or edge
case, so a careful-but-shallow solver lands on the wrong branch.

### Reading it off the transcript

| What the passing attempts did | Apply |
|---|---|
| All converged on one oracle mode | Strategy 1 (the mode name leaks the method), or the oracle is acting as a grader |
| Used a canonical literature value | Strategy 2 |
| Used the wrong convention, but the tolerance accepted it | Strategy 4 |
| Solved sub-pieces sequentially with per-piece feedback | Strategy 5 |
| Never called the oracle at all | Structural leakage — the prompt alone determines the answer |

---

## Oracle design (inverse tasks)

**The oracle is an instrument, not a grader.**

1. **Returns observations, not judgments.** No `check_*`, no `validate_*`, no
   `{"correct": ...}`. If you're comparing against the answer, you've built a
   grader and the model will search against it.
2. **Multiple modes.** A multi-mode oracle forces the model to *choose* which
   observation is informative. One mode means no decision — and the decision is
   the task.
3. **A `help` mode that doesn't help.** Modes and signatures. Not
   recommendations, not what each mode measures in physics terms.
4. **Noise that defeats trivial inference.** Match it to the domain — gaussian,
   1/f, shot, systematic offsets. Clean signal makes inversion trivial; too much
   makes it impossible.

Anti-patterns the validator flags: `check_*`/`validate_*` modes; returning a
hidden parameter or anything it's recoverable from in one step; one mode that
returns everything; mode names that describe the physics (`check_q_factor`);
`hint` fields; no budget; identical noise across calls.

---

## Common ways tasks get rejected

- Pass rate 0/32 (impossible) or ≥25/32 (too easy) — outside the band either way
- The trap is named or hinted anywhere the solver can see, **including tool
  diagnostics**
- Budget loose enough that brute force or trial-and-error works
- The "shortcut" isn't actually tempting — nobody would really make that mistake
- Tolerance wide enough that the near-miss also passes
- Uniqueness holds only up to an equivalence the prompt never constrains
- Most failures are format or budget-accounting errors rather than reasoning

**When in doubt:** if a smart colleague reading only the prompt would fall into
your trap roughly a third of the time, you've got it right.
