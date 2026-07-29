# Finishing an inverse task: the expert workflow

You never build a Docker image. The image is built once and published; you write
**four files**, upload them, and fill in five fields on Taiga's Create Problem
form.

```
1. write        problem.md, oracle/setup.py, golden/expected.json, solution/main.py
2. validate     python3 tools/validate_problem.py my-problem-id
3. upload       the folder as Preloaded Files → /mnt/problems/my-problem-id/
4. configure    5 fields on the Create Problem form (step 4 below)
5. run          Run Problem → check the transcript → calibrate
```

The container reads your oracle at run time and publishes exactly the operations
it declares. Nothing is hardcoded to any one task, so **adding a task requires no
rebuild and no engineering support**.

---

## 1. What you write

Copy the template and edit four files:

```bash
cp -r problems/_template problems/my-problem-id
```

### `oracle/setup.py` — the hidden system *(required)*

A class named `Oracle`. Put the ground truth in underscore-prefixed attributes,
declare the operations the solver may perform, and set the query budget.

```python
class Oracle:
    BUDGET = 6                     # budgeted calls the solver gets
    _A, _B = 11, 4                 # hidden: underscore = unreachable

    ACTIONS = [
        {"name": "evaluate",
         "description": "Return the box's output for your chosen integer x.",
         "params": {"x": {"type": "integer", "required": True}},
         "costs_budget": True},
        {"name": "help",
         "description": "Return a general hint. It never reveals the constants.",
         "params": {"question": {"type": "string", "default": ""}},
         "costs_budget": False},
    ]

    def evaluate(self, x):
        return (self._A * x + self._B) % 97

    def help(self, question=""):
        return "..."
```

Each `ACTIONS` entry becomes something the model can call. Types available:
`integer`, `number`, `string`, `boolean`, `array`, `object`. Full field reference
in [AUTHORING.md](AUTHORING.md#actions--your-probe-surface).

### `golden/expected.json` — the numeric answer and tolerance *(required)*

```json
{
  "answer": [11, 4],
  "tolerance": 0,
  "keys": ["a", "b"],
  "scoring": "binary"
}
```

- `tolerance` — absolute, per numeric element. Set it **tighter than the distance
  to your nearest near-miss**, or the wrong answer passes too.
- `keys` — names your answer elements, so the model may submit either
  `[11, 4]` or `{"a": 11, "b": 4}`.
- `scoring` — leave `"binary"`. `"partial"` awards half credit for recovering
  one of two constants, which rewards the very incompleteness most tasks exist
  to reject.

### `problem.md` — the general explanation *(required, or use the form)*

The task in your own words: the setup, what to report, and the budget.

**You do not need to document the tools.** The container appends an accurate,
auto-generated calling guide to whatever you write, built from your `ACTIONS`.
That's deliberate — a hand-written tool description is the easiest thing in the
setup to get out of sync with the code.

State the setup and the budget, and nothing about how to solve it. Never name
the intended method or the error you're discriminating against — not here, not
in an action `description`, not in `help()` output.

### `solution/main.py` — the intended solver *(required for validation)*

Proves the task is solvable within budget.

```python
def solve(oracle):
    b = oracle.evaluate(0)
    y1 = oracle.evaluate(1)
    return [(y1 - b) % 97, b]
```

Also write `solution/shortcut.py`, the tempting wrong approach. The validator
requires it to **fail** — a trap that scores 1.0 means the task doesn't
discriminate and is broken.

Neither file ever enters the container.

---

## 2. Validate before you upload

```bash
python3 tools/validate_problem.py my-problem-id
```

It checks that your oracle loads, that every declared action actually reaches
your code, that the intended solver passes within budget, that the shortcut
fails, that the budget is enforced, and that neither your prompt nor your hint
text gives away the answer or the method. Then it prints the exact form values
for step 4.

`FAIL` means don't upload yet. `WARN` is advisory — read it and decide.

---

## 3. Upload the folder

**Preloaded Files → Mount files.** Upload your problem folder so it lands at:

```
/mnt/problems/my-problem-id/
├── problem.md
├── oracle/setup.py
└── golden/expected.json
```

Upload **only those three**. Never upload `solution/`, your near-miss table, or
your calibration notes — the container doesn't need them, and anything mounted
is on disk inside the environment.

The container searches `/mnt/problems` *before* its built-in problems, so a
mounted folder is picked up immediately and can also override a baked-in task.

### The two upload boxes are not interchangeable

They sit next to each other and only one reaches the container:

| Box | Where the files go | Use it for |
| --- | --- | --- |
| **Preloaded Files → Mount files** | *mounted into the container at run time* | ✅ your oracle, golden answer, problem.md |
| **Upload Supporting Files** | remote storage, **never mounted** | reviewer material: uniqueness argument, calibration notes, near-miss table |

Read the second box's help text carefully — it says *"use for reference
materials like golden answers that humans need to review."* That means golden
answers **for human reviewers**, not the `golden/expected.json` the grader reads.
Put your answer key there and the container never sees it: `setup_problem` fails
with "No problems found", because nothing was mounted.

If you hit that error, this is almost certainly why — the message says so
explicitly.

---

## 4. The five fields that matter

| Field | Value |
| --- | --- |
| **Problem ID** | `my-problem-id` — must match the mounted folder name exactly |
| **Task Prompt** | paste `problem.md`, or write it here and skip the file |
| **Tools** | **leave empty** |
| **Grading Strategy** | **`mcp`** |
| **Startup Command** | `python -u /app/mcp_server/server.py` |

Plus: **Docker Image** = the published inverse-tasks image, and turn **"Tell
model about uploaded files" OFF** so the mounted scaffolding isn't listed in the
model's system prompt.

### Two of those will silently ruin the task

**Tools must be empty.** The form is pre-filled with
`bash, str_replace_editor, web_search_deep_research`. With `bash`, the model can
simply read your oracle and your answer key off the filesystem:

```
cat /mnt/problems/my-problem-id/oracle/setup.py     # the hidden constants
cat /mnt/problems/my-problem-id/golden/expected.json # the answer
```

It would score 1.0 without doing any inference, and the pass rate would look
great. An inverse task needs no tools beyond the oracle, so clear the field.

**Grading Strategy must be `mcp`.** The form defaults to `Rubric (Itemwise)`,
which hands the transcript to an LLM judge scored against rubric items and
**ignores `golden/expected.json` entirely** — your tolerance, your near-miss
discrimination, all of it. `mcp` runs the container's `grade_problem`, which
compares the submission to your golden answer deterministically. That's also why
you can ignore the "Rubric Items — Required" warning: it belongs to the rubric
strategy you're not using.

---

## 5. What the model actually experiences

It gets your prompt plus the generated guide, and probes through `query`:

```
| Call                                                  | What it does          | Budget |
| `query(action="evaluate", params={"x": <integer>})`   | Return the box's ...  | costs 1 query |
| `query(action="help", params={"question": <string>})` | Return a general hint | free |

- submit_answer(answer) — record your final answer as JSON: [<integer>, <integer>]
- describe_oracle() — re-read this list and check your remaining budget. Free.

Query budget: 6 call(s).
```

So the loop is: `query` to probe → reason → `submit_answer` → `grade_problem`
scores it against your golden answer. The budget is enforced by the container, so
the model cannot exceed it, and a call that errors inside your oracle still
spends its budget (otherwise a solver could probe for free by triggering errors).

---

## 6. Calibrate

Run the problem, read the transcript, then check it against the bar in
`sample_experts_instructions.md`:

- pass rate **0.15–0.40** at N=32 across ≥3 checkpoints
- intended solver passes; shortcut fails
- **≥60% of failures land on your named near-miss** — this is the real test of
  whether you built the task you think you built

Set **Number of Attempts** to 3 for a first look; go to 32 once it behaves.

If the pass rate is 0, the budget is probably too tight or the prompt is
ambiguous. If it's above 0.6, the trap isn't tempting or the tolerance is too
loose.

---

## Quick reference

| I want to... | Do this |
| --- | --- |
| Add a task | New folder under `problems/`, mount it, new problem in the form |
| Change the prompt | Edit the Task Prompt field — no re-upload needed |
| Change the oracle or answer | Re-upload the folder as Preloaded Files |
| Change the tool names | Edit `ACTIONS` in your oracle; the guide updates itself |
| Give partial credit | `"scoring": "partial"`, or write `grader/grade.py` |
| Check my work | `python3 tools/validate_problem.py my-problem-id` |
