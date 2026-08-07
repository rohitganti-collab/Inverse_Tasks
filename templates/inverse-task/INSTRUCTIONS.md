# Inverse Task — Instructions

Read this once. Then work top-to-bottom through **The 8 steps**.

Every file here ends in `.template`. Copy the folder, strip the suffix, fill it
in. See [the copy recipe](../README.md#how-to-use-these).

**Your job:** author one inverse task — a scientific puzzle with a hidden,
provably unique answer that a competent scientist can get wrong in a specific,
predictable way. **You own the science. Claude writes the code.**

---

## Forward vs. inverse — the one thing to internalise

- **Forward** = given the cause, compute the consequence. *(Given rate
  constants, find concentration at t=10.)* This is what your tool already does.
- **Inverse** = given the consequence, recover the hidden cause, by probing the
  tool under a tight budget. *(Given concentration measurements, recover the
  rate constants.)* **This is the task.**

Your tool is the forward computation. The task wraps it in a budgeted black box
the model must query strategically to work backward.

---

## The two rules that matter most

**1. Lock the answer first. Write the prompt last.**
Everything hidden depends on the answer being fixed. If it is still moving while
you build, stop and settle it.

**2. The oracle is an instrument, not a grader.**
It returns observations — never accepted/rejected, never close-enough, never a
hint. If you catch yourself writing `check_*` or `validate_*`, the model will
search against it instead of reasoning.

---

## The 8 steps — don't skip ahead

### Step 1 — Lock the answer

Fix the hidden ground truth. Write down **why no other answer is possible** —
your uniqueness argument. **If you can't prove uniqueness, stop and pick a
different setup.**

→ `golden/expected.json`, `STATE.md` § *Why this is the only answer*

### Step 2 — Order the decisions

What must be measured or known first? What does it unlock? Where does validation
belong? This becomes the intended solution path.

→ `STATE.md` § *Order of decisions*

### Step 3 — Enumerate the near-misses

Every wrong answer a **competent** colleague might produce, and why each is
tempting. At least one must look structurally correct — right shape, wrong
number. Record the distance to the nearest one; your tolerance goes inside it.

→ `STATE.md` § *Near-misses*, `grader/grading_guide.md`

### Step 4 — Pick the trap

The single most common professional error from your list. This is what the task
actually tests.

→ `reasoning_trap.md`, `STATE.md` § *The trap*

### Step 5 — Spec the code

Write a precise spec for three things: the hidden oracle, the intended solver,
and the shortcut solver. **Claude implements all three from your spec — you
review, you don't write Python.**

→ `oracle/setup.py`, `solution/main.py`, `solution/shortcut.py`

### Step 6 — Set the budget

Tight enough that the shortcut is cheap and tempting, brute force is impossible,
and the correct path *barely* fits. **If a model can afford to try everything,
the task is broken.** Show the arithmetic.

→ `Oracle.BUDGET`, the budget line in `problem.md`, `STATE.md` § *Budget*

### Step 7 — Calibrate

Run the harness. Record measured numbers, not intentions.

| Check | Requirement |
|---|---|
| Intended solver | passes **32/32** |
| Shortcut solver | fails **32/32** |
| Pass rate | **0.15 – 0.40** (target ~0.30) across **≥3** model checkpoints |
| Failure concentration | **≥60%** of failures land on your labelled near-miss |

**If it doesn't clear this, revise — don't ship.** See *Hardening* below.

→ `STATE.md` § *Calibration*

### Step 8 — Write the prompt last, in your own words

State the setup and the budget. **Never name the trap, the method, or hint at
the fix** — not in the prompt, not in the oracle's help text, not in any error
message the model can see.

→ `problem.md`

---

## The oracle contract

`oracle/setup.py` defines a class named `Oracle`:

```python
Oracle().query(mode: str, **params) -> observation
```

The gym constructs **one instance per attempt** and forwards every probe through
`query`.

| Member | Required | Meaning |
|---|---|---|
| `query(mode, **params)` | **yes** | Probe entry point. Returns the observation. |
| `BUDGET` | recommended | Integer count of budgeted probes allowed. |
| `ACTIONS` | optional | Declares modes: `name`, `description`, `params`, `costs_budget`. |
| public constants | optional | Values stated in `problem.md` (e.g. `M = 97`). |
| `_`-prefixed | — | Hidden ground truth. Never exposed. |

### Four guarantees your oracle must uphold

**1. State is per-instance.** Everything mutable lives on `self` via
`__init__` — never at module or class level. Otherwise budget leaks between
rollouts and a fresh `Oracle()` isn't a fresh attempt.

**2. Budget is enforced inside the oracle.** Exhausting it **raises
`RuntimeError`** rather than returning a value, so the limit holds whether or not
the caller counts. `help` is always free.

**3. Unknown modes raise `ValueError`.** Only the modes in `ACTIONS` are
reachable, so the probe surface can't drift from what `problem.md` promises.

**4. Nothing is printed.** The return value is the entire interface — a stray
`print` corrupts the stdio transport.

### Design principles

**Return observations, not judgments.**

```python
# ❌ Grader-like — the model searches against it
if mode == "check_answer":
    return {"correct": params["guess"] == self._SECRET}

# ✅ Instrument-like — the model must interpret it
if mode == "evaluate":
    return (self._A * x + self._B) % self.M
```

**Have multiple modes.** A multi-mode oracle forces the model to *choose* which
observation is worth spending budget on. One mode means no decision, and no
reasoning signal. Make the second mode a genuinely different measurement, not a
variant of the first.

**Have a `help` mode that doesn't help.** It lists modes and signatures. It does
**not** recommend a mode and does **not** explain what each measures in domain
terms — that's a method leak.

**Never return hidden ground truth, even derived.** If a single probe lets the
model algebraically recover a `_`-prefixed value, it isn't hidden.

### Anti-patterns

- `check_*`, `validate_*`, `is_correct` modes → that's a grader
- A hint in `help` text or an error message *(the sample task's `help()` does
  this deliberately as a teaching fixture — do not copy it)*
- One mode that returns everything
- Mode names that describe the physics (`check_q_factor`) → method leak
- No budget, or a budget loose enough for brute force
- Module- or class-level mutable state → budget leaks across rollouts

---

## Dependencies

**Standard library only** by default. If the problem genuinely needs a
third-party package, add `requirements.txt` beside `oracle/setup.py`, one pinned
requirement per line — and flag it, because the gym image has to carry it before
the problem can run.

---

## `golden/expected.json`

```json
{ "answer": [23, 58], "tolerance": 0 }
```

**Exactly those two keys** — any extra key fails verification. `tolerance` is
absolute and per numeric element; `0` means exact. Graded element-wise and in
order, so **order is part of the answer**.

Set `tolerance` tighter than the distance to the nearest near-miss, or the wrong
answer passes too. State units in `problem.md`, not here.

---

## Hardening

When the pass rate comes in above 0.40:

**Hide the method, not the science.** Describe operationally; never name the
technique. ❌ *"Compute via ΔSCF with MOM constraints"* → ✅ *"Use a
self-consistent procedure for the excited state that preserves the chosen
orbital occupation"*.

**Hide the target.** Pick scientifically valid but non-canonical examples, so the
answer can't be recalled. ❌ formaldehyde n→π\*, 2D Ising at T_c, the
repressilator at Elowitz parameters → ✅ a donor-substituted heterocycle, a 1D
chain with an unusual coupling ratio.

**Tighten the budget.** The single most effective lever. If the correct path
comfortably fits, the model can afford to explore instead of reason.

**Force a convention commitment.** Set the tolerance tight enough that the
default-convention answer fails, and state the convention in the prompt —
*"standard deviation using the n−1 denominator"*.

**Require everything in one submission.** No per-component feedback. Topology
*and* values together; all six orbital elements as one tuple. Getting one
component right must not be worth partial credit.

**Sit the answer near a degeneracy.** Design it so a careful-but-shallow solver
lands on the wrong branch.

### Reading a failed calibration

| Symptom | Likely cause |
|---|---|
| Pass rate **≥0.40** | Budget too loose, or the prompt/help leaks the method |
| Pass rate **0** | Your intended solver or oracle is broken — check before blaming difficulty |
| Failures **scattered**, not on the near-miss | The trap isn't the error models actually make; re-pick it (Step 4) |
| Shortcut **passes** | Tolerance too wide, or the trap isn't a real error |
| Passing runs all used **one mode** | That mode leaks the method, or the oracle is acting as a grader |
| Passing runs cited a **literature value** | Hide the target |

---

## Pre-flight check

`verify_problems.py <problem-id>` (ships with the gym packaging) checks the
mechanical contract:

- the three required files exist — `problem.md`, `oracle/setup.py`, `golden/expected.json`
- golden is exactly `answer` + `tolerance`
- `oracle/setup.py` imports with no third-party deps and defines `Oracle`
- `query("help")` works and costs no budget
- every declared `ACTION` is reachable through `query`
- an unknown mode raises rather than returning
- `BUDGET` is enforced — the call after the last one raises
- two `Oracle()` instances don't share budget
- probing writes nothing to stdout
- **the golden answer does not appear verbatim in `problem.md`**

It does **not** judge difficulty. Passing it means the task is well-formed, not
that it's calibrated — Step 7 is still the real gate.

---

## Pre-submission checklist

**Answer**
- [ ] Uniqueness argued in `STATE.md` — provably one answer
- [ ] `golden/expected.json` has exactly `answer` + `tolerance`
- [ ] Tolerance tighter than the distance to the nearest near-miss
- [ ] Answer shape and order match what `problem.md` asks for

**Oracle**
- [ ] Observations only — no judgments, no hints, no diagnostics
- [ ] ≥2 informative modes, plus a `help` that doesn't recommend
- [ ] All mutable state per-instance in `__init__`
- [ ] Budget enforced here, raising `RuntimeError`; `help` free
- [ ] Unknown modes raise `ValueError`
- [ ] Never prints
- [ ] No hidden value recoverable from any single return
- [ ] Standard library only, or `requirements.txt` present and flagged

**Code**
- [ ] `solution/main.py` queries the oracle — never reads `_`-prefixed values or hardcodes ground truth
- [ ] `solution/main.py` fits inside budget
- [ ] `solution/shortcut.py` is genuinely tempting, cheaper than the intended path, and lands on the named near-miss

**Prompt**
- [ ] The answer value appears nowhere in `problem.md`
- [ ] Trap not named or hinted — prompt, `help` text, and error messages
- [ ] No method names, no canonical target, no strategy hints
- [ ] Every constant the solver may know is stated
- [ ] Budget stated and equal to `Oracle.BUDGET`
- [ ] Output format and tolerance stated
- [ ] `submit_answer(answer)` instruction present
- [ ] **You** wrote it, in your own words

**Calibration**
- [ ] Intended solver 32/32
- [ ] Shortcut 0/32 — proven by running it, not asserted
- [ ] Pass rate 0.15–0.40 across ≥3 checkpoints
- [ ] ≥60% of failures on the named near-miss
- [ ] `verify_problems.py` passes

---

## Do not ship if

- Pass rate is **0/32** (impossible) or **≥25/32** (too easy) — outside the band
- The trap is named or hinted anywhere the solver can see, **including tool diagnostics**
- The budget is loose enough that brute force or trial-and-error works
- The shortcut isn't actually tempting — no one would really make that mistake
- The tolerance is wide enough that the near-miss also passes
- You cannot prove the answer is unique

---

## AI Use Policy

Claude implements **code** from your spec — `oracle/setup.py`,
`solution/main.py`, `solution/shortcut.py`. You review it.

Claude must **not** write `problem.md`, `reasoning_trap.md`, or
`grader/grading_guide.md`. **Never let Claude draft the solver-facing prompt.**
