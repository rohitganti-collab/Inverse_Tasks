# Reasoning trap

## The trap

The setup reads like a steady-state problem. The rod is linear, both ends are
pinned at a fixed temperature, the heater's average output is a well-defined
function of position, and the question says "long after switch-on" — which in
most textbook framings means "once the transient has died away." The natural
move is to drop `du/dt`, solve `-D u'' = <S>(x)` once, and read off the probe.

That is a five-line tridiagonal solve, it converges immediately, it is stable at
any grid resolution, and it produces a confident, well-conditioned, physically
sensible number: 2.38 K.

It is the wrong number, because the transient never dies away. The source keeps
driving, so the rod settles into a *periodic* state, not a static one, and the
question asks for the maximum of that oscillation rather than its mean.

## Why a careful solver succeeds

Two things have to line up. First, noticing that "the highest temperature the
sensor ever reads" is a property of the oscillation, not of its average — so the
time derivative cannot be dropped. Second, checking whether the rod is fast
enough to follow the drive: the diffusive relaxation time over this rod is
`L^2 / (pi^2 D)` ~ 2 s against a 4 s drive period, so the rod tracks a large
part of the swing and neither of the two easy bounds (steady-with-mean-source at
2.38 K, steady-with-peak-source at 4.76 K) is close.

A solver that marches in time from the stated cold start, runs long enough for
the cycles to repeat, and interpolates to the probe position gets 3.00 K on any
reasonable grid.
