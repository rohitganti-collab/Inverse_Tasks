# Inverse_Tasks

A Taiga RL environment for **inverse tasks**: the model probes a hidden system
only through `query_oracle(mode, parameters)` under a tight budget, then
submits an answer graded against a golden key.

The Docker image is **generic**. Experts write the oracle, golden answer, and
(optionally) Task Prompt; the engine loads whatever their oracle declares and
publishes exactly that. No server changes per task.

## How secrets stay hidden on Taiga

1. The MCP server and problem data are **root-owned and owner-only**.
2. Taiga runs model-side tools as uid/gid `1000:1000`.
3. **Tools is empty by default**; add a filesystem tool only when the task
   genuinely needs it.
4. **Preloaded Files** mount only the runtime subset (never `solution/`).
5. **Tell model about uploaded files: OFF**.
6. **Grading Strategy: `mcp`** — not Agentic Grader / Rubric.

At setup, writable preloaded problem trees are changed to owner-only
permissions. Their contents are never overwritten, so a Taiga MCP-process
restart can reload the oracle and golden answer before grading.

See **[docs/EXPERT_WORKFLOW.md](docs/EXPERT_WORKFLOW.md)** for the exact form
fill-in matching the Create Problem UI.

```bash
cp -r problems/_template problems/my-problem-id
python3 tools/validate_problem.py my-problem-id
```

## Layout

```
Dockerfile                 generic MCP runtime (oracle-agnostic)
mcp_server/                engine + tools (query_oracle, submit_answer, …)
problems/
  _template/               copy this to start a task
  modular-black-box/       sample teaching fixture
```

## Model-facing tools

| Tool | Purpose |
| --- | --- |
| `query_oracle(mode, parameters)` | Probe the hidden system |
| `describe_oracle()` | Modes + budget remaining (free) |
| `submit_answer(answer)` | Final JSON answer |

`setup_problem` / `grade_problem` are harness-only (hidden from the model).

## Build / test

```bash
python3 -m unittest discover -s tests
python3 tools/validate_problem.py
docker build -t inverse-tasks:local .
```
