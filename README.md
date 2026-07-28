# Inverse_Tasks

Inverse tasks sample environment for Taiga.

Each problem gives a model a black-box "oracle" it can only query through a
tight budget of tool calls, and asks it to recover a hidden cause (constants,
parameters, etc.) that provably explains the oracle's behavior. See
`sample_experts_instructions.md` for how a new inverse task is authored.

## Layout

```
Dockerfile              # generic runtime, serves every problem below over MCP
mcp_server/server.py     # setup_problem / evaluate / help / submit_answer / grade_problem
problems/
  modular-black-box/
    problem.md           # task prompt shown to the model
    config.yaml          # display metadata (direction, domain, title)
    oracle/setup.py       # hidden Oracle — never shipped to the model directly
    golden/expected.json  # graded answer + tolerance
    grader/grading_guide.md   # human-readable grading notes (not read by code)
    BRIEF.md, STATE.md, reasoning_trap.md, solution/   # authoring/calibration
                                                        # only — excluded from
                                                        # the Docker image
```

One image serves any number of problems: drop a new folder under `problems/`
with the same five-piece contract (`problem.md`, `oracle/setup.py` exposing a
`query(mode, x=None)` method, `golden/expected.json`) and it's runnable
immediately — no server code changes needed.

## Container interface

The image runs an MCP server over stdio exposing Taiga's required hooks plus
the model-facing tools:

- `setup_problem(problem_id, use_hinted_problem, extra_fields)` — loads
  `problems/<problem_id>/oracle/setup.py`, instantiates a fresh `Oracle`, and
  returns `problem.md` as the prompt.
- `evaluate(x)` / `help(question)` — the only way the model touches the
  oracle; both go through `Oracle.query(...)`, so the hidden constants and
  the intended/shortcut solvers under `solution/` never reach the model.
- `submit_answer(a, b)` — records the model's final answer.
- `grade_problem(problem_id, transcript, extra_fields)` — compares the last
  submission against `golden/expected.json` (exact match within `tolerance`).

`setup_problem` and `grade_problem` are hidden from the model automatically
(Taiga's reserved-hook filtering); the model only ever sees `evaluate`,
`help`, and `submit_answer`.

## Build

```bash
docker build -t inverse-tasks:local .
```

## Test locally

Smoke-test the MCP server without Taiga:

```bash
docker run --rm -i inverse-tasks:local
```

To exercise it against Taiga's actual agent harness without pushing to a
registry, use the local tunnel CLI (see the Taiga wiki's `local_tunnel.md`):

```bash
taiga-local-tunnel start --dockerfile ./Dockerfile \
  --startup-command "python -u /app/mcp_server/server.py" \
  --problem-id modular-black-box
```

## Push and register

Tag and push to your org's registry, then reference the image in a
problems-metadata file (see `problems-metadata.example.json`) when creating a
job or registering a problem version in Taiga.
