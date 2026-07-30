# Inverse_Tasks — Taiga Docker handoff

Generic inverse-task MCP image for Taiga. One image serves every folder under
`problems/`. Experts add tasks without changing the server.

## What the FDE builds and pushes

```bash
# 1. Build (linux/amd64 for Taiga)
docker build --platform linux/amd64 -t inverse-tasks:local .

# 2. Tag for your org registry (example)
docker tag inverse-tasks:local \
  us-east1-docker.pkg.dev/<PROJECT>/<REPO>/inverse-tasks:v1

# 3. Push
docker push us-east1-docker.pkg.dev/<PROJECT>/<REPO>/inverse-tasks:v1
```

Then create/update the Taiga problem with:

| Field | Value |
| --- | --- |
| **Problem ID** | `modular-black-box` |
| **Docker Image** | the pushed tag above |
| **Startup Command** | `python -u /app/mcp_server/server.py` |
| **Tools** | **empty** (delete bash / str_replace_editor) |
| **Grading Strategy** | **`mcp`** |
| **Task Prompt** | contents of `problems/modular-black-box/problem.md` |
| **Preloaded Files** | optional; image already bakes the sample. To override, mount at `/mnt/problems/modular-black-box/` |
| **Tell model about uploaded files** | **OFF** |

See `problems-metadata.example.json` for a full metadata stub.

## Runtime surface (model-facing)

| Tool | Who sees it | Purpose |
| --- | --- | --- |
| `query_oracle(mode, parameters)` | model | Probe the hidden system |
| `describe_oracle()` | model | Modes + budget left |
| `submit_answer(answer)` | model | Final JSON answer |
| `setup_problem` / `grade_problem` | harness only | Load oracle / score golden |

## Problem layout

```
problems/<problem-id>/
  problem.md              # prompt (or paste into Taiga Task Prompt)
  oracle/setup.py         # class Oracle with query(mode, **params) + ACTIONS
  golden/expected.json    # { "answer": [...], "tolerance": N }
  solution/               # local validation only — NOT in the image
```

Sample: `modular-black-box`. Extra Python deps for this sample: **none**
(stdlib only). Image deps are only `mcp` + `pydantic` (see `requirements.txt`).

## Validate before push

```bash
python3 -m unittest discover -s tests
python3 tools/validate_problem.py modular-black-box
docker build --platform linux/amd64 -t inverse-tasks:local .
# optional smoke:
docker run --rm inverse-tasks:local \
  python -u /app/mcp_server/server.py --selftest --problem-id modular-black-box
```
