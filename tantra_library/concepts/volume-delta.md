## What it is

Volume delta estimates who was more aggressive: buyers or sellers. Without tick-by-tick
trade data, bar-level delta labels each bar's whole volume as "up" or "down" by candle
direction and compares the two totals.

## How it's calculated

```
up_volume   = volume if close > open else 0
down_volume = volume if close < open else 0
delta_pct (average) = 100 * (up - down) / (total / 2)
delta_pct (total)   = 100 * (up - down) / total
```

Averaging normalises to half the total so a perfectly one-sided window reads +/-200,
whereas total normalisation caps at +/-100. Windows can be rolling or reset at an event
such as a trend flip.

## How traders use it

- Confirm a trend: a rising trend with positive delta has participation behind it.
- Spot absorption: heavy volume without progress in price.
- Gate breakouts: require a minimum delta (for example +30) before taking one.

## Compared with

On-balance volume accumulates signed volume without a window. True order-flow delta
needs bid/ask classified trades. See `concept.adaptive-ma` and `concept.breakout`.

## Pitfalls

- Data quality: spot FX and gold feeds report tick count, not real volume. Delta from tick
  volume is a proxy only, so this library refuses real-volume entries on tick sources.
- Bar-direction classification mislabels bars that open high and close slightly lower on
  net buying.
- Normalisation choice changes the scale of every threshold.

## FAQ

**Can I use it on futures and equities?** Yes; those carry real exchange volume.

**Why reset at a flip?** It measures participation in the current move, not the history.
