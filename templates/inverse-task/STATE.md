# STATE — Gravitationally coupled coherent states

<!-- Your authoring record. Sections follow the build order in INSTRUCTIONS.md.
     Not shipped to the gym — it exists so you keep the build straight and so a
     reviewer can follow your reasoning. -->

state: BRIEFED

## Why this is the only answer

<!-- Step 1. The uniqueness argument. Fix the hidden ground truth, then write
     down why NO OTHER ANSWER IS POSSIBLE. This is the load-bearing section of
     the whole task.

     If you cannot prove uniqueness, stop and pick a different setup. If this
     section keeps changing while you build, the task is not stable yet. -->

     The Hamiltonian is given. The evolution of the expectation values can be
     derived exactly, cf. arXiv:2410.21009 sec. II.B. For the given input state,
     we have $a_R = a_I = b_I = 0$ and
     $$ \langle x_1 \rangle = \langle x_- \rangle \propto \cos \Omega_- t $$
     where $\Omega_- = \omega \sqrt{1-2\delta}$ with
     $\delta = \frac{Gm}{\omega^2 d^3}$. Since the parameters $\omega$, $d$, and
     the constant $G$ are given, knowing $\Omega_-$ amounts to knowing $m$.
     The task then boils down to sampling $\langle x_1 \rangle$ for multiple
     times to extract the frequency.

     For any $f(t) = a \cos(bt)$ with $a \neq 0$ and $b \geq 0$, the
     coefficients $a$ and $b$ are uniquely determined by four values
     $f(0) = a, f(T), f(\sqrt{2}T), f(\sqrt{3}T)$ for any $T>0$. To show this,
     suppose $b' \neq b$ gave the same values, then we have:
     $b' t_i = \sigma_i b t_i + 2\pi n_i$, where for $i \in \{1,2,3\}$
     $t_i = \sqrt{i}T$, $n_i$ are integers and $\sigma_i \in \{\pm 1\}$.
     Hence $\sigma_j = \sigma_k$ for some $j \neq k$, and for this combination
     we have $n_j/t_j = n_k/t_k$. This is only possible for $n_j = n_k = 0$,
     since otherwise we would have a rational ratio equal to a ratio that can
     only be irrational, $n_j/n_k = t_j/t_k$. Thus, $b' = \pm b$ and there can
     only be one $b \geq 0$.

## Order of decisions

<!-- Step 2. What must be measured or known first? What does it unlock? Where
     does validation belong? This becomes the intended solution path, and
     solution/main.py should follow it step for step. -->

     Measuring $\langle x_1 \rangle$ at the four values
     $t \in \{0,T,\sqrt{2}T,\sqrt{3}T\}$ allows us to extract the frequency
     $\Omega_-$ in $\langle x_1 \rangle \propto \cos \Omega_- t$.
     Using the given values for $\omega$, $d$, and $G$, we find $m$ from
     $\Omega_- = \omega \sqrt{1-2\delta}$ with $\delta=\frac{Gm}{\omega^2 d^3}$.

## Near-misses

<!-- Step 3. Every wrong answer a COMPETENT colleague might produce, and why
     each is tempting. At least one must look structurally correct — right
     shape, wrong number.

     Also record the distance from the correct answer to the nearest near-miss:
     your tolerance has to be tighter than that. -->

     Using the rotating-wave approximation, one obtains
     $\Omega_- = \omega (1-\delta)$ instead of the correct
     $\Omega_- = \omega \sqrt{1-2\delta}$. This single mistake shifts the final
     answer from $m = 5.00\ \mathrm{\mu g}$ to $m = 6.34\ \mathrm{\mu g}$.

## The trap

<!-- Step 4. Of the near-misses above, the single most common professional
     error. This is what the task actually tests, what shortcut.py implements,
     and what ≥60% of failures should land on. -->

     Using the rotating-wave approximation, one obtains
     $\Omega_- = \omega (1-\delta)$ instead of the correct
     $\Omega_- = \omega \sqrt{1-2\delta}$. This single mistake shifts the final
     answer from $m = 5.00\ \mathrm{\mu g}$ to $m = 6.34\ \mathrm{\mu g}$.

## Budget

<!-- Step 6. The number, and the arithmetic behind it: how many probes does the
     intended path need, how many does the shortcut need, and why does brute
     force not fit? -->

     4 -- as shown above we need to sample 4 points to determine the
     coefficients a and b in $f(t) = a \cos(bt)$.

## Calibration

<!-- Step 7. Record the measured numbers, not intentions:
     intended solver     __/32
     shortcut solver     __/32   (must be 0)
     pass rate           ____    (target 0.15-0.40, ideally ~0.30)
     checkpoints tested  ____    (>=3)
     failures on the named near-miss  ____%   (must be >=60%) -->

## Notes

<!-- state sequence: BRIEFED -> LOCKED -> NEAR-MISSES -> SPECED -> CALIBRATED -> READY -->
