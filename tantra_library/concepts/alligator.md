## What it is

The Alligator is a trio of smoothed averages of the bar midpoint, each pushed forward in
time: jaw (slow), teeth (medium) and lips (fast). When they are tangled the market is
"sleeping"; when they fan out in order the market is trending.

## How it's calculated

```
median = (high + low) / 2
jaw   = RMA(median, 13) shifted 8 bars
teeth = RMA(median,  8) shifted 5 bars
lips  = RMA(median,  5) shifted 3 bars
```

The shift means the value shown at time t was computed `shift` bars earlier, so the lines
use no future data; they just respond with extra delay.

## How traders use it

- Lines ordered lips > teeth > jaw and widening: uptrend; reversed: downtrend.
- Intertwined lines: stay out, ranges dominate.
- As a proximity filter: price must reach the lines before a reversal pattern counts.

## Compared with

A multi-moving-average ribbon has similar logic without the forward shift. See
`concept.reversal-bar` and `concept.adaptive-ma`.

## Pitfalls

- Heavy lag: by design signals arrive late in trends.
- Warm-up: the jaw needs 13 bars plus its shift before it exists.
- Whipsaws in sideways markets despite the "sleeping" heuristic.

## FAQ

**Are the shifts repainting?** No; the shift delays the line, it does not peek forward.

**Can I change the lengths?** Yes; the defaults are 13/8/5 and 8/5/3.
