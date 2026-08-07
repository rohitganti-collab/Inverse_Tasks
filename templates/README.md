# Task templates

Templates for authoring tasks in this repo. Pick a direction, read its
`INSTRUCTIONS.md`, fill in the templates in the order it gives you.

| | [`inverse-task/`](inverse-task/) | [`forward-task/`](forward-task/) |
|---|---|---|
| **The model gets** | A black box it can only probe, under a budget | The complete system, disclosed |
| **It must** | Recover the hidden cause from observations | Compute the consequence correctly |
| **Difficulty lives in** | Strategic probing + inference under a tight budget | The method-selection decision |
| **Hidden ground truth** | Yes — `_`-prefixed values in the oracle | **None** |
| **Start here** | **[INSTRUCTIONS.md](inverse-task/INSTRUCTIONS.md)** | **[INSTRUCTIONS.md](forward-task/INSTRUCTIONS.md)** |

**Default to inverse.** That's what this programme is built around, and it gives
the cleaner reasoning signal. A forward task only works when there's a genuine
method-selection decision to test — if you can't name that decision in one
sentence, author it as an inverse task instead.

---

## How to use these

```bash
# 1. Copy the direction you want
cp -r templates/inverse-task my-problem-id
cd my-problem-id

# 2. Strip the .template suffix from every file
find . -name '*.template' -exec sh -c 'mv "$1" "${1%.template}"' _ {} \;

# 3. Read INSTRUCTIONS.md, then fill in from Step 1
```

Problem ids are lowercase kebab-case.

`INSTRUCTIONS.md` comes along so it's beside you while you work. It is **not part
of the task** — delete it before you hand the folder off.

---

## What a finished task looks like

```
my-problem-id/
├── problem.md            # The ONLY file the model sees — YOU write it, LAST
├── config.yaml           # direction, domain, title
├── golden/
│   └── expected.json     # exactly {"answer": ..., "tolerance": N}
├── oracle/
│   └── setup.py          # class Oracle — the probe surface
├── solution/
│   ├── main.py           # Intended solver — must pass 32/32
│   └── shortcut.py       # Trap solver — must fail 32/32
├── grader/
│   └── grading_guide.md  # Near-miss table — YOU write it
├── reasoning_trap.md     # The trap, in prose — YOU write it
├── BRIEF.md              # Your idea, for a colleague
└── STATE.md              # Your authoring record
```

**Only three of these ship to the gym**: `problem.md`, `oracle/setup.py`, and
`golden/expected.json`. The solvers, near-miss table, trap write-up and
calibration notes stay on the authoring side — but the task isn't finished
without them, because they're what prove it's calibrated.

---

## The rules that apply to both directions

**Lock the answer first. Write the prompt last.** Everything else depends on the
answer being fixed. For an inverse task you must be able to prove it's the *only*
answer; for a forward task you must verify it independently.

**The oracle is an instrument, not a grader.** It returns observations — never
accepted/rejected, never close-enough, never a hint. If you're writing `check_*`
or `validate_*`, the model will search against it instead of reasoning.

**The shortcut solver must fail.** It exists to prove your trap traps. And it
must fail *onto the named near-miss* — that's what makes the concentration check
mean anything.

**The failure must be silent.** A naive run should complete, return a plausible
number, and be wrong. If it crashes or warns, the model notices and corrects.

**Never name the trap or the method** — not in `problem.md`, not in `help` text,
not in an error message, not in any value the oracle returns.

**The budget is the difficulty.** Tight enough that brute force loses and the
correct path barely fits. If a model can afford to try everything, the task is
broken.

### The oracle contract

Both directions use the same one — the gym doesn't special-case direction:

```python
Oracle().query(mode: str, **params) -> observation
```

One instance per attempt. Four guarantees, all machine-checked by
`verify_problems.py`:

1. **State is per-instance** — mutable values on `self` via `__init__`, so budget
   never leaks between rollouts.
2. **Budget is enforced in the oracle**, raising `RuntimeError` rather than
   returning. `help` is free.
3. **Unknown modes raise `ValueError`** — the probe surface can't drift from what
   `problem.md` promises.
4. **Nothing is printed** — the return value is the whole interface.

### The calibration gate

| Check | Requirement |
|---|---|
| Intended solver | passes **32/32** |
| Shortcut solver | fails **32/32** |
| Pass rate | **0.15 – 0.40** (target ~0.30) across **≥3** checkpoints |
| Failure concentration | **≥60%** on the labelled near-miss |
| Tolerance | tighter than the distance to the nearest near-miss |

**AI Use Policy.** Claude implements code from your spec — the oracle and both
solvers — and you review it. Claude must **not** write `problem.md`,
`reasoning_trap.md`, or `grader/grading_guide.md`. **Never let Claude draft the
solver-facing prompt. You own the science.**

---

## Worked example

The task at the root of this branch (`problem.md`, `oracle/`, `solution/`, …) is
the **modular black box** — a complete, calibrated inverse task to read alongside
the templates.

One deliberate exception: its `help` mode *does* hint at the trap, because it was
built as a teaching fixture. **Don't copy that.** In a real task, `help` reveals
nothing about the method.
