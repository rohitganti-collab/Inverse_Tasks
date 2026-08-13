# Hardening: what the runtime guarantees, and why

An inverse task is only worth running if the score means what it claims. Every
defect in this document was found in a *shipped* environment, and in three of
the four cases the task still looked like it worked — the runs went green, so
nothing drew attention until someone went looking.

This is the threat model the image is built against, what it now enforces, and
what it still cannot enforce on its own.

## Threat model

Assume all of the following, because all of it has happened:

| Assumption | Why |
| --- | --- |
| The model has a shell as uid 1000 | Taiga's Tools field is set per problem. This repo tells you to leave it EMPTY for inverse tasks, but that is configuration outside the image, and shipped problems have had `bash` and `str_replace_editor` enabled. |
| The model can call every registered MCP tool | `setup_problem` and `grade_problem` are meant to be harness-only. A shipped image was observed exposing `grade_problem` to the model. The image cannot verify who is calling. |
| Anything `grade_problem` returns is readable by the model | Taiga writes grade output to `/workdir/app.log`, world-readable, while solver tools run as uid 1000. |
| `/tmp` is world-writable and pre-creatable | It is, and a solver can plant files at predictable paths before the server writes them. |
| The model will notice anything the task leaks | It will. When an oracle returned every reading as a schema-validation error, the models parsed the values out of the error strings and scored 1.0 anyway. |

The through-line: **the image must not depend on the model being unable to reach
something.** Where the model can reach it, the image has to make reaching it
useless.

## What the runtime enforces

### The grade payload never contains the answer

`core.grade_discloses_expected()` returns False whenever
`INVERSE_TASKS_RUNTIME=taiga`, which the image sets. Under that runtime:

- top-level `expected` is omitted from grade metadata;
- per-element `details[].expected` is stripped, keeping `match` and the model's
  own `submitted` value so a failure is still diagnosable;
- a custom `grader/grade.py` cannot reopen the hole — its metadata is scrubbed
  on the way out;
- `expected_fingerprint`, a truncated SHA-256 of the golden answer, replaces it.

The fingerprint is what makes a fixed-instance task visible: if every rollout of
a family reports the same fingerprint, the instance never varied, and the pass
rate is measuring memorisation.

Without this, a reachable grader is an answer oracle:

```
submit_answer([0,0,0,0])   # throwaway
grade_problem(...)          # payload lands in /workdir/app.log
cat /workdir/app.log        # expected=[1784, 1330, 840, 935]
submit_answer([1784,1330,840,935])
```

Authoring runs keep the disclosure — the author already owns
`golden/expected.json`, and the validator needs to compare against it.

### Observations survive the transport

Probe results are rendered by `server._dump()` and returned as `str`. The tool
is annotated `-> str`, so no output schema can reject a float.

This sounds trivial. It was not: a shipped image declared the probe tool as
`-> str | int | dict`, FastMCP derived its output schema from that annotation,
and **every reading of a float-returning bench failed validation** — reaching the
model only inside `Output validation error: 1.3362473561192243 is not valid
under any of the given schemas`. The runs still passed, because the value was in
the error text. `tests/test_hardening.py::FloatObservations` and the validator's
`transport:` check both guard this now.

### The budget cannot be reset

The query budget is the entire difficulty mechanism, so it is enforced by the
engine rather than trusted to the oracle:

- counted **before** dispatch, so an oracle that raises still spends its call —
  no free probing by inducing errors;
- `setup_problem` refuses re-entry once an attempt has spent budget or
  submitted, so calling it again cannot hand back a fresh `Session` with
  `calls_used = 0`;
- the attempt-state snapshot lives at `/var/lib/inverse-tasks/session.json`
  (root-owned, `0700`), not under `/tmp`, and is ignored on restore unless it is
  a regular file owned by this process with no group or other bits;
- `_own_private_dir()` verifies ownership before writing, because
  `mkdir(exist_ok=True)` accepts a directory somebody else created and a later
  `chmod` fixes the mode but not the owner.

### Problem files are private, except what a forward task must publish

`harden_problem_permissions()` runs at `setup_problem` and, under the Taiga
runtime, makes the problem tree root-owned:

| Path | Mode | Why |
| --- | --- | --- |
| `oracle/`, `golden/`, `grader/`, `problem.md` | `0700` / `0600` | The hidden system, the answer, and the grading logic. |
| `simulation/` and everything under it | `0755` / `0644` | A forward task's whole premise is that the model gets these inputs. Root-*owned*, so they are readable but not editable — a solver cannot rewrite its own inputs. |
| the problem root | `0711` when a public subtree exists, else `0700` | Traversable so `simulation/...` can be opened by name, not listable, so nothing beside it can be enumerated. |

Permissions rather than deletion: Taiga may restart the MCP process between
setup and grading, and a deleted file cannot be reloaded.

Hardening is deliberately confined to the image (`INVERSE_TASKS_RUNTIME=taiga`)
so a local run never mutates an authoring checkout. If it cannot make the tree
private it raises, rather than continuing quietly — see
`INVERSE_TASKS_REQUIRE_PRIVATE_PROBLEMS`.

### The build is the gate

`docker build` runs, and fails on, the full chain: `--selftest` in both tool
modes, an end-to-end MCP protocol smoke over stdio, and
`tools/validate_problem.py` across every baked-in problem. A broken integration
becomes a build failure instead of a mystery at job time.

That gate has already earned its place — it caught a Python 3.11 f-string
incompatibility that the authoring machine's 3.14 accepted silently.

## What the image cannot enforce

Be honest about the boundary. These need the Taiga form to be right:

1. **Tools must be EMPTY for inverse tasks.** The image cannot un-register
   `bash`. It can only ensure that having a shell buys nothing — which is what
   everything above is for.
2. **Grading Strategy must be `mcp`.** An Agentic Grader is an LLM judge; it
   awards partial credit and can be argued with. Exact-match, judge-free grading
   is the entire premise of an inverse task.
3. **Preloaded Files must mount `oracle/` + `golden/` only** (or `simulation/` +
   `golden/` for forward tasks), never `solution/`, `STATE.md`,
   `reasoning_trap.md`, or `BRIEF.md`.
4. **"Tell model about uploaded files" must be OFF** for inverse tasks.
5. **The seed must vary per problem-run, and the golden answer must move with
   it.** The image supports `INVERSE_TASKS_SEED`; something upstream has to set
   it and write the matching `golden/expected.json`.

`tools/validate_problem.py` prints the exact form values for each problem. Run
it and copy them.

## Regression coverage

`tests/test_hardening.py` holds one test per defect above, named for the failure
rather than the function, so the reason survives. `tools/validate_problem.py`
adds three pre-ship checks:

| Check | Catches |
| --- | --- |
| `transport:` | observations that cannot cross the MCP boundary unchanged |
| `privacy:` | a grade payload carrying golden values |
| `instance:` | hidden values that cannot vary between rollouts (AST-based — an earlier substring version passed a fixed oracle because the word "instance" appeared in a comment) |

`instance:` is a warning, not a failure: a fixed instance is legitimate while
you iterate. The other two fail the build.
