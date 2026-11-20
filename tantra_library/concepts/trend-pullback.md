## What it is

A trend pullback is a temporary move against an established trend into a level where
buyers (or sellers) tend to re-engage. The idea is to join the trend at a better price
than a breakout would give, with a nearby invalidation point.

## How it's calculated

A pullback setup has three parts that this library expresses as detectors:

```
regime  : N consecutive same-direction center steps (det.pr-trend-regime)
location: bar touches the inner band against the trend (det.pr-zone-touch)
trigger : reversal bar closes back with the trend (det.reversal-bar)
```

Entry is on a break of the reversal bar's extreme, stop beyond the outer band or the bar
extreme (padded with an ATR fraction), target the opposite inner band.

## How traders use it

- Wait for a trend to prove itself with two or more steps.
- Enter only when location and trigger agree on the same bar.
- Skip the trade when the stop distance is too large to give a workable reward ratio.

## Compared with

Breakout entries buy strength; pullback entries buy weakness. See `concept.breakout`,
`concept.r-multiple` and `concept.reversal-bar`.

## Pitfalls

- The first pullback after a long run is often a trend end rather than a dip.
- Detectors that use the current bar's re-centered levels will mislabel touches; use
  pinned previous-bar levels.
- Strong trends may never pull back, so entry rates are low.

## FAQ

**How deep may a pullback go?** Past the outer band, the thesis is invalid.

**Can this run on any market?** Yes, but the volume-free version suits FX and gold best.
