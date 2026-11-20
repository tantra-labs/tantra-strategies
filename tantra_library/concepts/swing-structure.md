## What it is

Swing structure reads the market as a sequence of confirmed turning points: higher highs
and higher lows in an uptrend, lower highs and lower lows in a downtrend. Pivots are the
raw material; rolling highest and lowest values give the enclosing extremes.

## How it's calculated

```
pivot high at bar i : high[i] is the maximum of bars i-left .. i+right
pivot low  at bar i : low[i]  is the minimum of bars i-left .. i+right
```

The pivot becomes known only `right` bars after bar i, when the right-hand window closes.
`Highest(n)` and `Lowest(n)` are simply the maximum and minimum of the last n values.

## How traders use it

- Stop placement just beyond the last confirmed pivot against the position.
- Trend definition: sequence of pivot highs and lows.
- Breakout levels: the highest high of the last n bars.

## Compared with

Fractals are pivots with left = right = 2. Zig-zag filters pivots by a minimum size;
pivots here use a fixed window instead. See `concept.support-resistance` and
`concept.reversal-bar`.

## Pitfalls

- Confirmation delay: signals tied to a pivot are always late by `right` bars.
- Do not plot a pivot back at bar i and then trade as if it was visible on bar i.
- Left and right windows trade sensitivity for noise.
- The most recent swing is always unconfirmed.

## FAQ

**Which left / right?** 5/5 suits swings on intraday charts; use 2/2 for fractals.

**Why is my pivot value empty?** Until `right` bars pass, nothing is confirmed.
