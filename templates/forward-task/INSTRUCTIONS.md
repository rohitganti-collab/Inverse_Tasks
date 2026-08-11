# Forward task — instructions

Read this once, then work top-to-bottom through **The build order**.

```bash
cp -r templates/forward-task problems/my-problem-id
cd problems/my-problem-id
for f in $(find . -name '*.template'); do mv "$f" "${f%.template}"; done
```

`my-problem-id` must be lowercase kebab-case. It becomes the Taiga Problem ID
and the mount path.

---

## Read this before you choose forward

**Inverse is the default direction.** It produces a cleaner reasoning signal,
because the model's own measurement choices are part of what's being tested.

Choose forward only when all three hold:

- the task genuinely requires **running** a specific tool, and the difficulty
  lives in the mesh / solver / convergence / boundary-condition decision;
- hiding parameters would feel artificial;
- a single well-defined number comes out.

If you can't make that case, write the inverse version instead.

Two things to know going in:

1. **Forward tasks come back easier** on the same model ensemble. Budget for a
   hardening pass; don't be surprised by a first measurement above the band.
2. **The hard part is never running the tool.** Frontier models can drive any
   supported solver. The hard part is the non-obvious method decision that
   quietly determines correctness — and if your prompt makes that decision for
   the model, there is no task left.

---

## What a forward task is

The model is given the whole system — geometry, material properties, boundary
conditions, inputs — as files it can read, and must compute a consequence. There
is no oracle and nothing hidden.

So all the difficulty lives in one place: **the method decision you decline to
make for the model.**

| Decision | The silent failure |
|---|---|
| Mesh / discretisation | Default mesh, unconverged answer, no warning |
| Solver family | Steady-state where the problem is transient |
| Convergence criteria | Residuals fell, the answer is still moving |
| Boundary condition type | Dirichlet where Neumann was physical |
| Validation | No mass or energy balance check, so nothing catches it |

---

## The build order

Eight steps. Full detail in `docs/TASK_DESIGN.md`.

| Step | Do | Fill in |
|---|---|---|
| **1. Lock the answer** | Compute it, and pin the *definition* of the quantity so precisely that no other reading is defensible | `golden/expected.json`, `STATE.md` |
| **2. Order the decisions** | Which method choices have to be made, and in what order | `STATE.md` |
| **3. Give each candidate a job** | Every plausible wrong number, one sentence each on why it loses | `grader/grading_guide.md` |
| **4. Plan the wrong paths** | Which method choice produces which wrong number. The modal one is your trap | `STATE.md`, `reasoning_trap.md` |
| **5. Build the files** | Inputs, reference solver, shortcut solver | `simulation/`, `solution/main.py`, `solution/shortcut.py` |
| **6. Establish discretisation independence** | Refine grid and time step until the answer stops moving; record the table | `STATE.md` → "Discretisation independence" |
| **7. Calibrate** | The gate below, then Taiga | `STATE.md` → "Calibration" |
| **8. Write the prompt** | Last, in your own words | `problem.md` |

Step 6 is the one with no inverse-task equivalent, and it is where forward tasks
are usually won or lost. See below.

---

## Step 1, restated — uniqueness is about the question

For an inverse task, uniqueness is a property of the hidden system. For a forward
task the system is fully specified, so the solution exists and is unique
automatically. What has to be argued is that **the quantity you asked for is
unambiguous.**

- "Report the drag" — ambiguous. Instantaneous? Mean? Over which cycle?
- "Report the time-averaged drag coefficient over the final two shedding
  periods" — not ambiguous.

Two competent people computing two different defensible numbers is the single
most common way a forward task fails QA. Write the definition out in `STATE.md`,
then read `problem.md` back and check it forces that definition and no other.

---

## Step 6 — discretisation independence

A forward answer is only well defined if it stops moving. Before you can set a
tolerance you have to know how much your own reference solver wobbles.

- Refine the grid until the reported quantity is stable. Record the table.
- Refine the time step likewise, if the problem is transient.
- Interpolate to the requested probe location rather than snapping to the
  nearest node, or the answer rides the grid.
- Where the value is approached rather than reached, say from which direction
  and by how much.

That measured spread is the **lower** bound on your tolerance. The distance to
the shortcut answer is the **upper** bound. If they cross, the task cannot be
graded — redesign it.

Worked example: `problems/rod-heat-forward/STATE.md`.

---

## Choosing a trap that survives refinement

Prefer a **modelling** error over a **resolution** error.

Resolution errors converge away. A model that refines far enough gets the right
answer by brute force, and your reasoning task quietly becomes a compute test.
Ask yourself: *if the model simply refines, does it get rescued?* If yes, the
trap is a speed bump.

Modelling errors don't converge away at any resolution:

- steady state where the problem is genuinely transient
- reporting a mean where the question asks for a peak, or the reverse
- the wrong boundary-condition **type**, not the wrong value
- a linearised or small-amplitude model used outside its regime
- the wrong averaging window, reference frame, or sign convention
- a default that silently disables a physical effect the regime needs

The reference fixture uses the first of these: `problems/rod-heat-forward/`
asks for a peak under periodic forcing, and the steady-state shortcut returns
the mean — 2.38 K against a true 3.00 K, wrong at every resolution.

---

## Step 7 — the gate

```bash
python3 tools/validate_problem.py my-problem-id
```

| Check | Requirement |
|---|---|
| `solution/main.py` against the inputs | **passes** |
| `solution/shortcut.py` against the inputs | **FAILS**, for the intended reason |
| Answer across grids and time steps | stable, within tolerance |
| Nothing leaks | no answer in the prompt, no mesh/solver/convergence hint |

Then Taiga, against **`docs/CALIBRATION.md`**. Forward tasks land easier — if
the first measurement is above the band, that is expected, not a surprise.
Harden with the five strategies in `docs/TASK_DESIGN.md`.

---

## The files

| File | What it is | Ships to the container? |
|---|---|---|
| `problem.md` | The prompt. Written last, your words | **Yes** (or paste into the Taiga form) |
| `simulation/**` | The inputs — **visible to the model** | **Yes** |
| `golden/expected.json` | The graded answer + tolerance | **Yes** |
| `config.yaml` | direction / domain / tool metadata | Yes, optional |
| `requirements.txt` | Pinned deps needed to run | Read by whoever builds the image |
| `grader/grading_guide.md` | Near-miss table | **No** |
| `solution/main.py` | Reference solver | **No** |
| `solution/shortcut.py` | The trap, as code | **No** |
| `reasoning_trap.md`, `BRIEF.md`, `STATE.md` | Your working record | **No** |

The solver contract is `solve(simulation_dir) -> answer`, where
`simulation_dir` is the folder holding the input files.

---

## What's different on Taiga

Two settings differ from an inverse task, and both matter:

| Field | Forward | Why |
|---|---|---|
| **Tools** | `bash` | The model has to be able to run the tool. This is the one case where a shell is correct. |
| **Tell model about uploaded files** | **ON** | It has to know the inputs exist. |

And one thing to plan for: **the published `inverse-tasks` image contains no
scientific software.** A forward task needs an image with your toolchain baked
in. Build from this repo's Dockerfile so the MCP server and the grading path
come along, and add your tool on top — `docs/TAIGA_RUNBOOK.md` §7.

`golden/` still mounts root-only, so `bash` running as uid 1000 can't read the
answer key.

---

## Pre-submission checklist

**Inputs**
- [ ] `simulation/` contains everything needed to run, and nothing else
- [ ] No reference solution, no run configuration that makes the method choice
- [ ] No comment in an input file naming the expected approach
- [ ] Every file referenced by name in `problem.md`

**Answer & grading**
- [ ] The quantity is defined unambiguously — interval, location, frame, convention
- [ ] Tolerance is wider than your reference solver's spread across grids and time steps
- [ ] Tolerance is tighter than the distance to the nearest near-miss
- [ ] The convergence table is recorded in `STATE.md`

**Code**
- [ ] `solution/main.py` runs the tool in `config.yaml` and passes
- [ ] `solution/shortcut.py` fails, and refinement does **not** rescue it
- [ ] `solution/shortcut.py` is self-contained — it must not import `main.py`
- [ ] `requirements.txt` pins every package

**Prompt**
- [ ] No hint about mesh, grid, time step, solver family, or convergence
- [ ] No "the defaults may not be sufficient"
- [ ] No method names
- [ ] Answer format explicit — units, decimal places, ordering
- [ ] `submit_answer` instruction present

**Calibration**
- [ ] `python3 tools/validate_problem.py my-problem-id` clean
- [ ] Taiga result recorded in `STATE.md` with job ids

---

## AI Use Policy

Claude may write **code**: `solution/main.py`, and a mechanical implementation
of the trap *you* wrote in `solution/shortcut.py`.

Claude may **not** write — or reformat, or proofread — `problem.md`,
`reasoning_trap.md`, `grader/grading_guide.md`, or your explanation.

**You own the science.** Full version: `docs/AI_USE_POLICY.md`.

---

## Then what

`docs/TAIGA_RUNBOOK.md` — creating the problem in Taiga, field by field, and
what to do with the result.
