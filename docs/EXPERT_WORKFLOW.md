# Finishing an inverse task: the expert workflow

You never build a Docker image. The image is built once and published; you write
the science files, upload only the runtime subset, and fill in the Create
Problem form.

```
1. write        oracle/setup.py, golden/expected.json, solution/{main,shortcut}.py
2. validate     python3 tools/validate_problem.py my-problem-id
3. upload       Preloaded Files → /mnt/problems/my-problem-id/  (oracle + golden only)
4. configure    Taiga form fields below
5. run          Run Problem → read transcript → calibrate
```

The model probes with **`query_oracle(mode, parameters)`**. It must never see
the oracle source. Two defences:

1. The image and problem data are owner-only; Taiga executes model-side tools
   as uid/gid `1000:1000`.
2. **Tools should be empty** for an oracle-only inverse task. Add a filesystem
   tool only when the task explicitly needs one.

---

## 1. What you write

```bash
cp -r problems/_template problems/my-problem-id
```

| File | Who uses it | Mount on Taiga? |
| --- | --- | --- |
| `oracle/setup.py` | MCP loads it as root | **Yes — Preloaded Files** |
| `golden/expected.json` | MCP grades against it as root | **Yes — Preloaded Files** |
| Task Prompt (form) or `problem.md` | Shown to the model | Form preferred; file optional |
| `solution/main.py` | Local validation only | **No** |
| `solution/shortcut.py` | Local validation only | **No** |
| `grader/grading_guide.md`, BRIEF, STATE, trap | Humans / calibration | **Supporting Files only** (not mounted) |

### `oracle/setup.py`

Hidden system. Prefer `class Oracle` with `ACTIONS`. Hidden values in
`_leading_underscore` attributes. `help` must list modes, not the method.

### `golden/expected.json`

```json
{ "answer": [11, 4], "tolerance": 0, "keys": ["a", "b"], "scoring": "binary" }
```

### Task Prompt

Paste into Taiga's **Task Prompt** field (see screenshots). State the setup and
what to report. Do **not** document tool call syntax — the container appends a
generated `query_oracle` guide from your `ACTIONS`.

### `solution/main.py` / `shortcut.py`

Local only. Intended must pass; shortcut must fail.

---

## 2. Validate

```bash
python3 tools/validate_problem.py my-problem-id
```

---

## 3. Upload (Preloaded Files vs Supporting Files)

| Box on the form | Mounted into container? | Use for |
| --- | --- | --- |
| **Preloaded Files → Mount files** | **Yes** | `oracle/`, `golden/` at `/mnt/problems/<id>/` |
| **Upload Supporting Files** | **No** | Human review only (trap write-up, STATE, solutions) |
| **Grader Files** | Injected at `/tmp/grader_files/` for *agentic* graders | **Do not use** for MCP tasks |

Upload only:

```
/mnt/problems/my-problem-id/
├── oracle/setup.py
└── golden/expected.json
```

Turn **Tell model about uploaded files OFF** (`augment_prompt_with_input_files: false`).

---

## 4. Create Problem form — exact values

Matching the Taiga UI sections:

### Basic Information
| Field | Value |
| --- | --- |
| **Problem ID** | `my-problem-id` (must match the mounted folder name) |
| **Task Prompt** | Your science prompt (from `problem.md` or written here) |
| **Hints** | Optional; never name the trap |
| **System Prompt** | Leave empty unless you have a specific reason |

### Preloaded Files / Supporting Files
| Field | Value |
| --- | --- |
| **Preloaded Files** | Mount `oracle/` + `golden/` at `/mnt/problems/<id>/` |
| **Upload Supporting Files** | Optional human docs only |

### Grading
| Field | Value |
| --- | --- |
| **Grading Strategy** | **`mcp`** — not Agentic Grader, not Rubric (Itemwise) |
| Nickname / Grader Guidance / Grader Files | Leave empty for MCP |

`mcp` runs the container's `grade_problem` against your golden answer.
**Agentic Grader** ignores `golden/expected.json` and asks an LLM to judge.

### Customize Tools
| Field | Value |
| --- | --- |
| **Tools** | Clear this for an oracle-only task. Add only tools the task requires. |
| **Enabled Package Managers** | empty |
| **Domain Allowlist** | empty unless the oracle truly needs the network |
| **Docker Image** | your published `inverse-tasks` image |
| **Startup Command** | `python -u /app/mcp_server/server.py` |
| **Required Resources** | e.g. `2vcpu+6gib` |

### Why empty Tools is the safest default

The form may pre-fill broad tools. An inverse task normally needs only the MCP
tools published by this image, so remove unrelated tools and reduce the attack
surface. If a task does require `bash` or an editor, Taiga demotes it to uid
1000 while the MCP and problem trees remain root-only.

An oracle-only inverse task needs **only** the MCP tools the image publishes:
`query_oracle`, `describe_oracle`, `submit_answer`.

---

## 5. What the model experiences

1. Taiga starts the image, runs the startup command (MCP over stdio).
2. Harness calls hidden `setup_problem(problem_id)`.
3. Engine loads oracle + golden, makes the mounted problem tree owner-only,
   and returns Task Prompt + generated `query_oracle` guide.
4. Model calls `query_oracle` / `submit_answer` only.
5. Harness calls hidden `grade_problem` → compares submission to golden.

If Taiga restarts MCP between steps 4 and 5, the owner-only files remain intact
and the persisted attempt state is restored.

---

## 6. Calibrate

Pass rate target **0.15–0.40** at N=32; ≥60% of failures on your named near-miss.
See `sample_experts_instructions.md`.
