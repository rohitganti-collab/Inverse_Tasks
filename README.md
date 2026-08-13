# Inverse_Tasks

Everything needed to author a STEM reasoning task and run it on Taiga.

Two directions ship as **separate problems**:

- **Inverse** — the model gets a hidden system it can only probe through a
  budgeted oracle, and must recover the hidden parameters. *This is the default
  direction.*
- **Forward** — the model gets the whole system as input files and must run the
  tool to compute a consequence. Chosen when the difficulty genuinely lives in
  the mesh / solver / convergence decision.

Adding a task means adding a folder under `problems/`. No server or Docker
changes.

---

## Start here

**Never written one of these?** In order:

1. **`docs/TASK_DESIGN.md`** — what a good task is. The eight steps, the oracle
   rules, the ways tasks get rejected.
2. **`problems/modular-black-box/`** — a complete inverse task. Read `STATE.md`,
   `reasoning_trap.md`, `problem.md`, `oracle/setup.py`, then both solvers, in
   that order. That's the authoring order.
3. **`templates/inverse-task/INSTRUCTIONS.md`** — copy the folder and build
   yours.
4. **`docs/TAIGA_RUNBOOK.md`** — get it running on Taiga and calibrated.

```bash
python3 -m unittest discover -s tests     # engine regression suite
python3 tools/validate_problem.py         # the reference problems should pass
```

If those don't pass on a clean clone, stop and report it.

---

## Map

| Path | What it is |
|---|---|
| **`docs/TASK_DESIGN.md`** | The science: eight steps, oracle rules, hardening strategies, rejection reasons |
| **`docs/CALIBRATION.md`** | **The shipping gate — the authority on the bar.** Pass-rate band, failure concentration, tolerance rule |
| **`docs/TAIGA_RUNBOOK.md`** | Idea → running, calibrated task. Every Taiga form field, plus troubleshooting |
| **`docs/AI_USE_POLICY.md`** | What Claude may and may not write |
| **`docs/AUTHORING.md`** | The engineering contract: oracle API, `expected.json` fields, custom graders |
| **`docs/HARDENING.md`** | The threat model: what the runtime enforces, and the five things only the Taiga form can |
| `tools/verify_container.sh` | Run the known reward-hacking attacks against a built image |
| `templates/inverse-task/` | Copy-me folder + `INSTRUCTIONS.md` |
| `templates/forward-task/` | Copy-me folder + `INSTRUCTIONS.md` |
| `problems/modular-black-box/` | Reference inverse task |
| `problems/rod-heat-forward/` | Reference forward task |
| `problems/_template/` | Bare runnable skeleton (folders starting `_` are never served) |
| `tools/validate_problem.py` | Run before every upload |
| `mcp_server/` | The engine. You should not need to touch it |
| `Dockerfile`, `docker/` | Image build; only needed for a custom toolchain |

### The reference problems are fixtures

`modular-black-box` and `rod-heat-forward` are structurally complete and
validator-clean, and **neither is calibrated** — a frontier model solves both.
They exist so you can read a finished task and so the engine has something to
regression-test against.

**Copy their structure, not their difficulty.** Do not submit either as your
authored task.

---

## The two rules

**Lock the answer first. Write the prompt last.**

**The oracle is an instrument, not a grader.** It returns observations — never
`correct`, `accepted`, `close_enough`, or a hint. If you're writing `check_*` or
`validate_*`, you've built a grader and the model will search against it instead
of reasoning.

---

## Non-negotiables when you configure Taiga

Full walkthrough in `docs/TAIGA_RUNBOOK.md`. The four that break tasks silently:

| | Inverse | Forward |
|---|---|---|
| **Grading Strategy** | `mcp` | `mcp` |
| **Tools** | **empty** — delete `bash` and `str_replace_editor` | `bash` |
| **Preloaded Files** | `oracle/` + `golden/` only | `simulation/` + `golden/` only |
| **Tell model about uploaded files** | OFF | ON |

**Agentic Grader ignores `golden/expected.json`** and asks an LLM to judge —
that reintroduces exactly the judge-shaped attack surface exact-match grading
exists to remove. Never mount `solution/`.

---

## Runtime surface

| Tool | Who sees it | Purpose |
|---|---|---|
| `query_oracle(mode, parameters)` | model | Probe the hidden system (inverse only) |
| `describe_oracle()` | model | Modes and remaining budget |
| `submit_answer(answer)` | model | Final answer |
| `setup_problem` / `grade_problem` | harness only | Load the problem / score against golden |

The container appends a calling guide generated from your `ACTIONS` to the
prompt, so what the model is told always matches what is published.
