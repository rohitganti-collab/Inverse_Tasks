# Running your task on Taiga — the runbook

Everything between "I have an idea" and "my task has a measured pass rate."
Follow it in order. Sections 1–5 happen on your machine; 6 onward happen in the
Taiga web UI.

You never build a Docker image unless you need a tool the published one doesn't
have (section 7).

---

## 0. Before you start

| You need | How to get it |
|---|---|
| A Taiga account | Complete Forte onboarding, sign the ICA, clear the background check. Ask your project lead if you're stuck — this gates everything. |
| Access to the environment | Ask your lead to add you to the environment your project uses. |
| **The HDO project code set on the environment** | Ask your lead. Without it, runs do not count toward the evaluation — you can burn a week of jobs that measure nothing. Check for a "No HDO project code" banner on the environment page before you run anything. |
| Python 3.11+ | For the validator. No other local dependency. |
| Docker | Only if you hit section 7. |

Then:

```bash
git clone <this repo>
cd Inverse_Tasks
python3 -m unittest discover -s tests     # engine regression suite
python3 tools/validate_problem.py         # the reference problems should pass
```

If those two commands don't pass on a clean clone, stop and report it — nothing
downstream is trustworthy.

---

## 1. Read one finished task

Twenty minutes, and it saves more than it costs.

- **Inverse:** `problems/modular-black-box/` — read `STATE.md`, then
  `reasoning_trap.md`, then `problem.md`, then `oracle/setup.py`, then both
  solvers. That order is the authoring order.
- **Forward:** `problems/rod-heat-forward/` — same order.

Both are **reference fixtures**. They are structurally complete and
validator-clean, and neither is calibrated — a frontier model solves both. Copy
their structure, not their difficulty.

---

## 2. Create your folder

```bash
cp -r templates/inverse-task problems/my-problem-id     # or templates/forward-task
cd problems/my-problem-id
for f in $(find . -name '*.template'); do mv "$f" "${f%.template}"; done
```

`my-problem-id` must be lowercase kebab-case: `^[a-z0-9]+(-[a-z0-9]+)*$`. Taiga
enforces that pattern. The folder name becomes the Problem ID and the mount
path, so pick it once and don't rename.

Folders starting with `_` or `.` are never served, which is why `_template`
isn't a problem.

---

## 3. Author it

Follow `INSTRUCTIONS.md` in the folder you just copied. Eight steps, in order,
answer first and prompt last. The science requirements live in
`docs/TASK_DESIGN.md`; the engineering contract lives in `docs/AUTHORING.md`.

Do not skip to the prompt. It is written last for a reason: a prompt drafted
early describes the task you imagined rather than the one you built.

---

## 4. Validate locally

```bash
python3 tools/validate_problem.py my-problem-id
```

Fix every `FAIL`. Read every `WARN` and decide — they are the ones a human has
to judge, especially the leakage warnings.

This is not a formality. It catches, before you spend a single Taiga job: an
oracle that declares a parameter it can't service, a golden answer that doesn't
match the declared shape, an intended solver that busts the budget, a shortcut
that passes (task broken), a budget that isn't enforced, the answer printed in
your own prompt, and method vocabulary in solver-visible text.

The validator prints your exact Create Problem form values when it passes.
Keep that output on screen for section 6.

---

## 5. Decide which image you need

| Your oracle / solver imports | Image |
|---|---|
| Python standard library only | The **published `inverse-tasks` image**. Nothing to build. |
| numpy, scipy, or any scientific package | You need a **custom image** — see section 7 first, then come back. |

The published image contains `mcp` and `pydantic` and nothing else. `import
numpy` in your oracle will fail at `setup_problem` time with an import error
that looks like a Taiga bug and isn't.

---

## 6. Create the problem in Taiga

**Environment → Problems → Create Problem.** Field by field.

### Basic Information

| Field | Value | Why |
|---|---|---|
| **Problem ID** | `my-problem-id` | Must match the mounted folder name exactly, or the engine won't find your problem. |
| **Task Prompt** | Paste the contents of `problem.md` | The container appends the tool-calling guide automatically. Do not document `query_oracle` syntax yourself — if you hand-write it and later change `ACTIONS`, the two drift apart. |
| **Hints** | Empty | A hint that names the method destroys the task. |
| **System Prompt** | Empty | Unless you have a specific reason. |

### Preloaded Files / Supporting Files

Three upload boxes on this form do three different things. Getting them mixed up
is the most common way a task leaks its own answer.

| Box | Mounted into container? | Use for |
|---|---|---|
| **Preloaded Files → Mount files** | **Yes** | The runtime subset only |
| **Upload Supporting Files** | No — human review only | `reasoning_trap.md`, `STATE.md`, `grader/grading_guide.md` |
| **Grader Files** | Injected for *agentic* graders | **Never** for these tasks |

Mount exactly this, at `/mnt/problems/my-problem-id/`:

```
inverse task                    forward task
├── oracle/setup.py             ├── simulation/**
└── golden/expected.json        └── golden/expected.json
```

**Never mount `solution/`.** It contains the intended solver and the trap.

| Field | Inverse | Forward |
|---|---|---|
| **Tell model about uploaded files** | **OFF** | **ON** — it has to know the inputs exist |

### Grading

| Field | Value |
|---|---|
| **Grading Strategy** | **`mcp`** |
| Nickname / Grader Guidance / Grader Files | Empty |

`mcp` calls the container's `grade_problem`, which compares the submission to
your `golden/expected.json` within your tolerance. **Agentic Grader ignores your
golden answer entirely** and asks an LLM to judge — that reintroduces exactly the
judge-shaped attack surface this whole programme exists to remove. Rubric
(Itemwise) is likewise wrong here.

### Customize Tools

| Field | Inverse | Forward |
|---|---|---|
| **Tools** | **EMPTY — delete `bash` and `str_replace_editor`** | **`bash`** (the model has to run the tool) |
| **Enabled Package Managers** | empty | empty, unless the task genuinely needs to install something |
| **Domain Allowlist** | empty | empty unless the tool needs the network |
| **Docker Image** | your published image tag | ditto |
| **Startup Command** | `python -u /app/mcp_server/server.py` | same |
| **Required Resources** | `2vcpu+6gib` is plenty for an oracle | size it to your solver |

**On clearing Tools for an inverse task.** The form may pre-fill `bash` and
`str_replace_editor`. Delete them. An oracle-only task needs only the MCP tools
the image publishes — `query_oracle`, `describe_oracle`, `submit_answer` — and
leaving broad tools enabled hands the model a filesystem next to the mount that
holds your answer key. The container defends itself (MCP and problem trees are
root-only; Taiga runs model-side tools as uid/gid 1000), but that is the second
line of defence, not the first. If your task genuinely needs a shell, add it
deliberately and say why in `STATE.md`.

---

## 7. If you need a custom image

Only when your oracle or solver imports something beyond the standard library.

1. Add your pinned dependencies to `requirements.txt` in the repo root.
2. Regenerate the lock file, then build for **linux/amd64** — Taiga runs amd64,
   and an arm64 image built on an Apple laptop fails at startup with an
   exec-format error:

```bash
docker build --platform linux/amd64 -t inverse-tasks:local .
docker tag inverse-tasks:local \
  us-east1-docker.pkg.dev/<PROJECT>/<REPO>/inverse-tasks:v2
docker push us-east1-docker.pkg.dev/<PROJECT>/<REPO>/inverse-tasks:v2
```

The build runs the engine selftest against the real `mcp` package and fails the
build rather than letting a broken wiring surface as a mystery at job time.

3. **Tag immutably.** `:v2`, or a digest. Never reuse a tag like `:dev` or
   `:latest` for a task you have calibrated — a mutable tag means the thing you
   measured and the thing that runs are different, and your pass rate is
   describing an image that no longer exists.

**Forward tasks almost always need this.** The published image has no scientific
toolchain, so a forward task whose whole point is running OpenFOAM needs an
image with OpenFOAM in it. Build from this repo's Dockerfile so the MCP server
and grading path come along, and add your tool on top.

---

## 8. Run it

**Run Problem** → pick your model → run.

Read the transcript in full, not just the score. You are looking for:

- Did the model call the tools you expected, or did it find a mode you forgot
  was reachable?
- Did it burn budget on something uninformative, or did it walk straight to the
  answer?
- Did it fail for the reason you designed, or for a reason you didn't?
- Did anything in a tool return value tell it more than you meant to?

A pass on the first try is not good news. See section 9.

---

## 9. Calibrate

One run is not a measurement. The full gate — pass-rate band, failure
concentration, artefact cap, and how to read them — is in
**`docs/CALIBRATION.md`**. Do not skip it: an uncalibrated task is not a
deliverable, and a task that everything passes contributes exactly zero
gradient.

Record the job id for every run in your `STATE.md` so the numbers can be traced.

---

## 10. Iterate

When a run comes back too easy, harden it — five levers, in
`docs/TASK_DESIGN.md`. Re-validate, re-run, re-record.

When a run comes back at 0/N, the usual causes in order: the intended path
doesn't fit the budget; the prompt is ambiguous about the answer format; the
oracle raises on a call the model reasonably makes; the answer isn't unique
over the space the prompt declares.

Editing a problem in Taiga creates a new **ProblemVersion**. Pass rates are
per-version — do not compare a number measured on v3 with one measured on v6.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Problem not found` at setup | Problem ID doesn't match the mounted folder name | They must be byte-identical |
| Import error at setup | Oracle imports a package the image lacks | Section 7 |
| Model says it can't see any tools | Grading strategy isn't `mcp`, or the startup command is wrong | `python -u /app/mcp_server/server.py` |
| Model reads the oracle source | Broad tools left enabled *and* mount permissions failed | Clear Tools; check `setup_problem` ran |
| Score 0 with a correct-looking answer | Submission shape doesn't match the golden shape | Declare `ANSWER_SCHEMA`; re-read the Output format section of your prompt |
| Score 1.0 every run | Task is too easy, or the shortcut is reachable | `docs/CALIBRATION.md`, then harden |
| Answer graded wrong despite right method | Tolerance too tight for legitimate numerical spread | Measure the spread, widen — but stay tighter than the nearest near-miss |
| Runs "don't count" | No HDO project code on the environment | Section 0 |
| Container won't start | Image built for arm64 | Rebuild with `--platform linux/amd64` |
| Nondeterministic scores | Unseeded RNG, or per-attempt state at module level | Seed it; move state into `Oracle.__init__` |
