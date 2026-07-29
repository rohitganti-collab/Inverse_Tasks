# Inverse_Tasks

Generic **inverse-task** runtime for Taiga: one Docker/MCP image, many problem
folders. The model probes a hidden system only through
`query_oracle(mode, parameters)`, then submits an answer graded against a
golden key.

Experts add science by dropping a folder under `problems/` — **no MCP or Docker
changes per task**.

## Architecture

```
Taiga harness
  └─ Docker image (this repo)
       ├─ mcp_server/          generic engine (oracle-agnostic)
       │    setup_problem      # harness-only: load oracle, return prompt
       │    grade_problem      # harness-only: score vs golden
       │    query_oracle       # model-facing probe
       │    describe_oracle    # model-facing: modes + budget
       │    submit_answer      # model-facing: final JSON answer
       └─ problems/<id>/       drop-in tasks
            problem.md         # task prompt (or use Taiga Task Prompt field)
            oracle/setup.py    # hidden Oracle / query_oracle
            golden/expected.json
```

The harness owns the agent loop. This image owns the instrument + verifier.
`setup_problem` / `grade_problem` are hidden from the model automatically.

## Per-problem contract

```bash
cp -r problems/_template problems/my-problem-id
```

| File | Role |
| --- | --- |
| `problem.md` | Prompt (optional if Task Prompt is set in Taiga) |
| `oracle/setup.py` | Hidden system. Prefer `class Oracle` + `ACTIONS`, or module-level `query_oracle(mode, parameters)` |
| `golden/expected.json` | `{ "answer": ..., "tolerance": N }` |
| `solution/` | Local calibration only — **never** mount on Taiga |

Sample: `problems/modular-black-box/`.

## Model-facing tools

| Tool | Purpose |
| --- | --- |
| `query_oracle(mode, parameters)` | Probe the hidden system |
| `describe_oracle()` | Modes + budget remaining (free) |
| `submit_answer(answer)` | Final JSON answer |

## Taiga form (critical)

| Field | Value |
| --- | --- |
| **Docker Image** | published inverse-tasks image |
| **Startup Command** | `python -u /app/mcp_server/server.py` |
| **Tools** | **empty** (no bash / str_replace_editor) |
| **Grading Strategy** | **`mcp`** |
| **Preloaded Files** | mount `oracle/` + `golden/` at `/mnt/problems/<id>/` |
| **Tell model about uploaded files** | **OFF** |

Details: [docs/EXPERT_WORKFLOW.md](docs/EXPERT_WORKFLOW.md).

## Build / test

```bash
python3 -m unittest discover -s tests
python3 tools/validate_problem.py modular-black-box
docker build -t inverse-tasks:local .
```
