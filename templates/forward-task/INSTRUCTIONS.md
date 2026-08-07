# Forward Task — Instructions

Read this once. Then work top-to-bottom through **The 8 steps**.

Every file here ends in `.template`. Copy the folder, strip the suffix, fill it
in. See [the copy recipe](../README.md#how-to-use-these).

> **Read this first.** This programme is built around **inverse** tasks, and
> [`../inverse-task/`](../inverse-task/) is the default. A forward task only
> works when there is a genuine method-selection decision to test. If you can't
> name that decision in one sentence, author an inverse task instead.

---

## Forward vs. inverse

- **Inverse** = given the consequence, recover the hidden cause by probing under
  a budget. **The default here.**
- **Forward** = given the cause, compute the consequence. Nothing is hidden.

A forward task therefore cannot get its difficulty from concealment. Hand a model
a fully specified system and ask for a number, and it will simply compute it.

**The difficulty has to live in the method-selection decision** — the choice that
quietly determines whether the number is right.

| Decision | How the default silently fails |
|---|---|
| Resolution / discretisation | Unconverged; the number still looks reasonable |
| Method / solver | Steady-state where the physics is unsteady |
| Stopping criterion | Residuals fall while the solution is still wrong |
| Boundary treatment | Dirichlet vs Neumann; pressure vs velocity outlet |
| Convention | Wrong sign, reference quantity, or denominator |
| Post-processing | Instantaneous value where a time-average was required |

### The three conditions a forward task must satisfy

1. **The naive default is wrong.** Not slightly imprecise — outside tolerance.
2. **It fails silently.** The naive run completes, emits no warning, and returns
   a plausible number. A loud failure is a hint; the model will notice and fix it.
3. **Brute force doesn't substitute for the decision.** If the model can sweep
   every setting and read off where results converge, it never had to decide.
   That is what the budget is for.

Fail any one of these and you don't have a task.

---

## Two rules that carry over

**1. Verify the answer independently, then write the prompt last.** You have no
hidden ground truth to check against, so verification is the whole foundation.

**2. The oracle must not judge.** `run` returns the observation and the settings
used — never converged/unconverged, never a warning that a setting is coarse,
never a residual the model can threshold into a free answer. **Recognising an
inadequate setting is the skill being tested.**

---

## The 8 steps

### Step 1 — Lock and verify the answer

Fix the answer, and verify it **against literature, an analytical limit, or an
independent setup in a different tool**. Your own converged run agreeing with
itself is not verification.

→ `golden/expected.json`, `STATE.md` § *The verified answer*

### Step 2 — Name the method decision

Pick the one decision from the table above that determines correctness. Record
the correct answer, the number the naive default produces, and the separation
between them — your tolerance has to sit inside it.

→ `STATE.md` § *The method decision*

### Step 3 — Enumerate the near-misses

Every wrong answer a **competent** colleague might report, and why each is
tempting. At least one must look structurally correct.

Then **confirm the naive path fails quietly** — run it and record what it
actually printed and returned.

→ `STATE.md` § *Near-misses*, § *Silent-failure check*, `grader/grading_guide.md`

### Step 4 — Pick the trap

The single most common professional error from your list. This is what the task
actually tests.

→ `reasoning_trap.md`, `STATE.md` § *The trap*

### Step 5 — Spec the code

Spec the system oracle, the intended solver, and the shortcut solver. **Claude
implements all three from your spec — you review, you don't write Python.**

The `run` mode must genuinely honour the settings it's given: a coarse resolution
has to return a different, wrong number, and do it without crashing.

→ `oracle/setup.py`, `solution/main.py`, `solution/shortcut.py`

### Step 6 — Set the budget

Wide enough for a deliberate convergence check, no wider. Show the arithmetic:
runs the honest path needs, runs the shortcut needs, and why a full sweep doesn't
fit. **A budget that permits a sweep removes the task.**

→ `Oracle.BUDGET`, the budget line in `problem.md`, `STATE.md` § *Budget*

### Step 7 — Calibrate

| Check | Requirement |
|---|---|
| Intended solver | passes **32/32** |
| Shortcut solver | fails **32/32** |
| Pass rate | **0.15 – 0.40** (target ~0.30) across **≥3** model checkpoints |
| Failure concentration | **≥60%** of failures land on your labelled near-miss |

**Forward tasks come out easier than inverse ones — budget for extra
hardening.** If it doesn't clear the gate, revise; don't ship.

→ `STATE.md` § *Calibration*

### Step 8 — Write the prompt last, in your own words

Disclose the system **completely**. Disclose the **convention**. Disclose
**nothing** about which settings are adequate.

State the regime factually — *"the flow is at Reynolds number 100"* — without
drawing the conclusion that follows from it — *"...so you'll need a transient
solver."* The first is the setup; the second is the answer to the question.

→ `problem.md`

---

## The oracle contract

Identical to an inverse task's — the gym doesn't special-case direction.

```python
Oracle().query(mode: str, **params) -> observation
```

One instance per attempt. Four guarantees, all machine-checked:

**1. State is per-instance** — everything mutable on `self` via `__init__`, so
budget never leaks between rollouts.
**2. Budget enforced in the oracle**, raising `RuntimeError`. `help` and `spec`
are free.
**3. Unknown modes raise `ValueError`.**
**4. Nothing is printed** — the return value is the entire interface.

A forward task has **no `_`-prefixed ground truth**. If you're adding one, you're
writing an inverse task.

### The mode layout

| Mode | Cost | Returns |
|---|---|---|
| `spec` | free | The complete system definition. Withholds nothing. |
| `run` | budgeted | The observation, plus the settings it used. No verdict. |
| `help` | free | Modes and remaining budget. |

`spec` may list the available methods and the valid resolution range. It must not
call any of them adequate, recommended, or sufficient.

### Anti-patterns

- `run` returning `converged: true/false`, a warning, or a thresholdable residual
- `spec` marking one setting as the recommended or standard choice
- A `run` whose result doesn't actually change with resolution — then there's no
  decision to get wrong
- A naive run that crashes or warns — the failure must be silent
- No budget, or one loose enough to sweep every setting
- Module- or class-level mutable state → budget leaks across rollouts

---

## Dependencies

**Standard library only** by default. If the problem needs a solver package, add
`requirements.txt` beside `oracle/setup.py`, one pinned requirement per line, and
flag it — the gym image must carry it before the problem can run.

---

## `golden/expected.json`

```json
{ "answer": [42], "tolerance": 0 }
```

**Exactly those two keys** — any extra fails verification. `tolerance` is
absolute and per numeric element. Graded element-wise and in order.

For a forward task the tolerance is squeezed from both sides: **tight enough to
exclude the naive-default answer, wide enough to admit a genuinely converged
solve** that made reasonable implementation choices. State both numbers in the
grading guide. If you can't separate them, the method decision you picked isn't
consequential enough — go back to Step 2.

Units go in `problem.md`, not here.

---

## Hardening

Forward tasks usually need this. In rough order of effectiveness:

**Tighten the budget.** The most direct lever. It's what stops a sweep standing
in for the decision.

**Tighten the tolerance.** Push it below the naive-default answer — while
confirming a correct solve still passes.

**Move the decision earlier.** A trap in post-processing is easy to spot. One in
the discretisation is not.

**Compose two decisions.** Require a resolution decision *and* a method decision,
submitted together with no intermediate feedback. Getting one right isn't enough.

**Force a convention commitment.** State a convention whose default form gives a
different number, and set the tolerance to separate them.

**De-canonicalise the setup.** A cylinder at Re=100 has a memorised answer. Shift
the geometry or regime so the number must be computed, not recalled.

**Strip the tells.** If `spec`, a parameter name, or a default value reads as
`coarse`, `draft`, or `preliminary`, the model takes it as a hint. Make the naive
configuration look deliberate.

### Reading a failed calibration

| Symptom | Likely cause |
|---|---|
| Pass rate **≥0.40** | Budget permits a sweep, or the prompt/`spec` hints the setting |
| Pass rate **0** | Your intended solver or oracle is broken — check that first |
| Failures **scattered** | The trap isn't the error models make; re-pick it (Step 4) |
| Shortcut **passes** | Tolerance too wide, or the default isn't wrong enough |
| Passing runs did **one run each** | The default is adequate — your decision isn't consequential |
| Passing runs **swept** resolutions | Tighten the budget |
| Passing runs cited a **literature value** | De-canonicalise the setup |

---

## Pre-flight check

`verify_problems.py <problem-id>` (ships with the gym packaging) checks the
mechanical contract: required files present, golden is exactly `answer` +
`tolerance`, `Oracle` imports with no third-party deps, `query("help")` is free,
every declared `ACTION` is reachable, unknown modes raise, `BUDGET` is enforced,
instances don't share budget, nothing is printed, and **the answer doesn't appear
in `problem.md`**.

It doesn't judge difficulty. Passing means well-formed, not calibrated.

---

## Pre-submission checklist

**Answer**
- [ ] Verified against literature / analytical limit / independent setup — not your own run
- [ ] `golden/expected.json` has exactly `answer` + `tolerance`
- [ ] Tolerance excludes the naive answer AND admits a correct solve — both numbers recorded
- [ ] Answer shape and order match `problem.md`

**The trap**
- [ ] The method decision is named in one sentence
- [ ] The naive default falls outside tolerance
- [ ] The naive run completes with no crash and no warning — verified by running it
- [ ] The budget excludes a full settings sweep

**Oracle**
- [ ] `run` honours its settings — a coarse setting returns a genuinely different number
- [ ] `run` returns no verdict, warning, or thresholdable residual
- [ ] `spec` discloses the system fully, and recommends nothing
- [ ] No `_`-prefixed ground truth
- [ ] State per-instance; budget enforced with `RuntimeError`; `help`/`spec` free
- [ ] Unknown modes raise `ValueError`; nothing printed
- [ ] Standard library only, or `requirements.txt` present and flagged

**Code**
- [ ] `solution/main.py` justifies its settings in a comment and demonstrates convergence
- [ ] `solution/main.py` fits inside budget
- [ ] `solution/shortcut.py` is one default run, is genuinely tempting, and lands on the named near-miss

**Prompt**
- [ ] The answer value appears nowhere in `problem.md`
- [ ] System fully specified; regime stated factually without its conclusion
- [ ] No resolution / refinement / transient hint; no method name
- [ ] Not a canonical setup with a recallable answer
- [ ] Budget stated and equal to `Oracle.BUDGET`
- [ ] Output format, tolerance, units, and any relevant convention stated
- [ ] `submit_answer(answer)` instruction present
- [ ] **You** wrote it, in your own words

**Calibration**
- [ ] Intended solver 32/32
- [ ] Shortcut 0/32 — proven by running it
- [ ] Pass rate 0.15–0.40 across ≥3 checkpoints
- [ ] ≥60% of failures on the named near-miss
- [ ] `verify_problems.py` passes

---

## Do not ship if

- You cannot name the method decision in one sentence — **it isn't a forward task**
- The naive default passes, or fails loudly
- The budget allows sweeping settings instead of choosing them
- Pass rate is 0/32 or ≥25/32
- The trap is hinted anywhere the solver can see — prompt, `spec`, `help`, or `run` output
- The answer was verified only by your own converged run

---

## AI Use Policy

Claude implements **code** from your spec — `oracle/setup.py`,
`solution/main.py`, `solution/shortcut.py`. You review it.

Claude must **not** write `problem.md`, `reasoning_trap.md`, or
`grader/grading_guide.md`. **Never let Claude draft the solver-facing prompt.**
