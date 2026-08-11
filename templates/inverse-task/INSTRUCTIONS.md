# Inverse task — instructions

Read this once, then work top-to-bottom through **The build order**.

Every file here ends in `.template`. Copy the folder into `problems/`, strip the
suffixes, and fill them in:

```bash
cp -r templates/inverse-task problems/my-problem-id
cd problems/my-problem-id
for f in $(find . -name '*.template'); do mv "$f" "${f%.template}"; done
```

`my-problem-id` must be lowercase kebab-case. It becomes the Taiga Problem ID
and the mount path.

---

## What an inverse task is

> An inverse task is **not a normal task with the answer hidden. It is a small
> investigation.** The solver can see the evidence, but not the rule that makes
> one answer right and the others wrong.

The model gets a hidden system it can only touch through an **oracle** — a
budgeted function that returns measurements. It has to design its own
measurement strategy, infer the hidden parameters, and commit. There is no
feedback loop; it finds out whether it was right only after submitting.

Your job is to build a system where **a careful solver succeeds and a naive
solver fails for a reason you predicted in advance.**

---

## The two rules that matter most

**1. Lock the answer first. Write the prompt last.**
Everything hidden depends on the answer being fixed. If the answer is still
moving while you build the oracle, the task isn't stable — stop and settle it.

**2. The oracle is an instrument, not a grader.**
It returns observations. Never judgments — no `correct`, no `accepted`, no
`close_enough`, no hints. If you catch yourself writing `check_*` or
`validate_*`, you are building a grader, and the model will search against it
instead of reasoning.

---

## The build order

Eight steps, each producing a concrete artifact. Don't skip ahead — later steps
depend on earlier ones being settled. Full detail in `docs/TASK_DESIGN.md`.

| Step | Do | Fill in |
|---|---|---|
| **1. Lock the answer** | Write the exact answer and the argument that makes it the only one *over the answer space you will state in the prompt* | `golden/expected.json`, `STATE.md` → "Why this answer is the only answer" |
| **2. Order the decisions** | What must be true first? What follows? Where does validation belong? | `STATE.md` → "Order of decisions" |
| **3. Give each candidate a job** | Every plausible wrong answer, one sentence each on why it loses. At least one must look good at first glance | `grader/grading_guide.md` → near-miss table |
| **4. Plan the wrong paths** | Which shortcut produces which wrong answer. The modal one is your trap | `STATE.md` → "Wrong paths catalogue", `reasoning_trap.md` |
| **5. Build the files** | Oracle, intended solver, shortcut solver — all three run | `oracle/setup.py`, `solution/main.py`, `solution/shortcut.py` |
| **6. Design the oracle and budget** | Multiple modes, a `help` that doesn't help, seeded domain noise, a budget brute force loses to | `oracle/setup.py`, `STATE.md` → "Budget" |
| **7. Calibrate** | The gate below, then Taiga | `STATE.md` → "Calibration" |
| **8. Write the prompt** | Last, in your own words | `problem.md` |

### Step 7 in detail — the gate

Local, first:

```bash
python3 tools/validate_problem.py my-problem-id
```

| Check | Requirement |
|---|---|
| `solution/main.py` against the oracle | **passes**, within budget |
| `solution/shortcut.py` against the oracle | **FAILS** — and for the reason you intended |
| `solution/main.py` with a different oracle noise seed | still passes; the answer must not drift with the seed |
| Nothing leaks | no answer in the prompt, no method vocabulary anywhere the solver can read |

Then Taiga, against **`docs/CALIBRATION.md`** — pass rate in 0.15–0.40 at N=32,
≥60% failure concentration, ≤10% artefacts. That document is the authority on
the bar; if the shortcut passes or the pass rate is out of band, harden using
the five strategies in `docs/TASK_DESIGN.md` and re-run.

---

## The files

| File | What it is | Ships to the container? |
|---|---|---|
| `problem.md` | The prompt. Written last, your words | **Yes** (or paste into the Taiga form) |
| `oracle/setup.py` | The hidden system | **Yes** — the whole point |
| `golden/expected.json` | The graded answer + tolerance | **Yes** |
| `config.yaml` | direction / domain / tool metadata | Yes, optional |
| `requirements.txt` | Pinned deps your oracle imports | Read by whoever builds the image |
| `grader/grading_guide.md` | Near-miss table | **No** — names the trap |
| `solution/main.py` | Intended solver | **No** |
| `solution/shortcut.py` | The trap, as code | **No** |
| `reasoning_trap.md` | The trap, in prose | **No** |
| `BRIEF.md`, `STATE.md` | Your working record | **No** |

The Docker packaging step is an allowlist, so anything else you invent stays out
by default rather than shipping next to the answer key.

---

## The oracle contract, in one place

`oracle/setup.py` defines a class named `Oracle`. Declare the probe surface in
`ACTIONS`; each entry becomes a tool named exactly as you name it. The engine
handles budget accounting, parameter validation, and dispatch.

```python
class Oracle:
    BUDGET = 12
    _TRUE_VALUE = 42        # underscore = hidden from the model AND from solvers

    ACTIONS = [
        {
            "name": "measure",
            "description": "Take a reading at the chosen setting.",
            "params": {"setting": {"type": "number", "required": True}},
            "costs_budget": True,
        },
        {"name": "help", "params": {}, "costs_budget": False},
    ]

    def __init__(self):
        self._rng = random.Random(20260811)   # per-attempt state, seeded

    def measure(self, setting): ...
    def help(self): ...
```

- A fresh `Oracle()` is built **per attempt** — per-attempt state goes in
  `__init__`, never at module level.
- Calls reach `oracle.<action>(**params)` first, then
  `oracle.query(action, **params)`. Either style works; a dispatcher's signature
  must accept every parameter any action declares.
- `costs_budget: false` actions are free. A call that reaches your oracle and
  then raises **still spends its call**, so nobody probes for free by triggering
  errors. Calls rejected before reaching you (unknown action, bad parameter)
  don't spend.
- `ANSWER_SCHEMA` is optional but recommended: it pins the shape shown to the
  model and lets the validator check your golden answer against it.

Full contract, including custom graders and the `expected.json` fields:
`docs/AUTHORING.md`.

---

## Pre-submission checklist

**Answer & grading**
- [ ] `golden/expected.json` has the answer and a justified tolerance
- [ ] Tolerance is tighter than the distance to the nearest near-miss and wider than your solver's spread across seeds
- [ ] The near-miss table has one row per plausible wrong answer, each with a reason
- [ ] Units stated in `problem.md` — the `unit` field in `expected.json` is metadata and grading ignores it

**Oracle**
- [ ] Observations only — no judgments, no hints
- [ ] ≥2 informative modes plus a `help` that doesn't recommend
- [ ] Domain-realistic noise, seeded, varying per call
- [ ] Budget enforced, and derived from the intended path
- [ ] No hidden parameter recoverable from any single return value

**Code**
- [ ] `solution/main.py` queries the oracle and never hardcodes hidden values
- [ ] `solution/main.py` passes within budget
- [ ] `solution/shortcut.py` fails, for the intended reason, and is self-contained
- [ ] `requirements.txt` pins every package the oracle imports

**Prompt**
- [ ] No method names, no canonical targets, no strategy hints
- [ ] The answer space is stated, so the answer is unique over it
- [ ] Answer format explicit — order, units, decimal places
- [ ] Any convention that matters is stated
- [ ] Tool names match your `ACTIONS` names
- [ ] `submit_answer` instruction present

**Calibration**
- [ ] `python3 tools/validate_problem.py my-problem-id` clean
- [ ] Answer stable across oracle noise seeds
- [ ] Taiga result recorded in `STATE.md` with job ids

---

## AI Use Policy

Claude may write **code**: `oracle/setup.py`, `solution/main.py`, and a
mechanical implementation of the trap *you* wrote in `solution/shortcut.py`.

Claude may **not** write — or reformat, or proofread — `problem.md`,
`reasoning_trap.md`, `grader/grading_guide.md`, or your explanation.

**You own the science.** Full version: `docs/AI_USE_POLICY.md`.

---

## Then what

`docs/TAIGA_RUNBOOK.md` — creating the problem in Taiga, field by field, and
what to do with the result.
