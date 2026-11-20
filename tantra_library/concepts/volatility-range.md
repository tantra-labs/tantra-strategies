## What it is

A volatility range is a set of levels derived from ATR that holds still until price has
moved far enough to justify moving it. Predictive Ranges are the example in this library:
a center line, and inner and outer bands around it, that update in discrete steps rather
than following every tick of price.

## How it's calculated

```
step   = ATR(length) * factor
center : starts at the source price
if source - center > step:  center += step   (step up)
if center - source > step:  center -= step   (step down)
hold   = step / 2          # refreshed only on a step, otherwise frozen
r1 = center + hold   r2 = center + 2 * hold
s1 = center - hold   s2 = center - 2 * hold
```

At most one step is taken per bar, even if price jumped several steps. Because the band
width is frozen between steps, levels stay valid for many bars and can be treated as
horizontal support and resistance.

## How traders use it

- Treat s1 / r1 as first reaction zones and s2 / r2 as stretched extremes.
- Count consecutive same-direction center steps as a trend-strength reading.
- A step in the center line marks that the market covered a full ATR-multiple of distance.

## Compared with

ATR bands move with price every bar; these levels do not. Donchian channels use extremes,
these use distance. See `concept.atr`, `concept.support-resistance` and `concept.breakout`.

## Pitfalls

- A breakout re-centers the range on the same bar it happens. A study that compares the
  breakout bar against levels computed with that bar already included will never see the
  break, so studies must pin the previous bar's levels before updating.
- The factor and length are very sensitive: a factor of 6 on ATR 200 gives wide, rare steps.
- Early bars (before ATR has warmed up) have no bands.

## FAQ

**Why one step per bar?** It keeps the line deterministic and stops a gap from teleporting
the whole range.

**Does it repaint?** Not on closed bars; levels are a function of data up to that bar only.
