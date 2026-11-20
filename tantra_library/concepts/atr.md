## What it is

Average True Range (ATR) answers one question: how far does this market typically move
in a single bar? It ignores direction and only measures distance, which makes it the
workhorse for sizing stops, filtering quiet markets and scaling other indicators.

## How it's calculated

Each bar's true range is the largest of three distances:

```
TR = max(high - low, |high - prev_close|, |low - prev_close|)
```

The gap terms matter: an overnight gap that never trades inside the bar is still range
a stop would have felt. ATR then smooths TR with Wilder's running average (RMA):

```
ATR[t] = (ATR[t-1] * (n - 1) + TR[t]) / n
```

The first value is seeded with the plain mean of the first n true ranges.

## How traders use it

- Stop distance: place a stop 1.5 to 3 ATR from entry so normal noise does not trigger it.
- Position size: risk a fixed amount divided by ATR-based stop distance.
- Regime filter: skip breakout entries when ATR is far below its own recent average.
- Band construction: add or subtract a multiple of ATR from a price to get an envelope.

## Compared with

`concept.volatility-range` turns ATR into frozen, stepped bands. Standard deviation
measures dispersion around a mean and reacts more to a single outlier than ATR does.

## Pitfalls

- ATR is in price units, so values are not comparable across instruments; use ATR / price.
- A long length lags a volatility regime change; a short one is noisy.
- Needs `n` bars of warm-up; early values are undefined and must not be traded.
- Gaps inflate ATR for many bars afterwards.

## FAQ

**Which length should I use?** 14 is the convention; 200 gives a slow, structural scale.

**Does ATR predict direction?** No. It only describes size of movement.

**Is Wilder smoothing the same as an EMA?** It is an EMA with alpha = 1/n, so it is slower
than the usual 2/(n+1) EMA of the same length.
