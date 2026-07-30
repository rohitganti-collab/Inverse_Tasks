# Inverse tasks — gym package

Problem content for inverse tasks, packaged for `core_gym`. **No Taiga hooks
here**: no `setup_problem`, no `grade_problem`, no MCP server, no Dockerfile —
`core_gym` supplies all of that. This branch is the oracle runtime surface and
nothing else.

An inverse task gives the model a black box it can only probe under a tight
budget, and asks it to recover the hidden cause that explains what it observes.

## Contents

```
problems/
  modular-black-box/
    problem.md            the task prompt
    oracle/setup.py       hidden Oracle, stable query(...) contract
    golden/expected.json  {"answer": [...], "tolerance": N}

template/                 copy to problems/<id>/ to add a task
verify_problems.py        optional pre-flight checker (stdlib only)
```

Nothing else ships: no intended solver, no shortcut/trap solver, no near-miss
table, no calibration notes. Those stay on the authoring branch.

## Dependencies

**None beyond the standard library.** `modular-black-box` imports nothing at
all, so no numpy or scipy is required today.

If a future problem needs a third-party package, add a `requirements.txt` beside
its `oracle/setup.py`:

```
problems/<problem-id>/requirements.txt
```

Keep it to one pinned requirement per line. Anything a problem lists there has to
be present in the gym image before that problem can run — treat it as a heads-up
rather than something installed at run time.

## The oracle contract

`problems/<id>/oracle/setup.py` defines a class named `Oracle`:

```python
Oracle().query(mode: str, **params) -> observation
```

Construct **one instance per attempt** and forward every probe through `query`.

| Member | Required | Meaning |
| --- | --- | --- |
| `query(mode, **params)` | yes | The probe entry point. Returns the observation. |
| `BUDGET` | recommended | Integer count of budgeted probes allowed. |
| `ACTIONS` | optional | Declares the modes: `name`, `description`, `params`, `costs_budget`. |
| public constants | optional | Values stated in `problem.md` (e.g. `M = 97`). |
| `_`-prefixed | — | Hidden ground truth. Never expose these to the model. |

Guarantees each oracle upholds, so the gym does not have to defend against them:

- **State is per-instance.** Everything mutable lives on `self` via `__init__`,
  so a fresh `Oracle()` is a fresh attempt and budget never leaks between
  rollouts.
- **Budget is enforced inside the oracle.** Exhausting it raises `RuntimeError`
  rather than returning a value, so the limit holds whether or not the caller
  also counts. `help` is free; `evaluate` is budgeted.
- **Unknown modes raise `ValueError`.** Only the modes in `ACTIONS` are
  reachable, so the probe surface cannot drift from what `problem.md` promises.
- **Nothing is printed.** The return value is the entire interface, which keeps
  a stdio transport clean.

`modular-black-box` also exposes `evaluate(x)` and `help()` as thin aliases for
`query`, sharing the same budget. Use them or ignore them; `query` is canonical.

### modular-black-box

`f(x) = (a·x + b) mod 97` with hidden `a`, `b`. Budget 6. Modes:

| Mode | Cost | Returns |
| --- | --- | --- |
| `query("evaluate", x=<int>)` | 1 | `int` — the observation |
| `query("help")` | free | `dict` — modes, `budget_remaining`, `modulus` |

Answer: `[a, b]`, exact integers, tolerance 0.

## Golden answers

```json
{ "answer": [23, 58], "tolerance": 0 }
```

Exactly those two keys. `tolerance` is absolute and per numeric element; `0`
means exact. Grade element-wise and in order — order is part of the answer.

Set `tolerance` tighter than the distance to the nearest near-miss, or the wrong
answer passes too.

## Adding a problem

```bash
cp -r template problems/my-problem-id
# edit problem.md, oracle/setup.py, golden/expected.json
python3 verify_problems.py my-problem-id
```

Problem ids are lowercase kebab-case. `template/` sits outside `problems/` on
purpose, so anything scanning `problems/*` only ever sees real tasks.

`verify_problems.py` checks the three files exist, the golden format is exactly
`answer` + `tolerance`, the oracle imports with no third-party deps, every
declared action is reachable through `query`, unknown modes raise, the budget is
enforced, two instances do not share budget, probing writes nothing to stdout,
and the answer is not printed in the prompt. It is a development aid — the gym
does not need it at run time.

## Prompt wording

`problem.md` refers to `query_oracle(mode, parameters)` and
`submit_answer(answer)`. Those names come from `core_gym`'s tool surface — if
they differ on your side, update those lines in `problem.md`, since the model
reads them literally.

The prompts deliberately state the setup and the budget and nothing about method.
An inverse task is calibrated so a competent solver fails in one specific,
predictable way; wording that hints at the intended approach destroys that.
