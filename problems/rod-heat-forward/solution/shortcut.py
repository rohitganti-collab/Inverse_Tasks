"""Shortcut solver — the modal professional error. REFERENCE FIXTURE.

The trap: treat the problem as steady state. The heater's average output is well
defined, the rod is linear, and "long after switch-on" reads like an invitation
to drop the time derivative. So the naive path solves

    -D u'' = <S>(x)

once, and reports the probe value.

That answer is the *mean* the sensor settles around, not the *maximum* it
reaches. The drive period (4 s) is comparable to the rod's diffusive relaxation
time (L^2 / (pi^2 D) ~ 2 s), so the rod tracks a large part of the swing instead
of averaging it away. Steady state returns 2.38 K; the true peak is 3.00 K.

Refining the grid does not help: the steady solve is grid-converged to four
decimal places by 40 cells and still wrong, because the error is a modelling
choice rather than a discretisation error.

Deliberately self-contained — it must not import the intended solver, or a
missing-import error would be mistaken for the trap failing honestly.

Authoring and calibration only — never mounted under Preloaded Files.
"""
from __future__ import annotations

import json
import math
from pathlib import Path


def solve(simulation_dir, ncell: int = 320):
    spec = json.loads((Path(simulation_dir) / "rod.json").read_text())
    length = spec["domain_length_m"]
    diffusivity = spec["thermal_diffusivity_m2_per_s"]
    source = spec["source"]
    amplitude = source["peak_amplitude_K_per_s"]
    centre = source["centre_m"]
    half_width = source["gaussian_half_width_m"]
    probe_at = spec["probe_position_m"]

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

    # Time-averaged source: <1 + sin(2*pi*t/P)> = 1.
    rhs = [amplitude * math.exp(-(((x - centre) / half_width) ** 2)) for x in centres]

    for i in range(1, ncell):
        factor = lower[i] / diag[i - 1]
        diag[i] -= factor * upper[i - 1]
        rhs[i] -= factor * rhs[i - 1]
    u = [0.0] * ncell
    u[-1] = rhs[-1] / diag[-1]
    for i in range(ncell - 2, -1, -1):
        u[i] = (rhs[i] - upper[i] * u[i + 1]) / diag[i]

    j = probe_at / dx - 0.5
    lo = max(0, min(ncell - 2, int(math.floor(j))))
    frac = j - lo
    return round(u[lo] * (1.0 - frac) + u[lo + 1] * frac, 2)


if __name__ == "__main__":
    print(solve(Path(__file__).resolve().parent.parent / "simulation"))
