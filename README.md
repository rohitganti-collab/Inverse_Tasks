# Task templates

Templates and instructions for authoring inverse and forward scientific reasoning
tasks, and submitting them to Taiga.

**This branch is templates and instructions only.** No engine, no Docker image,
no sample task — copy a folder, follow its `INSTRUCTIONS.md`, and you have a task
ready to validate and upload.

| | [`templates/inverse-task/`](templates/inverse-task/) | [`templates/forward-task/`](templates/forward-task/) |
|---|---|---|
| **The model gets** | A black box it can only probe, under a budget | The complete system, disclosed — real input files, real execution tools |
| **It must** | Recover the hidden cause from observations | Compute the consequence correctly |
| **Difficulty lives in** | Strategic probing + inference under a tight budget | The method-selection decision |
| **Hidden ground truth** | Yes — `_`-prefixed values in the oracle | **None** |
| **Reaches the system through** | `oracle/setup.py`, via `query_oracle` / `describe_oracle` | `simulation/` files, prompt-augmented, via whatever execution tool the domain tool needs |
| **Start here** | **[INSTRUCTIONS.md](templates/inverse-task/INSTRUCTIONS.md)** | **[INSTRUCTIONS.md](templates/forward-task/INSTRUCTIONS.md)** |

**Default to inverse.** That's what this programme is built around, and it gives
the cleaner reasoning signal. A forward task only works when there's a genuine
method-selection decision to test — if you can't name that decision in one
sentence, author it as an inverse task instead.

---

## How to use these

```bash
# 1. Copy the direction you want. The folder name is your problem id —
#    lowercase kebab-case.
cp -r templates/inverse-task my-problem-id
cd my-problem-id

# 2. Strip the .template suffix from every file
find . -name '*.template' -exec sh -c 'mv "$1" "${1%.template}"' _ {} \;

# 3. Read INSTRUCTIONS.md, then fill in from Step 1
```

`INSTRUCTIONS.md` comes along so it's beside you while you work. It is **not part
of the task** — delete it before you upload.

To validate and submit, drop the finished folder into the engine repo's
`problems/` directory, run `python3 tools/validate_problem.py my-problem-id`, and
follow the Taiga submission section in your `INSTRUCTIONS.md`.

---

## What a finished task looks like

The two directions ship different trees — an inverse task hides its system
behind an oracle; a forward task discloses everything, including real input
files.

**Inverse:**

```
my-problem-id/
├── problem.md            # the prompt the model sees      [ships, required]
├── config.yaml           # direction/domain/title          [ships, optional]
├── oracle/
│   └── setup.py          # the probe surface               [ships, required]
├── golden/
│   └── expected.json     # the graded answer               [ships, required]
├── grader/
│   ├── grade.py          # custom scoring, if you need it  [ships, optional]
│   └── grading_guide.md  # your near-miss table            [does NOT ship]
├── solution/
│   ├── main.py           # intended solver — must pass     [does NOT ship]
│   └── shortcut.py       # trap solver — must fail         [does NOT ship]
├── BRIEF.md              # your idea, for a colleague      [does NOT ship]
├── STATE.md              # uniqueness + calibration record [does NOT ship]
└── reasoning_trap.md     # the trap, written out           [does NOT ship]
```

**Forward — no oracle at all:**

```
my-problem-id/
├── problem.md            # the prompt the model sees      [ships, required]
├── config.yaml           # direction/domain/tools_required [ships, optional]
├── simulation/
│   └── ...               # real input files, VISIBLE       [ships, required]
├── golden/
│   └── expected.json     # the graded answer               [ships, required]
├── grader/
│   ├── grade.py          # custom scoring, if you need it  [ships, optional]
│   └── grading_guide.md  # your near-miss table            [does NOT ship]
└── solution/
    ├── main.py           # intended solver — must pass     [does NOT ship]
    └── shortcut.py       # trap solver — must fail         [does NOT ship]
```

Packaging is an **allowlist**: any authoring file you invent stays out of the
image by default rather than shipping next to the answer key. The templates don't
include `grader/grade.py` — add it only if you need custom scoring, since an
unfinished one ships and breaks grading.

---

## The rules that apply to both directions

**Lock the answer first. Write the prompt last.** For an inverse task you must be
able to prove it's the *only* answer; for a forward task you must verify it
independently.

**The shortcut solver must fail.** It exists to prove your trap traps. It must
fail *onto the named near-miss* — that's what makes the concentration check
mean anything.

**The failure must be silent.** A naive run should complete, return a plausible
number, and be wrong. If it crashes or warns, the model notices and corrects.

**Never name the trap or the method** — not in `problem.md`, not in anything
the model can see.

### Inverse tasks: the oracle contract

`oracle/setup.py` defines a class named `Oracle`; the engine builds one instance
per attempt and calls `oracle.<action>(**params)`, falling back to
`oracle.query(action, **params)` if you prefer a dispatcher.

The engine enforces `BUDGET`, makes only the actions in `ACTIONS` reachable, and
validates parameters before they reach you. You put hidden values in `_`-prefixed
names, keep all per-attempt state in `__init__`, seed any randomness, and never
print. **The oracle is an instrument, not a grader** — it returns observations,
never accepted/rejected, never close-enough, never a hint. **The budget is the
difficulty**: tight enough that brute force loses and the correct path barely
fits. Don't document the tool call syntax in your prompt — the container appends
a calling guide generated from your `ACTIONS`.

### Forward tasks: no oracle, real files and tools instead

There's no probe surface, because there's nothing to probe. `simulation/` ships
as Preloaded Files with the "Tell model about uploaded files" setting turned
**ON** (`augment_prompt_with_input_files: true`) — the model sees those files
directly. It also needs real execution tools enabled on the Taiga form (not the
empty Tools list an oracle-only task gets), since it has to actually run the
domain tool itself. `submit_answer` is the one piece of the model-facing
contract both directions share.

`tools/validate_problem.py` currently only validates the oracle contract, so a
forward task's calibration (below) has to be run and recorded by hand — see
`templates/forward-task/INSTRUCTIONS.md` for the known gap.

### The calibration gate

| Check | Requirement |
|---|---|
| Intended solver | passes (inside budget, for inverse tasks) |
| Shortcut solver | **fails** |
| Pass rate | **0.15 – 0.40** (target ~0.30) at N=32, across **≥3** checkpoints |
| Failure concentration | **≥60%** on the labelled near-miss |
| Tolerance | tighter than the distance to the nearest near-miss |

**AI Use Policy.** Claude implements code from your spec — the oracle (or
`simulation/` scaffolding) and both solvers — and you review it. Claude must
**not** write `problem.md`, `reasoning_trap.md`, or `grader/grading_guide.md`.
**Never let Claude draft the solver-facing prompt. You own the science.**
