## What it is

An adaptive moving average changes how quickly it follows price depending on market
conditions. When price trends cleanly it hugs price; when price chops it flattens. VIDYA
(Variable Index Dynamic Average) uses momentum strength as the speed dial.

## How it's calculated

```
k      = 2 / (length + 1)
cmo    = |CMO(momentum)| / 100        # 0 (sideways) .. 1 (one-directional)
VIDYA[t] = k * cmo * price + (1 - k * cmo) * VIDYA[t-1]
```

When |CMO| is near zero the effective smoothing constant collapses and the line barely
moves. Optionally the result is smoothed again with a short SMA. A plain SMA is the
non-adaptive baseline: equal weight to every bar in the window.

## How traders use it

- Trend direction by slope or by price relative to the line.
- Volatility bands (VIDYA +/- ATR multiple) to define a flip level for the trend.
- A fast-to-flat line is itself a "no trend" signal.

## Compared with

SMA and EMA have fixed speed. KAMA adapts by efficiency ratio instead of CMO. See
`concept.momentum-oscillator` for the CMO input and `concept.volume-delta` for pairing
the trend with participation.

## Pitfalls

- Parameter sensitivity: a short momentum window makes the speed dial jumpy.
- Adaptive lines can stay nearly flat for long stretches, then jump after a trend begins.
- Seeding choice affects the first bars; discard the warm-up.

## FAQ

**Why use |CMO| and not CMO?** Speed should depend on how directional the market is, not on
which direction it points.

**Is it a lagging indicator?** Yes, but the lag shrinks automatically in clean trends.
