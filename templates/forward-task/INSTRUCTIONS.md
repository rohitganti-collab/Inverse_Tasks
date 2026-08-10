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

- **Inverse** = given the consequence, recover the hidden cause by probing a
  hidden oracle under a budget. **The default here.**
- **Forward** = given the cause, compute the consequence. Nothing is hidden,
  and there is **no oracle** — see below.

A forward task can't get its difficulty from concealment. Hand a model a fully
specified system and ask for a number, and it will simply compute it.

**The difficulty has to live in the method-selection decision** — the choice that
quietly determines whether the number is right.

| Decision | How the default silently fails |
|---|---|
| Mesh / discretisation | Unconverged; the number still looks reasonable |
| Method / solver | Steady-state where the physics is unsteady |
| Stopping criterion | Residuals fall while the solution is still wrong |
| Boundary treatment | Dirichlet vs Neumann; pressure vs velocity outlet |
| Convention | Wrong sign, reference quantity, or denominator |
| Post-processing | Instantaneous value where a time-average was required |

### Why there is no oracle here

An inverse task's oracle exists to hide something. A forward task hides
nothing, so it has no oracle, no `_`-prefixed ground truth, and no
`query_oracle` / `describe_oracle` tools.

Instead, the model gets:

- **Real input files.** Whatever your domain tool needs — OpenFOAM case
  folders, FEniCS meshes, ngspice netlists — go in `simulation/`. Those files
  ship as Preloaded Files with **"Tell model about uploaded files" turned ON**
  (`augment_prompt_with_input_files: true`), so the container appends their
  contents to the model's prompt directly. There is no probe surface to design
  because there is nothing to probe.
- **Real execution tools.** The model has to actually run the domain tool, so
  the Taiga form's Customize Tools section needs whatever that requires (a
  shell, a specific runner) enabled — unlike an oracle-only inverse task, which
  ships with Tools empty. Record what you need in `config.yaml`'s
  `tools_required`.
- **The same `submit_answer` tool** an inverse task uses. That part of the
  contract doesn't change.

⚠️ **Known gap:** `tools/validate_problem.py` and the oracle-run proxy it uses
for local validation are built for the inverse-task contract only — they
require `oracle/setup.py` and won't run against a forward task. Steps 5–7 below
tell you how to verify a forward task by hand until engine support for a
no-oracle path exists. Don't skip the verification just because the automated
gate doesn't cover it yet.

### The three conditions a forward task must satisfy

1. **The naive default is wrong.** Not slightly imprecise — outside tolerance.
2. **It fails silently.** The naive run completes, emits no warning, and returns a
   plausible number. A loud failure is a hint.
3. **Brute force doesn't substitute for the decision.** If the model can sweep
   every setting and read off where results converge, it never had to decide.

Fail any one and you don't have a task.

---

## Two rules that carry over

**1. Verify the answer independently, then write the prompt last.** You have no
hidden ground truth to check against, so verification is the whole foundation.

**2. Nothing you ship may judge.** Neither `simulation/`'s files nor
`problem.md` may call any setting adequate, recommended, standard, or
sufficient. **Recognising an inadequate setting is the skill being tested.**

---

## The 8 steps

### Step 1 — Lock and verify the answer

Fix the answer and verify it **against literature, an analytical limit, or an
independent setup in a different tool**. Your own converged run agreeing with
itself is not verification.

→ `golden/expected.json`

### Step 2 — Name the method decision

Pick the one decision that determines correctness. Record the correct answer, the
number the naive default produces, and the separation — your tolerance sits inside
it.

### Step 3 — Enumerate the near-misses

Every wrong answer a **competent** colleague might report, and why each is
tempting. Then **confirm the naive path fails quietly** — run it and record what
it actually printed and returned.

→ `grader/grading_guide.md`

### Step 4 — Pick the trap

The single most common professional error from your list. This is what
`solution/shortcut.py` implements.

### Step 5 — Build the simulation inputs, then spec the code

Put the tool's input files in `simulation/`. **These files are visible to the
model** — set their defaults so the naive run is the wrong run (a default mesh
that's too coarse, a steady-state solver configuration where the physics is
transient). The trap is baked into the inputs, not hidden behind a probe.

Then spec the intended solver and the shortcut. **Claude implements both from
your spec — you review, you don't write Python.**

`run_case` (or however you invoke your tool) must genuinely honour its
settings: a coarse setting has to return a different, wrong number, without
crashing.

→ `simulation/`, `solution/main.py`, `solution/shortcut.py`

### Step 6 — Declare the tools the model needs

There's no budget to set — a forward task has no oracle to meter. Instead,
list every execution tool the model will need to actually run the domain tool
(a shell, a specific runner) so whoever fills in the Taiga form's Customize
Tools section knows what to enable.

→ `config.yaml`'s `tools_required`

### Step 7 — Calibrate by hand

| Check | Requirement |
|---|---|
| Intended solver (`python3 solution/main.py`) | passes, matches golden answer |
| Shortcut solver (`python3 solution/shortcut.py`) | **fails** |
| Pass rate | **0.15 – 0.40** (target ~0.30) at N=32, across **≥3** checkpoints |
| Failure concentration | **≥60%** on your labelled near-miss |

Run both solvers manually and record the numbers — there is no
`tools/validate_problem.py` support for this yet (see the gap noted above).

**Forward tasks come out easier than inverse ones — budget for extra hardening.**

### Step 8 — Write the prompt last, in your own words

Disclose the system **completely**, including every file in `simulation/`.
Disclose the **convention**. Disclose **nothing** about which settings are
adequate.

State the regime factually — *"the flow is at Reynolds number 100"* — without
drawing the conclusion — *"...so you'll need a transient solver."* The first is
the setup; the second is the answer to the question.

→ `problem.md`

---

## The model-facing contract

- **No `query_oracle` / `describe_oracle`.** There's nothing hidden to probe.
- **`submit_answer(answer)`** is the same tool an inverse task uses.
- **Preloaded Files** mount `simulation/` + `golden/`, with
  `augment_prompt_with_input_files: true` so the model sees the input files
  without needing a file-reading tool.
- **Customize Tools is non-empty**, unlike an oracle-only inverse task — the
  model must actually execute the domain tool, so enable whatever running it
  requires.

### Anti-patterns

- A file in `simulation/`, a comment, or a filename that reads `coarse`,
  `draft`, or `preliminary` — the model takes it as a hint
- `problem.md` marking one setting as recommended or standard
- A run whose result doesn't actually change with the setting — no decision to
  get wrong
- A naive run that crashes or warns — the failure must be silent
- Leaving Customize Tools too broad — give the model only what running the
  domain tool actually needs

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
solution** that made reasonable implementation choices. State both numbers in the
grading guide. If you can't separate them, the decision you picked isn't
consequential enough — go back to Step 2.

Units go in `problem.md`, not here. For structural scoring, add `grader/grade.py`
(it **ships**) — but only if you need it; an unfinished one breaks grading.

---

## Dependencies

Whatever your domain tool needs must already be in the published image, or be
requested from whoever builds it — a forward task has no upload path for new
packages. Note what you need in `config.yaml`'s `tools_required`.

---

## Hardening

Forward tasks usually need this. In rough order of effectiveness:

**Tighten the tolerance.** Push it below the naive-default answer, while
confirming a correct solve still passes.

**Move the decision earlier.** A trap in post-processing is easy to spot. One in
the discretisation is not.

**Compose two decisions.** A mesh decision *and* a method decision, submitted
together with no intermediate feedback, `scoring` binary.

**Force a convention commitment.** State a convention whose default form gives a
different number, and set the tolerance to separate them.

**De-canonicalise the setup.** A cylinder at Re=100 has a memorised answer. Shift
the geometry or regime so the number must be computed, not recalled.

**Strip the tells.** If a filename, comment, or config key in `simulation/`
reads as `coarse`, `draft`, or `preliminary`, the model takes it as a hint.

### Reading a failed calibration

| Symptom | Likely cause |
|---|---|
| Pass rate **≥0.40** | The prompt or `simulation/` hints the setting |
| Pass rate **0** | Your intended solver is broken — check that first |
| Failures **scattered** | The trap isn't the error models make; re-pick it (Step 4) |
| Shortcut **passes** | Tolerance too wide, or the default isn't wrong enough |
| Passing runs did **one run each** | The default is adequate — your decision isn't consequential |
| Passing runs cited a **literature value** | De-canonicalise the setup |

---

## Submitting to Taiga

You never build the Docker image. You write the science files, upload the runtime
subset, and fill in the Create Problem form.

### What ships

| File | Ships? |
|---|---|
| `problem.md` | **yes** — or paste it into the Task Prompt field instead |
| `config.yaml` | yes, optional |
| `simulation/` | **yes, required** |
| `golden/expected.json` | **yes, required** |
| `grader/grade.py` | yes, if present |
| `grader/grading_guide.md` | **no** — names the trap |
| `solution/main.py`, `solution/shortcut.py` | **no** |
| `INSTRUCTIONS.md` | **no** |

Packaging is an **allowlist** — anything you invent stays out by default.

### The form

Problem id must be lowercase kebab-case (`^[a-z0-9]+(-[a-z0-9]+)*$`) and match the
mounted folder name.

| Field | Value |
| --- | --- |
| **Preloaded Files** | mount `simulation/` + `golden/` at `/mnt/problems/<id>/` |
| **Upload Supporting Files** | human docs only. Not mounted |
| **Tell model about uploaded files** | **ON** (`augment_prompt_with_input_files: true`) — the opposite of an inverse task |
| **Grading Strategy** | **`mcp`** — not Agentic Grader, not Rubric |
| **Customize Tools** | whatever running the domain tool requires — see `config.yaml`'s `tools_required`. Not empty, unlike an oracle-only task |
| **Enabled Package Managers / Domain Allowlist** | only what the domain tool genuinely needs |
| **Startup Command** | `python -u /app/mcp_server/server.py` |

---

## Pre-submission checklist

**Answer**
- [ ] Verified against literature / analytical limit / independent setup — not your own run
- [ ] Tolerance excludes the naive answer AND admits a correct solve — both numbers recorded
- [ ] `scoring` is `binary` unless you deliberately chose otherwise
- [ ] Answer shape matches `problem.md`

**The trap**
- [ ] The method decision is named in one sentence
- [ ] The naive default falls outside tolerance
- [ ] The naive run completes with no crash and no warning — verified by running it
- [ ] The setting the trap depends on is baked into `simulation/`'s defaults, not hinted in `problem.md`

**Inputs**
- [ ] Every file the task needs is in `simulation/`
- [ ] No filename, comment, or config key gives the trap away
- [ ] `run_case` (or your tool invocation) honours its settings — a coarse setting returns a genuinely different number

**Code**
- [ ] `solution/main.py` justifies its settings and demonstrates convergence, run manually
- [ ] `solution/shortcut.py` is one default run, tempting, and lands on the named near-miss, run manually

**Prompt**
- [ ] The answer value appears nowhere in `problem.md`
- [ ] System and every input file fully specified; regime stated factually without its conclusion
- [ ] No mesh / refinement / transient hint; no method name
- [ ] Tolerance, units, and any relevant convention stated
- [ ] **You** wrote it, in your own words

**Ship**
- [ ] Both solvers run and verified by hand (no automated validator covers forward tasks yet)
- [ ] Pass rate 0.15–0.40 across ≥3 checkpoints; ≥60% on the named near-miss
- [ ] Preloaded Files contain `simulation/` + `golden/` only
- [ ] Grading Strategy `mcp`; Tools set to what the domain tool needs; uploaded-files notice **ON**

---

## Do not ship if

- You cannot name the method decision in one sentence — **it isn't a forward task**
- The naive default passes, or fails loudly
- Pass rate is 0/32 or ≥25/32
- The trap is hinted anywhere the solver can see — `problem.md`, filenames, or config in `simulation/`
- The answer was verified only by your own converged run

---

## AI Use Policy

Claude implements **code** from your spec — `solution/main.py`,
`solution/shortcut.py`, and mechanical scaffolding for `simulation/`. You review it.

Claude must **not** write `problem.md` or `grader/grading_guide.md`. **Never let
Claude draft the solver-facing prompt.**
