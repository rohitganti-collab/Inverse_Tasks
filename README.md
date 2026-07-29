# Inverse_Tasks

A Taiga RL environment for **inverse tasks**: a model is given a black-box
oracle it can only probe through a tight budget of tool calls, and must recover
the hidden cause (constants, parameters, a mechanism) that explains what it
observes. Each task is built so that a competent solver can fail in one
specific, predictable way — see `sample_experts_instructions.md` for the
authoring method.

The container is **oracle-agnostic**. Experts write the prompt, the oracle, the
solvers and the answer key; the engine reads whatever their oracle declares and
publishes exactly that to the model. Adding a task is adding a folder — no
server or Docker changes.

Experts never build the image. It is published once, then each new task is a
folder they upload as Preloaded Files:

```bash
cp -r problems/_template problems/my-problem-id   # 1. write 4 files
python3 tools/validate_problem.py my-problem-id   # 2. validate + print form values
# 3. upload the folder to /mnt/problems/my-problem-id/ and fill in 5 form fields
```

- **[docs/EXPERT_WORKFLOW.md](docs/EXPERT_WORKFLOW.md)** — start here: what to
  write, and exactly what to put in Taiga's Create Problem form.
- **[docs/AUTHORING.md](docs/AUTHORING.md)** — the full engineering contract.

> Two Create Problem defaults will silently ruin an inverse task: the **Tools**
> field arrives pre-filled with `bash`, which lets the model read the oracle and
> the answer key off disk, and **Grading Strategy** defaults to
> `Rubric (Itemwise)`, which ignores `golden/expected.json` in favour of an LLM
> judge. Clear the first, set the second to `mcp`.

## Layout

```
Dockerfile                      generic runtime; ships every problem below
requirements.txt                mcp, pydantic
mcp_server/
  core.py                       the engine — oracle loading, action
                                normalisation, budget, grading. Stdlib only.
  server.py                     thin MCP layer: decides which tools the model sees
docker/collect_problems.py      allowlists each problem's runtime files into the image
tools/validate_problem.py       pre-flight checks for an authored problem
tests/                          engine + server suites, no third-party deps needed
problems/
  _template/                    copy this to start a task (never served)
  modular-black-box/            the sample task
```

Per problem, only `problem.md`, `config.yaml`, `oracle/`, `golden/expected.json`
and `grader/*.py` enter the image. The intended solver, the trap solver, the
near-miss table and the calibration notes stay out — by allowlist, so a new
authoring file is excluded by default rather than shipped next to the answer key.

## The oracle contract, in brief

`problems/<id>/oracle/setup.py` defines a class named `Oracle`. Declare the
probe surface and the engine turns each entry into a tool:

```python
class Oracle:
    BUDGET = 6
    ACTIONS = [
        {"name": "evaluate",
         "description": "Return the box's output for your chosen integer x.",
         "params": {"x": {"type": "integer", "required": True}}},
        {"name": "help",
         "description": "Return a general hint.",
         "params": {"question": {"type": "string", "default": ""}},
         "costs_budget": False},
    ]
    def evaluate(self, x): ...
    def help(self, question=""): ...
```

Undeclared oracles still work: the engine falls back to introspecting public
methods, then to forwarding through a single `query(mode, **params)`. Declaring
`ACTIONS` is preferred — it's what gives the model tools named the way your
prompt names them, with validated parameters.

Budget, parameter checking, answer parsing, grading, and leakage containment are
handled once, identically for every problem.

## Container interface

The image runs an MCP server over stdio. Taiga's scaffold hooks are hidden from
the model automatically; the rest is what the model can call.

| Tool | Visibility | Purpose |
| --- | --- | --- |
| `setup_problem` | hidden | Fresh oracle for `problem_id`; returns `problem.md`. |
| `grade_problem` | hidden | Scores the submission against `golden/expected.json`. |
| `list_problems` | hidden | Which problem ids this image serves. |
| *your declared actions* | model | One tool per `ACTIONS` entry, in bound mode. |
| `query(action, params)` | model | The generic probe, in generic mode. |
| `describe_oracle()` | model | Available actions, budget remaining, answer shape. Free. |
| `submit_answer(answer)` | model | Final answer as JSON; resubmission allowed. |

**Bound vs generic mode.** MCP publishes its tool list during the initialize
handshake, *before* Taiga says which problem is running — so per-problem tool
names only exist if the problem is known at startup. Pass `--problem-id` (or
`$PROBLEM_ID`, or ship exactly one problem) and the server binds at startup and
publishes your named actions. Otherwise it publishes `query(action, params)` and
the model discovers the surface via `describe_oracle()`. Both paths are tested.

## Develop and test

```bash
python3 -m unittest discover -s tests    # engine + server suites (no mcp needed)
python3 tools/validate_problem.py        # validate every authored problem
docker build -t inverse-tasks:local .
docker run --rm -i inverse-tasks:local   # stdio smoke test
```

To drive it with Taiga's real agent harness without pushing an image, use the
local tunnel (see the Taiga wiki, `features/local_tunnel.md`):

```bash
taiga-local-tunnel start --dockerfile ./Dockerfile \
  --startup-command "python -u /app/mcp_server/server.py --problem-id modular-black-box" \
  --problem-id modular-black-box
```

## Registering on Taiga

Push the image, then create a problem pointing at it — see
`problems-metadata.example.json`. Two settings are easy to get wrong:

- **Grading strategy must be `mcp`.** The Create Problem form defaults to
  `Rubric (Itemwise)`, which sends the transcript to an LLM judge and ignores
  your golden answer.
- **`startup_command` should pass `--problem-id`**, otherwise the model gets the
  generic `query()` surface rather than the tools your prompt names.

`required_tools` is normally empty — the model needs the oracle, not bash.

To iterate without rebuilding, mount a problem folder at
`/mnt/problems/<problem_id>/` via `preloaded_files`; that path is searched ahead
of the baked-in problems (`INVERSE_TASKS_PROBLEM_DIRS`).
