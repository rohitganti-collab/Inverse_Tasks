# Forward Task — Instructions

Read this once. Then work top-to-bottom through **The 8 steps**.

Every file here ends in `.template`. Copy the folder, strip the suffix, fill it
in — see [the copy recipe](../../README.md#how-to-use-these).

> **Read this first.** This programme is built around **inverse** tasks, and
> [`../inverse-task/`](../inverse-task/) is the default. A forward task only
> works when there is a genuine method-selection decision to test. If you can't
> name that decision in one sentence, author an inverse task instead.

---

## Forward vs. inverse

- **Inverse** = given the consequence, recover the hidden cause by probing under
  a budget. **The default here.**
- **Forward** = given the cause, compute the consequence. Nothing is hidden.

A forward task can't get its difficulty from concealment. Hand a model a fully
specified system and ask for a number, and it will simply compute it.

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

### Why it still has an oracle

Nothing is hidden, yet the system is still reached through `oracle/setup.py`. That
isn't ceremony: on Taiga the model's **only** tools are `query_oracle`,
`describe_oracle`, and `submit_answer`. There is no file-serving tool, and the
problem tree is made owner-only while model-side tools run as uid 1000. The probe
surface is the only channel that exists, so a forward task discloses its system
*through* it — `spec` returns the full definition, `run` executes the computation.

### The three conditions a forward task must satisfy

1. **The naive default is wrong.** Not slightly imprecise — outside tolerance.
2. **It fails silently.** The naive run completes, emits no warning, and returns a
   plausible number. A loud failure is a hint.
3. **Brute force doesn't substitute for the decision.** If the model can sweep
   every setting and read off where results converge, it never had to decide.
   That's what the budget is for.

Fail any one and you don't have a task.

---

## Two rules that carry over

**1. Verify the answer independently, then write the prompt last.** You have no
hidden ground truth to check against, so verification is the whole foundation.

**2. The oracle must not judge.** `run` returns the observation and the settings
used — never converged/unconverged, never a warning that a setting is coarse,
never a residual the model can threshold. **Recognising an inadequate setting is
the skill being tested.**

---

## The 8 steps

### Step 1 — Lock and verify the answer

Fix the answer and verify it **against literature, an analytical limit, or an
independent setup in a different tool**. Your own converged run agreeing with
itself is not verification.

→ `golden/expected.json`, `STATE.md` § *The verified answer*

### Step 2 — Name the method decision

Pick the one decision that determines correctness. Record the correct answer, the
number the naive default produces, and the separation — your tolerance sits inside
it.

→ `STATE.md` § *The method decision*

### Step 3 — Enumerate the near-misses

Every wrong answer a **competent** colleague might report, and why each is
tempting. Then **confirm the naive path fails quietly** — run it and record what
it actually printed and returned.

→ `STATE.md` § *Near-misses*, § *Silent-failure check*, `grader/grading_guide.md`

### Step 4 — Pick the trap

The single most common professional error from your list.

→ `reasoning_trap.md`, `STATE.md` § *The trap*

### Step 5 — Spec the code

Spec the system oracle, the intended solver, and the shortcut. **Claude implements
all three from your spec — you review, you don't write Python.**

`run` must genuinely honour its settings: a coarse resolution has to return a
different, wrong number, without crashing.

→ `oracle/setup.py`, `solution/main.py`, `solution/shortcut.py`

### Step 6 — Set the budget

Wide enough for a deliberate convergence check, no wider. Show the arithmetic.
**A budget that permits a sweep removes the task.**

→ `Oracle.BUDGET`, the budget line in `problem.md`, `STATE.md` § *Budget*

### Step 7 — Calibrate

| Check | Requirement |
|---|---|
| Intended solver | passes, inside budget |
| Shortcut solver | **fails** |
| Pass rate | **0.15 – 0.40** (target ~0.30) at N=32, across **≥3** checkpoints |
| Failure concentration | **≥60%** on your labelled near-miss |

**Forward tasks come out easier than inverse ones — budget for extra hardening.**

→ `STATE.md` § *Calibration*

### Step 8 — Write the prompt last, in your own words

Disclose the system **completely**. Disclose the **convention**. Disclose
**nothing** about which settings are adequate.

State the regime factually — *"the flow is at Reynolds number 100"* — without
drawing the conclusion — *"...so you'll need a transient solver."* The first is
the setup; the second is the answer to the question.

→ `problem.md`

---

## The oracle contract

Identical to an inverse task's — the engine doesn't special-case direction. It
builds one `Oracle()` per attempt and calls `oracle.<action>(**params)`.

### What the engine does for you

- **`BUDGET` is enforced by the engine.** A call that reaches your oracle and then
  raises still spends its call; a rejection that never reaches you doesn't.
- **Only actions in `ACTIONS` are reachable.**
- **Parameters are validated** before they reach you.

### What you must do

- **All per-attempt state in `__init__`**, never at class level.
- **Seed any randomness** (`random.Random(42)`) — Taiga needs reproducibility.
- **Never print.**
- A forward task has **no `_`-prefixed ground truth**. If you're adding one,
  you're writing an inverse task.

### The mode layout

| Mode | Cost | Returns |
|---|---|---|
| `spec` | free | The complete system definition. Withholds nothing |
| `run` | budgeted | The observation, plus the settings used. **No verdict** |
| `help` | free | Modes and remaining budget |

`spec` may list available methods and the valid resolution range. It must not
call any of them adequate, recommended, standard, or sufficient.

Declare `ACTIONS` explicitly, and set `ANSWER_SCHEMA` so `describe_oracle()` tells
the model what shape to submit. Parameter shorthands (`"n": "integer"`, a
`default` implying optional) work the same as for inverse tasks.

### Anti-patterns

- `run` returning `converged: true/false`, a warning, or a thresholdable residual
- `spec` marking one setting as recommended or standard
- A `run` whose result doesn't actually change with resolution — no decision to
  get wrong
- A naive run that crashes or warns — the failure must be silent
- No budget, or one loose enough to sweep every setting
- Class-level mutable state, or unseeded randomness

---

## `golden/expected.json`

```json
{
  "answer": [42.0],
  "tolerance": 0.01,
  "keys": ["quantity"],
  "scoring": "binary"
}
```

`answer` is required; `tolerance` is absolute per numeric element; `keys` names an
array answer's elements; `scoring` is `binary` (all-or-nothing) or `partial` (the
fraction matching). **Keep it binary** — partial credit rewards the incomplete
near-miss.

For a forward task the tolerance is squeezed from both sides: **tight enough to
exclude the naive-default answer, wide enough to admit a genuinely converged
solve** that made reasonable implementation choices. State both numbers in the
grading guide. If you can't separate them, the decision you picked isn't
consequential enough — go back to Step 2.

Units go in `problem.md`, not here. For structural scoring, add `grader/grade.py`
(it **ships**) — but only if you need it; an unfinished one breaks grading.

---

## Dependencies

**Standard library only** unless the published image already carries the package.
You don't build the image, so a new dependency is a request to whoever does.

---

## Hardening

Forward tasks usually need this. In rough order of effectiveness:

**Tighten the budget.** The most direct lever — it's what stops a sweep standing
in for the decision.

**Tighten the tolerance.** Push it below the naive-default answer, while
confirming a correct solve still passes.

**Move the decision earlier.** A trap in post-processing is easy to spot. One in
the discretisation is not.

**Compose two decisions.** A resolution decision *and* a method decision,
submitted together with no intermediate feedback, `scoring` binary.

**Force a convention commitment.** State a convention whose default form gives a
different number, and set the tolerance to separate them.

**De-canonicalise the setup.** A cylinder at Re=100 has a memorised answer. Shift
the geometry or regime so the number must be computed, not recalled.

**Strip the tells.** If `spec`, a parameter name, or a default reads as `coarse`,
`draft`, or `preliminary`, the model takes it as a hint.

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

## Validate before you upload

```bash
python3 tools/validate_problem.py my-problem-id
```

It checks the oracle loads and declares a usable surface, every declared action
reaches the oracle, the golden answer matches the declared shape, **the intended
solver passes within budget**, **the shortcut fails**, the budget is enforced, the
answer isn't printed in the prompt, no solver-visible text names the method, and
the shipped files are present.

`FAIL` blocks shipping. `WARN` is advisory. Its leakage vocabulary — **adjacent,
consecutive, shortcut, trap, naive, mistake, instead of, don't use, the trick** —
usually flags a prompt doing the model's thinking for it.

---

## Submitting to Taiga

You never build the Docker image. You write the science files, upload the runtime
subset, and fill in the Create Problem form.

### What ships

| File | Ships? |
|---|---|
| `problem.md` | **yes** — or paste it into the Task Prompt field instead |
| `config.yaml` | yes, optional |
| `oracle/setup.py` | **yes, required** |
| `golden/expected.json` | **yes, required** |
| `grader/grade.py` | yes, if present |
| `grader/grading_guide.md` | **no** — names the trap |
| `solution/main.py`, `solution/shortcut.py` | **no** |
| `BRIEF.md`, `STATE.md`, `reasoning_trap.md` | **no** |

Packaging is an **allowlist** — anything you invent stays out by default.

### The form

Problem id must be lowercase kebab-case (`^[a-z0-9]+(-[a-z0-9]+)*$`) and match the
mounted folder name.

| Field | Value |
|---|---|
| **Preloaded Files** | mount `oracle/` + `golden/` at `/mnt/problems/<id>/`. **Never mount `solution/`** |
| **Upload Supporting Files** | human docs only. Not mounted |
| **Tell model about uploaded files** | **OFF** |
| **Grading Strategy** | **`mcp`** — not Agentic Grader, not Rubric |
| **Tools** | **empty** — the task needs only the MCP tools the image publishes |
| **Enabled Package Managers / Domain Allowlist** | empty |
| **Startup Command** | `python -u /app/mcp_server/server.py` |

---

## Pre-submission checklist

**Answer**
- [ ] Verified against literature / analytical limit / independent setup — not your own run
- [ ] Tolerance excludes the naive answer AND admits a correct solve — both numbers recorded
- [ ] `scoring` is `binary` unless you deliberately chose otherwise
- [ ] Answer shape matches `ANSWER_SCHEMA` and `problem.md`

**The trap**
- [ ] The method decision is named in one sentence
- [ ] The naive default falls outside tolerance
- [ ] The naive run completes with no crash and no warning — verified by running it
- [ ] The budget excludes a full settings sweep

**Oracle**
- [ ] `run` honours its settings — a coarse setting returns a genuinely different number
- [ ] `run` returns no verdict, warning, or thresholdable residual
- [ ] `spec` discloses the system fully and recommends nothing
- [ ] No `_`-prefixed ground truth
- [ ] `ACTIONS` declared; state per-instance; randomness seeded; never prints

**Code**
- [ ] `solution/main.py` justifies its settings and demonstrates convergence, inside budget
- [ ] `solution/shortcut.py` is one default run, tempting, and lands on the named near-miss

**Prompt**
- [ ] The answer value appears nowhere in `problem.md`
- [ ] System fully specified; regime stated factually without its conclusion
- [ ] No resolution / refinement / transient hint; no method name
- [ ] No tool-call syntax documented — the container generates it
- [ ] Budget stated and equal to `Oracle.BUDGET`; mode names match `ACTIONS`
- [ ] Tolerance, units, and any relevant convention stated
- [ ] **You** wrote it, in your own words

**Ship**
- [ ] `tools/validate_problem.py` passes
- [ ] Pass rate 0.15–0.40 across ≥3 checkpoints; ≥60% on the named near-miss
- [ ] Preloaded Files contain `oracle/` + `golden/` only
- [ ] Grading Strategy `mcp`; Tools empty; uploaded-files notice OFF

---

## Do not ship if

- You cannot name the method decision in one sentence — **it isn't a forward task**
- The naive default passes, or fails loudly
- The budget allows sweeping settings instead of choosing them
- Pass rate is 0/32 or ≥25/32
- The trap is hinted anywhere the solver can see — prompt, `spec`, `help`, or `run`
- The answer was verified only by your own converged run

---

## AI Use Policy

Claude implements **code** from your spec — `oracle/setup.py`,
`solution/main.py`, `solution/shortcut.py`. You review it.

Claude must **not** write `problem.md`, `reasoning_trap.md`, or
`grader/grading_guide.md`. **Never let Claude draft the solver-facing prompt.**
