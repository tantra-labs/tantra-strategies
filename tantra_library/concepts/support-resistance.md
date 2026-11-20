## What it is

Support and resistance are price levels where past activity suggests buyers or sellers
will react again. Levels can come from swing pivots, round numbers, prior highs and
lows, or distance-based constructions such as predictive ranges.

## How it's calculated

This library supplies three level sources:

```
swing pivot    : bar whose high (low) is the max (min) of left + right neighbours
range bands    : center +/- n * (ATR * factor / 2), frozen between steps
rolling extreme: Highest / Lowest over a window
```

A touch is `low <= support` or `high >= resistance` on the bar; a break is a close beyond
the level.

## How traders use it

- Fade first touches in a ranging market.
- Buy dips into support only when the higher timeframe trend agrees.
- Treat a decisive close through a level as a regime change or breakout entry.

## Compared with

Moving averages are dynamic levels; pivots and bands are horizontal. See
`concept.volatility-range`, `concept.swing-structure` and `concept.breakout`.

## Pitfalls

- Levels are zones, not lines: wicks routinely overshoot.
- A pivot is only confirmed `right` bars late; using it earlier is look-ahead.
- A level touched many times is weaker, not stronger.
- Levels that move with the current bar (re-centered ranges) must be pinned beforehand.

## FAQ

**Which source is best?** None dominates; choose one and test it.

**How wide is a zone?** A fraction of ATR is a sensible starting width.
