# Inverse_Tasks

Authoring templates and a worked sample for inverse (and forward) scientific
reasoning tasks.

## Authoring a task — start here

**[`templates/`](templates/)** — copy a direction, follow its `INSTRUCTIONS.md`.

- **[`templates/inverse-task/`](templates/inverse-task/)** — the default. A black
  box the model probes under a budget to recover a hidden cause.
- **[`templates/forward-task/`](templates/forward-task/)** — the system is fully
  disclosed; difficulty is in the method-selection decision.

[`sample_experts_instructions.md`](sample_experts_instructions.md) is the
programme-level brief: the 8 steps and the gate, in short form. The templates
expand it into files you fill in.

## The worked sample

The task at the root of this branch is **the modular black box** — a complete,
calibrated inverse task to read alongside the templates:

```
problem.md              the prompt the model sees
config.yaml             direction, domain, title
oracle/setup.py         hidden Oracle — f(x) = (a·x + b) mod 97, budget 6
golden/expected.json    {"answer": [23, 58], "tolerance": 0}
solution/main.py        intended solver — recovers (a, b) from adjacent points
solution/shortcut.py    trap solver — fits a line, ignores the modular wrap
grader/grading_guide.md near-miss table
reasoning_trap.md       the trap, in prose
BRIEF.md  STATE.md      the authoring record
```

> One deliberate exception: the sample's `help` mode hints at the trap, because
> it is a teaching fixture. **Don't copy that** — in a real task, `help` reveals
> nothing about the method.

## The calibration gate

| Check | Requirement |
|---|---|
| Intended solver | passes 32/32 |
| Shortcut solver | fails 32/32 |
| Pass rate | 0.15 – 0.40 (target ~0.30) across ≥3 checkpoints |
| Failure concentration | ≥60% on the labelled near-miss |
| Tolerance | tighter than the distance to the nearest near-miss |

**You own the science. Claude writes the code — never the solver-facing prompt.**
