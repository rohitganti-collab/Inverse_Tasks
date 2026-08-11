"""Intended solver — REFERENCE FIXTURE.

Time-marches the rod to a periodic steady state and reports the peak probe
temperature over the final drive cycle. Backward Euler on a cell-centred finite
volume grid: unconditionally stable, so the time step is an accuracy choice
rather than a stability one.

Contract: forward tasks expose `solve(simulation_dir) -> answer`, where
`simulation_dir` is the folder holding the input files. Authoring and
calibration only — never mounted under Preloaded Files.

Discretisation independence (why the tolerance in golden/expected.json is 0.01):

    ncell  steps/cycle   peak
      40         800     3.0012
     160         800     3.0017
     640         800     3.0017      <- grid-converged by ~160 cells
     320         200     2.9978
     320        1600     3.0024      <- first-order in dt, spread ~0.005

Every reasonable transient discretisation lands inside 3.00 +/- 0.01. The
steady-state shortcut lands at 2.38 — see solution/shortcut.py.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

CYCLES = 8            # enough to reach the periodic state from a cold start
STEPS_PER_CYCLE = 800


def _load(simulation_dir: Path) -> dict:
    return json.loads((Path(simulation_dir) / "rod.json").read_text())


def _operator(ncell: int, length: float, diffusivity: float):
    """Tridiagonal diffusion operator for a cell-centred grid with u=0 ends.

    Boundary cells sit half a cell from the wall, hence the 2*D/dx face weight
    there rather than D/dx.
    """
    dx = length / ncell
    centres = [(i + 0.5) * dx for i in range(ncell)]
    lower = [0.0] * ncell
    diag = [0.0] * ncell
    upper = [0.0] * ncell
    for i in range(ncell):
        w_left = 2.0 * diffusivity / dx if i == 0 else diffusivity / dx
        w_right = 2.0 * diffusivity / dx if i == ncell - 1 else diffusivity / dx
        diag[i] = (w_left + w_right) / dx
        if i > 0:
            lower[i] = -w_left / dx
        if i < ncell - 1:
            upper[i] = -w_right / dx
    return dx, centres, lower, diag, upper


def _solve_tridiagonal(lower, diag, upper, rhs):
    n = len(rhs)
    diag = list(diag)
    rhs = list(rhs)
    for i in range(1, n):
        factor = lower[i] / diag[i - 1]
        diag[i] -= factor * upper[i - 1]
        rhs[i] -= factor * rhs[i - 1]
    out = [0.0] * n
    out[-1] = rhs[-1] / diag[-1]
    for i in range(n - 2, -1, -1):
        out[i] = (rhs[i] - upper[i] * out[i + 1]) / diag[i]
    return out


def _probe(values, centres, dx, position):
    """Linear interpolation to the probe, so the answer doesn't ride the grid."""
    j = position / dx - 0.5
    lo = max(0, min(len(values) - 2, int(math.floor(j))))
    frac = j - lo
    return values[lo] * (1.0 - frac) + values[lo + 1] * frac


def solve(simulation_dir, ncell: int = 320, steps_per_cycle: int = STEPS_PER_CYCLE):
    spec = _load(simulation_dir)
    length = spec["domain_length_m"]
    diffusivity = spec["thermal_diffusivity_m2_per_s"]
    source = spec["source"]
    amplitude = source["peak_amplitude_K_per_s"]
    centre = source["centre_m"]
    half_width = source["gaussian_half_width_m"]
    period = source["drive_period_s"]
    probe_at = spec["probe_position_m"]

    dx, centres, lower, diag, upper = _operator(ncell, length, diffusivity)
    shape = [math.exp(-(((x - centre) / half_width) ** 2)) for x in centres]

    dt = period / steps_per_cycle
    implicit_diag = [1.0 / dt + d for d in diag]

    u = [0.0] * ncell
    t = 0.0
    peak = float("-inf")
    for cycle in range(CYCLES):
        for _ in range(steps_per_cycle):
            t += dt
            drive = 1.0 + math.sin(2.0 * math.pi * t / period)
            rhs = [u[i] / dt + amplitude * shape[i] * drive for i in range(ncell)]
            u = _solve_tridiagonal(lower, implicit_diag, upper, rhs)
            if cycle == CYCLES - 1:
                peak = max(peak, _probe(u, centres, dx, probe_at))
    return round(peak, 2)


if __name__ == "__main__":
    print(solve(Path(__file__).resolve().parent.parent / "simulation"))
