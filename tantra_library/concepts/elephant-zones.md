## What it is

Elephant Zones are session-anchored support and resistance bands. Two support bands (s1, s2)
sit below the session open and two resistance bands (r1, r2) above it. Each band is the level
price plus or minus a half width of half an ATR.

## How it's calculated

A session is one IST day (intraday horizon). Once two or more sessions have completed, the
levels use nearest-rank percentiles of past sessions' excursions from their open:

```
s1 = open - P25(open - session low)     s2 = open - P35(...)
r1 = open + P63(session high - open)    r2 = open + P74(...)
```

During warm-up (fewer than two completed sessions) the levels come from the session's first
bar with golden-ratio multiples: anchor = first close, range = first high - low,
s1/r1 = anchor -/+ 1.618 * range and s2/r2 = anchor -/+ 2.618 * range. All arithmetic is
Decimal.

## How to read it

A sweep is a bar whose wick pierces the outer edge of the s1 (or r1) band and closes back
inside. Stops can sit beyond the band with an ATR buffer (see `prim.outer-buffer-stop`).
Levels only use data up to the current bar: there is no lookahead.
