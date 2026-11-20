## What it is

A breakout is a decisive move beyond a level that previously held price. The belief is
that the level's failure releases pent-up orders and the move continues.

## How it's calculated

Close-based break against pinned levels:

```
break_up   : close > r1_prev  and the center did not step on this bar
break_down : close < s1_prev  and the center did not step on this bar
```

The level must be the value from before the current bar. With predictive ranges the
breakout itself re-centers the range on the same bar; comparing against the freshly
recomputed r1 would move the goalposts and the break would never register. Studies must
therefore pin the previous bar's levels first. A step event is a second kind of breakout:
the center moved a full ATR multiple.

## How traders use it

- Require a trend filter and volume-delta agreement (for example delta >= +30).
- Stop at the last confirmed swing pivot, or one ATR beyond the pinned level.
- Target a multiple of risk such as 1.5R.

## Compared with

Pullback entries wait for a retest. Channel breakouts (Donchian) use extremes rather than
distance bands. See `concept.volatility-range`, `concept.volume-delta` and `concept.r-multiple`.

## Pitfalls

- False breakouts are the norm in ranges; the close requirement reduces but does not
  remove them.
- Tick volume in spot FX and gold makes delta filters unreliable.
- Look-ahead: acting on a close before the bar has closed.

## FAQ

**Why close rather than touch?** Wicks through a level are common; closes are more telling.

**What if price gaps far beyond the level?** The entry price and risk widen; size down.
