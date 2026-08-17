# Inverse Task — Instructions

Read this once. Then work top-to-bottom through **The 8 steps**.

Every file here ends in `.template`. Copy the folder, strip the suffix, fill it
in — see [the copy recipe](../../README.md#how-to-use-these).

**Your job:** author one inverse task — a scientific puzzle with a hidden,
provably unique answer that a competent scientist can get wrong in a specific,
predictable way. **You own the science. Claude writes the code.**

---

## Forward vs. inverse — the one thing to internalise

- **Forward** = given the cause, compute the consequence. *(Given rate constants,
  find concentration at t=10.)* This is what your tool already does.
- **Inverse** = given the consequence, recover the hidden cause, by probing the
  tool under a tight budget. *(Given concentration measurements, recover the rate
  constants.)* **This is the task.**

Your tool is the forward computation. The task wraps it in a budgeted black box
the model must query strategically to work backward.

---

## The two rules that matter most

**1. Lock the answer first. Write the prompt last.**
Everything hidden depends on the answer being fixed. If it's still moving while
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

Run the validator, then run the task on Taiga. Record measured numbers.

| Check | Requirement |
|---|---|
| Intended solver | passes, inside budget |
| Shortcut solver | **fails** |
| Pass rate | **0.15 – 0.40** (target ~0.30) at N=32, across **≥3** checkpoints |
| Failure concentration | **≥60%** of failures land on your labelled near-miss |

**If it doesn't clear this, revise — don't ship.** See *Hardening* below.

→ `STATE.md` § *Calibration*

### Step 8 — Write the prompt last, in your own words

State the setup and the budget. **Never name the trap, the method, or hint at the
fix** — not in the prompt, not in an action `description`, not in `help()` output.

→ `problem.md`

---

## The oracle contract

`oracle/setup.py` defines a class named `Oracle`. The engine builds **one
instance per attempt** and calls, in order of preference:

1. `oracle.evaluate(**params)` — a method named after the action *(recommended)*
2. `oracle.query("evaluate", **params)` — a single dispatcher, if you prefer one

Both work and you can mix them. If you use a dispatcher, its signature must
accept every parameter you declared.

### What the engine does for you — don't hand-roll these

- **`BUDGET` is enforced by the engine**, independently of any check inside your
  oracle. A call that reaches your oracle and then raises **still spends its
  call**, so a solver can't probe for free by triggering errors. A rejection that
  never reaches you — unknown action, missing or mistyped parameter — does not.
- **Only actions in `ACTIONS` are reachable.** Anything you leave out is
  unreachable, which is how you keep a debug or noisy mode private.
- **Parameters are validated** against your declarations before they reach you.

### What you must do

- **Hidden ground truth in `_`-prefixed names.** The model can't reach them and
  the validator proxy raises on access.
- **All per-attempt state in `__init__`**, never at class level.
- **Seed any randomness** (`random.Random(42)`). Taiga runs the same problem many
  times and needs it reproducible.
- **Never print.** The return value is the whole interface.

### `ACTIONS` — your probe surface

Each entry becomes a tool the model can call, named exactly as you name it.

| Field | Default | Meaning |
|---|---|---|
| `name` | required | Tool name; a valid identifier |
| `description` | generated | Shown to the model as the tool description |
| `params` | `{}` | Parameter declarations |
| `costs_budget` | `true` | Whether a call spends budget |
| `method` | action name | Oracle method to call, if it differs |

Parameter shorthands, all valid:

```python
"params": {
    "x": {"type": "integer", "description": "The input.", "required": True},
    "label": {"type": "string", "default": ""},   # a default implies optional
    "n": "integer",                               # bare type name
    "t": float,                                   # bare python type
}
```

Types: `integer`, `number`, `string`, `boolean`, `array`, `object`.

**Declare `ACTIONS` explicitly.** Without it the engine falls back to
introspecting public methods, or to a generic passthrough — and you lose both
tools named the way your prompt names them and parameter validation.

### `ANSWER_SCHEMA`

An optional class attribute describing the answer shape. The engine surfaces it
through `describe_oracle()` so the model knows what to submit. Keep it consistent
with `golden/expected.json` and the *Output format* section of `problem.md`.

### Design principles

**Return observations, not judgments.**

```python
# ❌ Grader-like — the model searches against it
def check_answer(self, guess):
    return {"correct": guess == self._SECRET}

# ✅ Instrument-like — the model must interpret it
def evaluate(self, x):
    return (self._A * x + self._B) % self.M
```

**Have multiple modes.** A multi-mode oracle forces the model to *choose* which
observation is worth spending budget on. One mode means no decision, and no
reasoning signal. Make the second a genuinely different measurement.

**Have a `help` mode that doesn't help.** It lists modes and budget. It does
**not** recommend a mode and does **not** explain what each measures in domain
terms — that's a method leak.

**Never return hidden ground truth, even derived.** If a single probe lets the
model algebraically recover a `_`-prefixed value, it isn't hidden.

### Anti-patterns

- `check_*` / `validate_*` actions → that's a grader
- A hint in an action `description` or in `help()` output
- One mode that returns everything
- Mode names that describe the physics (`check_q_factor`) → method leak
- No budget, or one loose enough for brute force
- Class-level mutable state → leaks between rollouts
- Unseeded randomness → Taiga can't reproduce the environment

---

## `golden/expected.json`

```json
{
  "answer": [11, 4],
  "tolerance": 0,
  "keys": ["a", "b"],
  "scoring": "binary"
}
```

| Field | Default | Meaning |
|---|---|---|
| `answer` | required | Number, string, array, object, or nested structure |
| `tolerance` | `0` | Absolute tolerance per numeric element |
| `keys` | — | Names for an array answer's elements. Lets the model submit `{"a": 11, "b": 4}` as well as `[11, 4]`, and labels per-element grading detail |
| `scoring` | `"binary"` | `binary` = 1.0 only if everything matches; `partial` = the fraction matching |

**Keep `scoring` binary unless you mean it.** With `partial`, a solver who
recovers one of two constants earns 0.5 — which rewards exactly the incomplete
near-miss most tasks are designed to reject.

Set `tolerance` tighter than the distance to your nearest near-miss, or the trap
answer passes too. Units go in `problem.md`, not here.

### Custom grading

For alternate accepted forms or anything structural, add `grader/grade.py` —
this **ships**:

```python
def grade(submission, expected, golden, transcript, extra_fields, session):
    """Any subset of these parameters; the engine passes what you ask for."""
    return {
        "subscores": {"slope": 1.0, "intercept": 0.0},
        "weights": {"slope": 0.5, "intercept": 0.5},
    }
```

Return Taiga's `Grade` shape, or `{"score": 0.75}`, or a bare float. Scores clamp
to `[0, 1]`. Only add this file if you need it — an unfinished `grade.py` ships
and breaks grading.

---

## Dependencies

**Standard library only** unless the published image already carries the package.
You don't build the image, so a new dependency is a request to whoever does —
flag it early rather than discovering it at run time.

---

## Hardening

When the pass rate comes in above 0.40:

**Hide the method, not the science.** Describe operationally; never name the
technique. ❌ *"Compute via ΔSCF with MOM constraints"* → ✅ *"Use a
self-consistent procedure for the excited state that preserves the chosen orbital
occupation"*.

**Hide the target.** Pick scientifically valid but non-canonical examples, so the
answer can't be recalled. ❌ formaldehyde n→π\*, 2D Ising at T_c, the repressilator
at Elowitz parameters → ✅ a donor-substituted heterocycle, a 1D chain with an
unusual coupling ratio.

**Tighten the budget.** The single most effective lever. If the correct path
comfortably fits, the model can explore instead of reason.

**Force a convention commitment.** Set the tolerance tight enough that the
default-convention answer fails, and state the convention in the prompt.

**Require everything in one submission.** No per-component feedback, `scoring`
binary. Getting one component right must not be worth partial credit.

**Sit the answer near a degeneracy**, so a careful-but-shallow solver lands on
the wrong branch.

### Reading a failed calibration

| Symptom | Likely cause |
|---|---|
| Pass rate **≥0.40** | Budget too loose, or the prompt/`help` leaks the method |
| Pass rate **0** | Your intended solver or oracle is broken — check that first |
| Failures **scattered**, not on the near-miss | The trap isn't the error models make; re-pick it (Step 4) |
| Shortcut **passes** | Tolerance too wide, or the trap isn't a real error |
| Passing runs all used **one mode** | That mode leaks the method, or the oracle is grading |
| Passing runs cited a **literature value** | Hide the target |

---

## Validate before you upload

```bash
python3 tools/validate_problem.py my-problem-id
```

It checks: the oracle loads and declares a usable surface; every declared action
actually reaches the oracle; the golden answer matches the declared shape; **the
intended solver passes within budget**; **the shortcut solver fails**; the budget
is enforced; the answer isn't printed in the prompt; no solver-visible text names
the method; and the files the image ships are present.

`FAIL` blocks shipping. `WARN` is advisory — read it and decide.

It greps solver-visible text for leakage vocabulary: **adjacent, consecutive,
shortcut, trap, naive, mistake, instead of, don't use, the trick**. A WARN there
usually means your prompt is doing the model's thinking for it.

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

Packaging is an **allowlist**, so any authoring file you invent stays out by
default rather than shipping next to the answer key.

### The form

Problem id must be lowercase kebab-case (`^[a-z0-9]+(-[a-z0-9]+)*$`) and match
the mounted folder name.

| Field | Value |
|---|---|
| **Preloaded Files** | mount `oracle/` + `golden/` at `/mnt/problems/<id>/`. **Never mount `solution/`** |
| **Upload Supporting Files** | human docs only — trap write-up, STATE, solvers. Not mounted |
| **Tell model about uploaded files** | **OFF** |
| **Grading Strategy** | **`mcp`** — not Agentic Grader, not Rubric. Agentic Grader ignores your golden answer and asks an LLM to judge |
| **Tools** | **empty**. An oracle-only task needs only `query_oracle`, `describe_oracle`, `submit_answer` |
| **Enabled Package Managers / Domain Allowlist** | empty |
| **Startup Command** | `python -u /app/mcp_server/server.py` |

Then Run Problem → read the transcript → calibrate against Step 7.

---

## Pre-submission checklist

**Answer**
- [ ] Uniqueness argued in `STATE.md` — provably one answer
- [ ] Tolerance tighter than the distance to the nearest near-miss
- [ ] `scoring` is `binary` unless you deliberately chose otherwise
- [ ] Answer shape matches `ANSWER_SCHEMA` and `problem.md`

**Oracle**
- [ ] Observations only — no judgments, no hints
- [ ] ≥2 informative modes, plus a `help` that doesn't recommend
- [ ] `ACTIONS` declared explicitly
- [ ] All per-attempt state in `__init__`; randomness seeded
- [ ] Hidden values `_`-prefixed and not derivable from any single return
- [ ] Never prints

**Code**
- [ ] `solution/main.py` passes inside budget, without reading `_`-prefixed values
- [ ] `solution/shortcut.py` is tempting, cheaper than the intended path, and lands on the named near-miss

**Prompt**
- [ ] The answer value appears nowhere in `problem.md`
- [ ] Trap not named or hinted — prompt, action descriptions, `help` output
- [ ] No method names, no canonical target, no strategy hints
- [ ] No tool-call syntax documented — the container generates it
- [ ] Every constant the solver may know is stated
- [ ] Budget stated and equal to `Oracle.BUDGET`; mode names match `ACTIONS`
- [ ] **You** wrote it, in your own words

**Ship**
- [ ] `tools/validate_problem.py` passes
- [ ] Pass rate 0.15–0.40 across ≥3 checkpoints; ≥60% on the named near-miss
- [ ] Preloaded Files contain `oracle/` + `golden/` only
- [ ] Grading Strategy `mcp`; Tools empty; uploaded-files notice OFF

---

## Do not ship if

- Pass rate is **0/32** (impossible) or **≥25/32** (too easy)
- The trap is named or hinted anywhere the solver can see, **including tool
  descriptions and diagnostics**
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
