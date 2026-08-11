# AI Use Policy

**You own the reasoning. Claude writes the code.**

This is not a style preference. The scientific claim a task rests on — that this
answer is the only answer, that a competent practitioner fails in this specific
way — is the thing being bought. A model can produce text that looks like that
claim without the professional experience that makes it true, and the failure is
invisible until a reviewer tries to re-derive it.

---

## The division

| Artefact | Owner | Why |
|---|---|---|
| The hidden answer + uniqueness argument | **You** | The scientific claim the task rests on |
| The near-miss taxonomy (`grader/grading_guide.md`) | **You** | Requires having watched real analyses fail |
| The reasoning trap (`reasoning_trap.md`) | **You** | It *is* the insight the task tests |
| The solver-facing prompt (`problem.md`) | **You** | Model-drafted prompts leak method |
| Your explanation / context for the reviewer | **You** | |
| `oracle/setup.py` | Claude, to your spec | Engineering to specification |
| `solution/main.py` | Claude, to your spec | Engineering to specification |
| `solution/shortcut.py` | Claude, from **your** trap | Mechanical implementation of a trap you wrote |
| Custom `grader/grade.py` | Claude, you validate | Generated, then run against your ground truth |

---

## The parts people get wrong

**Formatting counts as writing.** Claude may not clean up, reformat, proofread,
or "tighten" `problem.md`, `reasoning_trap.md`, or the grading guide. A prompt
that has been through a model reads like one, and the tells are exactly the
things that leak: helpfully signposted structure, a summarising sentence that
gestures at the approach, vocabulary borrowed from the method. Grammar is your
responsibility. Imperfect prose in your own voice is the deliverable.

**The trap is yours, then Claude implements it.** Ask Claude to invent the trap
and you get the plausible-sounding error rather than the one practitioners
actually make. Write the trap in `reasoning_trap.md` first, in your own words,
then hand it over to be turned into `solution/shortcut.py`.

**Specify, don't delegate.** "Write me an oracle for enzyme kinetics" produces
something generic. "The oracle exposes `assay(substrate_uM, inhibitor_uM,
replicates)`; velocity follows competitive inhibition with these hidden
constants; replicates average down gaussian noise at 3% relative and each costs
one unit of a 12-unit budget; `help` lists signatures only" produces the thing
you meant. You are the specification; Claude is the typist.

**Review what comes back.** You are accountable for the oracle even though you
didn't type it. Read it. Check it returns observations and not judgments, that
nothing hands back a hidden parameter, that the noise is seeded, that the budget
is enforced. `python3 tools/validate_problem.py` catches a lot of this, and not
all of it.

---

## Why the prompt in particular

The prompt is the only thing the model sees, and everything about task
difficulty lives in what it declines to say. A model drafting that text has no
way to know which omissions are load-bearing. It will help — by naming the
quantity that matters, by hinting at the order of operations, by explaining what
a measurement is *for*. Each of those is the task, given away.

Write it last, in your own words, after the answer is locked and the shortcut is
proven to fail. Then read it back and ask: could a smart colleague who read only
this fall into my trap about a third of the time? If not, either the prompt says
too much or the trap isn't tempting.

---

## Provenance

Record who wrote what, per task. If you used Claude for the oracle and the
solvers, say so in `STATE.md`. Nobody is trying to catch you out — the point is
that a reviewer can tell which claims carry a human's professional judgement
behind them and which are engineering.
