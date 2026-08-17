# Reasoning trap — Gravitationally coupled coherent states

<!-- The single professional error this task is built to catch. YOU write this.
     Not shipped to the gym; it travels with the task for reviewers. -->

## The tempting shortcut

<!-- One paragraph, concrete and specific. Name the actual procedure: which
     probes, which arithmetic, which default. "Sample two convenient points far
     apart, compute the slope, round it" — not "the model might be careless".

     It must be an error a competent colleague would really make. If nobody
     would plausibly do this, the trap is a strawman and the task will not
     calibrate. -->

     The textbook approach is to apply the rotating-wave approximation and
     find the evolution of $\langle x_1 \rangle$ for the approximate
     Hamiltonian.

## Why it loses

<!-- One paragraph. What does the shortcut fail to account for, and what wrong
     answer does it therefore produce? Say what the near-miss looks like —
     ideally structurally right (correct shape, plausible magnitude) but
     numerically wrong, so it is not obviously wrong on inspection. -->

     The rotating-wave approximation is valid if the interaction frequency is
     small compared to the system frequency, i.e. $\frac{Gm}{\omega d^3} \ll \omega$.
     This does not apply for the given parameters, where both sides only differ
     by about a factor of 3.

## Why a careful solver succeeds

<!-- One paragraph. The specific reasoning step the careful solver takes that
     the naive one skips. This is the discrimination the whole task rests on. -->

<!-- REMEMBER: none of this may leak into problem.md, into the oracle's help
     text, or into any error message the model can see. -->

     A careful solver realizes the possibility that the RWA may not apply and
     solves the EOMs exactly.