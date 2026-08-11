# STATE — driven rod, peak probe temperature

> **Reference fixture — do not submit this as your authored task.** It exists so
> you can see a complete, validator-clean *forward* task before writing your
> own, and so the engine has a forward problem to regression-test against.
> It has **not** been calibrated on Taiga; see "Calibration" below.

## Why this answer is the only answer

The governing equation, the diffusivity, the boundary conditions, the initial
condition, the source term, and the probe position are all fully specified in
`simulation/rod.json`. A linear parabolic PDE with fixed Dirichlet data and a
periodic forcing has a unique solution, and that solution approaches a unique
periodic state whose maximum at a fixed point is a single number. Nothing about
the answer depends on the numerical scheme chosen — only on getting the physics
right.

The reported quantity is the maximum over one full drive cycle of the settled
response, at the probe, in kelvin, rounded to 2 decimal places: **3.00 K**.

## Order of decisions

1. Recognise that the source is time dependent and the question asks for a
   *maximum*, not an average — so the transient response is required.
2. Confirm the rod has reached the periodic state before sampling (start from
   the stated cold initial condition and run several drive periods).
3. Discretise: any stable scheme works. Backward Euler is convenient because the
   time step becomes an accuracy choice rather than a stability one.
4. Check the answer is independent of grid and time step before committing.
5. Interpolate to the probe position rather than reporting the nearest cell,
   or the answer rides the grid.

## Candidate jobs

| Candidate | Why it is tempting | Why it loses |
|---|---|---|
| **2.38** (steady state with the mean source) | The rod is linear, the mean source is well defined, and "long after switch-on" sounds like steady state | Reports the mean the sensor settles around, not the maximum it reaches |
| **4.76** (steady state with the *peak* source) | Treats the rod as quasi-static and instantaneously in equilibrium with the source | The rod's relaxation time is comparable to the drive period, so it never comes close to catching the peak |
| **3.57** (mean of the two steady solves) | Looks like a defensible compromise, and lands near the right magnitude | Not a solution of anything; the true peak is set by the phase lag, not by averaging two bounds |
| Peak sampled before the rod settles | Time marching stopped too early | The first cycles undershoot from the cold start |

## Wrong paths catalogue

- Dropping `du/dt` → the steady shortcut, `solution/shortcut.py`, 2.38 K.
- Averaging the transient instead of taking the maximum → also 2.38 K, arriving
  from the other direction.
- Sampling the nearest cell centre instead of interpolating → answer moves with
  the grid; at coarse resolutions it drifts outside tolerance.

## Discretisation independence

Measured with `solution/main.py`:

| cells | steps/cycle | peak |
|---|---|---|
| 40 | 800 | 3.0012 |
| 160 | 800 | 3.0017 |
| 640 | 800 | 3.0017 |
| 320 | 200 | 2.9978 |
| 320 | 1600 | 3.0024 |

Spread across reasonable discretisations is ~0.005. Distance to the nearest
near-miss is 0.62. Tolerance is set at **0.01** — comfortably wider than the
scheme spread, sixty times tighter than the trap.

## Calibration

**Not calibrated.** No Taiga job has been run against this problem, so it has no
measured pass rate, no failure histogram, and no concentration score. It is a
structural reference, not a training task. A real forward task must clear the
gate in `docs/CALIBRATION.md` before it ships — and forward tasks tend to run
*easier* than inverse ones, so budget for extra hardening.
