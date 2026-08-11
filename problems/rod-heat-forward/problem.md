# Task setup

A one-dimensional rod of length 1.0 m conducts heat with a uniform thermal
diffusivity. Both ends are held at 0 K. The rod started at 0 K everywhere.

A heater is embedded in the rod. Its output is not constant: it rises and falls
smoothly and repeatedly, and it has been doing so since the rod was switched on.
The exact geometry, amplitude, and drive of the heater — along with the
diffusivity and the boundary conditions — are given in `simulation/rod.json`.

The temperature field obeys

```
du/dt = D * d2u/dx2 + S(x, t)
```

with `D` the thermal diffusivity and `S(x, t)` the heater term written out in
the input file.

# What you can use

The input file is under `simulation/`. You have a shell. Use whatever numerical
approach you consider appropriate.

# Your task

A sensor sits at the probe position given in the input file. Long after switch-on
— once the rod's response has settled into the same repeating pattern cycle after
cycle — report **the highest temperature that sensor ever reads**, in kelvin.

# Output format

A single number: the temperature in kelvin, rounded to 2 decimal places.

Submit your answer via `submit_answer(answer)`.
