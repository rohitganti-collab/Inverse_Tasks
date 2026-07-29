# Authoring an inverse task

You write the science: the prompt, the oracle, the intended solver, the trap.
The container figures out the rest. **No server or Docker changes are needed to
add a task** — the engine reads what your oracle declares and exposes exactly
that to the model.

This document is the engineering contract. For the *scientific* requirements
(uniqueness argument, near-miss enumeration, pass-rate calibration) see
`sample_experts_instructions.md`, which takes precedence on task design.

---

## 1. Create the folder

```bash
cp -r problems/_template problems/my-problem-id
```

`my-problem-id` must be lowercase kebab-case (`^[a-z0-9]+(-[a-z0-9]+)*$`) — Taiga
enforces that pattern on problem ids. Folders starting with `_` or `.` are
ignored by the engine, which is why `_template` is never served.

You'll have:

```
problems/my-problem-id/
├── problem.md            # the prompt the model sees            [ships, required]
├── config.yaml           # direction/domain/title metadata      [ships, optional]
├── oracle/
│   └── setup.py          # your hidden system                   [ships, required]
├── golden/
│   └── expected.json     # the graded answer                    [ships, required]
├── grader/
│   ├── grade.py          # custom scoring, if you need it       [ships, optional]
│   └── grading_guide.md  # your near-miss table                 [does NOT ship]
├── solution/
│   ├── main.py           # intended solver                      [does NOT ship]
│   └── shortcut.py       # the trap solver                      [does NOT ship]
├── BRIEF.md              # authoring notes                      [does NOT ship]
├── STATE.md              # uniqueness argument + calibration     [does NOT ship]
└── reasoning_trap.md     # the trap, written out                [does NOT ship]
```

Only the four `[ships]` entries enter the Docker image. `docker/collect_problems.py`
is an **allowlist**, so any new authoring file you invent stays out by default
rather than shipping next to the answer key.

---

## 2. Write the oracle

The only hard requirement: `oracle/setup.py` defines a class named `Oracle`.

```python
class Oracle:
    BUDGET = 6          # budgeted calls allowed; None or absent = unlimited

    _A = 11             # hidden ground truth: use a leading underscore
    _B = 4

    ACTIONS = [
        {
            "name": "evaluate",
            "description": "Return the box's output for your chosen integer x.",
            "params": {"x": {"type": "integer", "required": True}},
            "costs_budget": True,
        },
        {
            "name": "help",
            "description": "Return a general hint. It never reveals the constants.",
            "params": {"question": {"type": "string", "default": ""}},
            "costs_budget": False,
        },
    ]

    def __init__(self):
        ...             # per-attempt state goes here, not at class level

    def evaluate(self, x):
        return (self._A * x + self._B) % 97

    def help(self, question=""):
        return "..."
```

### `ACTIONS` — your probe surface

Each entry becomes a **tool the model can call**, named exactly as you name it.
Declare only what your `problem.md` tells the solver to call; anything you leave
out is unreachable, which is how you keep a debug or noisy mode private.

| Field | Default | Meaning |
| --- | --- | --- |
| `name` | required | Tool name. Must be a valid identifier and not a reserved name. |
| `description` | generated | Shown to the model as the tool description. |
| `params` | `{}` | Parameter declarations, see below. |
| `costs_budget` | `true` | Whether a call spends query budget. |
| `method` | action name | Oracle method to call, if it differs from the action name. |

Parameter declarations accept a few shorthands:

```python
"params": {
    "x": {"type": "integer", "description": "The input.", "required": True},
    "label": {"type": "string", "default": ""},   # a default implies optional
    "n": "integer",                               # bare type name
    "t": float,                                   # bare python type
}
```

Supported types: `integer`, `number`, `string`, `boolean`, `array`, `object`.

`ACTIONS` may also be a dict keyed by name:

```python
ACTIONS = {"evaluate": {"params": {"x": "integer"}}, "help": {"costs_budget": False}}
```

### How a call reaches your code

For an action named `evaluate`, the engine calls, in order of preference:

1. `oracle.evaluate(**params)` — a method of that name (recommended);
2. `oracle.query("evaluate", **params)` — a single dispatcher, if you prefer one.

Both styles work, and you can mix them. If you use a dispatcher, make sure its
signature accepts every parameter you declared — a `query(self, mode, x=None)`
cannot service an action declaring a `question` parameter. The validator checks
this for you.

### If you don't declare `ACTIONS`

Two fallbacks, in order:

1. **Introspection** — every public method becomes an action, with parameters
   read from its signature. Underscore-prefixed methods stay hidden.
2. **Generic passthrough** — an oracle with only `query()` gets the generic
   `query(action, params)` tool, and any action name is forwarded.

Declaring `ACTIONS` is strongly preferred: it's the only way the model gets
tools named the way your prompt names them, and it's the only way parameters get
validated before they reach you.

### Budget

Set `BUDGET` to an integer and the engine enforces it, independently of any
check inside your oracle:

- Actions with `costs_budget: false` never consume it.
- A call that reaches your oracle and then raises **still spends its call**, so a
  solver can't probe for free by deliberately triggering errors.
- Rejections that never reach your oracle (unknown action, missing or
  mistyped parameter) do **not** spend budget.

### Reproducibility

A fresh `Oracle()` is constructed per attempt, so `__init__` state never leaks
between runs. Seed any randomness (`random.Random(42)`) — Taiga runs the same
problem many times and needs the environment to be reproducible.

---

## 3. Write `golden/expected.json`

```json
{
  "answer": [11, 4],
  "tolerance": 0,
  "keys": ["a", "b"],
  "scoring": "binary"
}
```

| Field | Default | Meaning |
| --- | --- | --- |
| `answer` | required | The graded answer: a number, string, array, object, or nested structure. |
| `tolerance` | `0` | Absolute tolerance per numeric element. |
| `keys` | — | Names for the elements of an array answer. Lets the model submit `{"a": 11, "b": 4}` as well as `[11, 4]`, and labels the per-element grading detail. |
| `scoring` | `"binary"` | `"binary"` scores 1.0 only if everything matches; `"partial"` awards the fraction of matching elements. |

**Keep `scoring` binary unless you mean it.** With `"partial"`, a solver who
recovers one of two constants earns 0.5 — which rewards exactly the incomplete
near-miss most tasks are designed to reject. A wrong *arity* answer never earns
partial credit either way.

Set `tolerance` tighter than the distance to your nearest near-miss, or the trap
answer passes too.

### Custom grading

For partial credit, alternate accepted forms, or anything structural, add
`grader/grade.py`:

```python
def grade(submission, expected, golden, transcript, extra_fields, session):
    """Any subset of these parameters; the engine passes what you ask for."""
    return {
        "subscores": {"slope": 1.0 if ... else 0.0, "intercept": ...},
        "weights": {"slope": 0.5, "intercept": 0.5},
        "metadata": {"note": "..."},
    }
```

Return a dict in Taiga's `Grade` shape, or `{"score": 0.75}`, or a bare float.
Scores are clamped to `[0, 1]` and the weighted sum must land in that range.

---

## 4. Write the solvers

`solution/main.py` (intended) and `solution/shortcut.py` (the trap) each expose
`solve(oracle)` returning an answer in the same shape as your golden answer.

```python
def solve(oracle):
    b = oracle.query("evaluate", x=0)
    y1 = oracle.query("evaluate", x=1)
    return [(y1 - b) % oracle.M, b]
```

The validator runs both through the same budgeted path the model uses, so
`solve` receives a proxy rather than the raw oracle:

- **declared actions** are callable as methods (`oracle.evaluate(0)`) or via
  `oracle.query("evaluate", x=0)`;
- **public constants** pass through (`oracle.M`, `oracle.BUDGET`);
- **private attributes raise** — the intended solution may not read `_A` to
  "prove" it works, and calling an undeclared method is an error.

The intended solver must pass within budget. The shortcut solver must **fail** —
a trap that scores 1.0 means the task doesn't discriminate and is broken.

---

## 5. Write `problem.md` last

In your own words. State the setup and the budget. **Never name the trap, the
method, or hint at the fix** — not in the prompt, not in an action description,
not in `help()` output. The validator greps solver-visible text for
method/trap vocabulary and warns, but it can't judge your phrasing for you.

The tool names in your prompt must match your `ACTIONS` names, and the answer
you ask for must match your golden answer's shape and order.

---

## 6. Validate

```bash
python3 tools/validate_problem.py my-problem-id
python3 -m unittest discover -s tests      # engine regression suite
```

The validator checks: the oracle loads and declares a usable surface; every
declared action actually reaches the oracle; the golden answer matches the
declared shape; the intended solver passes within budget; the shortcut solver
fails; the budget is enforced; the answer isn't printed in the prompt; no
solver-visible text names the method; and the files the image needs are present.

`FAIL` blocks shipping. `WARN` is advisory — read it and decide.

---

## 7. Run it on Taiga

Build and push, then point a problem at it. See `docs/EXPERT_WORKFLOW.md` for
the Create Problem form field-by-field (matching the UI screenshots).

```json
{
  "id": "my-problem-id",
  "image": "<registry>/<org>/inverse-tasks:v1",
  "startup_command": "python -u /app/mcp_server/server.py",
  "required_tools": [],
  "scratchpad": "allowed",
  "augment_prompt_with_input_files": false
}
```

Critical settings:

- **Tools empty by default.** Oracle-only tasks need no broad model tools.
- **Grading strategy `mcp`.** Not Agentic Grader, not Rubric (Itemwise).
- **Preloaded Files** mount only `oracle/` + `golden/` at
  `/mnt/problems/<id>/`. Never mount `solution/`.
- **Tell model about uploaded files: OFF.**

The image starts MCP as root and keeps its implementation and baked problem
data owner-only. At setup it also makes writable preloaded problem trees
owner-only. Taiga's broad model tools run as uid/gid `1000:1000`, so a task may
opt into one without exposing the oracle. Files remain intact so an MCP restart
can reload the problem and grade the persisted submission.
