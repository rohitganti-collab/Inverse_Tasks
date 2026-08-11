# Grading guide — driven rod, peak probe temperature

**Golden answer:** `3.0` K. Single number, absolute tolerance `0.01`.

Tolerance rationale: the spread of the intended solver across grids from 40 to
640 cells and time steps from 200 to 1600 per cycle is ~0.005 K. The nearest
labelled near-miss sits 0.62 K away. `0.01` is wider than every legitimate
discretisation and far tighter than any wrong method.

## Near-miss table

| Submitted | Looks right because | Why it loses |
|---|---|---|
| `3.00` | Transient marched to the periodic state, probe interpolated | — this is the answer |
| `2.38` | Steady state driven by the time-averaged source; converges instantly and cleanly | Reports the mean the sensor settles around, not the maximum it reaches. **This is the trap** (`solution/shortcut.py`) |
| `4.76` | Steady state driven by the peak source — an apparent upper bound | Assumes the rod equilibrates faster than the drive; it does not |
| `3.57` | Average of the two steady bounds | Not a solution of the governing equation; the true peak is set by phase lag |
| 2.7–2.9 | Transient marched, but stopped before the periodic state was reached | Cold-start undershoot; the first cycles are still climbing |
| A number in °C | Correct method, wrong units | The prompt states kelvin |

## Edge cases

- Accept a bare number or a one-element array containing it.
- Reject a range or two candidates — the prompt asks for one number.
- A value inside tolerance obtained by an obviously different route (e.g. an
  analytic Fourier solution of the same PDE) is a **pass**. The task tests the
  modelling decision, not the numerical method.
