# Inverse Tasks — gym problem pack

Minimal problem surface for packaging into **core_gym**.

This branch deliberately excludes Taiga MCP hooks (`setup_problem` /
`grade_problem`), Docker runtime, expert calibration notes, and reference
solvers. The gym owns setup and grading; each problem only ships its oracle
runtime surface.

## Layout

```
problems/
  <problem-id>/
    problem.md           # task prompt shown to the model
    oracle/setup.py      # hidden Oracle with stable query(...) contract
    golden/expected.json # { "answer": ..., "tolerance": N }
```

Drop additional problem folders beside `modular-black-box` using the same
three-file contract.

## Included sample

| Problem ID | Domain | Extra Python deps |
| --- | --- | --- |
| `modular-black-box` | modular arithmetic inverse | **none** (stdlib only) |

## Oracle contract

```python
from oracle.setup import Oracle

oracle = Oracle()                 # fresh instance per attempt
oracle.query("help")              # free; lists modes + budget
oracle.query("evaluate", x=0)     # budgeted observation
```

- Hidden ground truth lives only inside `oracle/setup.py`.
- `query(mode, **params)` is the stable probe API.
- Budget is enforced inside the Oracle (sample: 6 evaluate calls).
- Returns observations only — never judgments or the hidden parameters.

## Golden answer

```json
{ "answer": [23, 58], "tolerance": 0 }
```

`tolerance` is absolute per numeric element (`0` = exact match).

## Specialized libraries

Current sample needs **no packages beyond the Python stdlib**.

If later problems need libraries beyond `numpy` / `scipy`, list them here
(or in a short note next to that problem folder) so they can be added to the
gym image.
