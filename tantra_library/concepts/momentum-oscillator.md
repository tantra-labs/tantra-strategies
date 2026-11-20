## What it is

A momentum oscillator condenses recent price changes into one number that swings around
a neutral level. It tells you how strongly and in which direction price has been moving,
not where price is.

## How it's calculated

Chande Momentum Oscillator (CMO) over n values:

```
su = sum of positive changes     sd = sum of |negative changes|
CMO = 100 * (su - sd) / (su + sd)       # range -100 .. +100
```

Awesome Oscillator (AO) is a difference of averages of the bar midpoint:

```
AO = SMA(median, fast) - SMA(median, slow)      # median = (high + low) / 2
```

Linear-regression slope is a third variant: the fitted slope of the last n values.

## How traders use it

- Zero-line crosses as a momentum-direction change.
- Extremes (CMO beyond +/-50) as stretched conditions.
- Turning points (AO shrinking while still positive) as early warning of fading push.
- As the speed input to adaptive averages.

## Compared with

RSI scales gains against losses with smoothing; CMO uses raw sums. See `concept.adaptive-ma`
and `concept.reversal-bar`, which can use an AO turn as a filter.

## Pitfalls

- "Overbought" is not a sell signal in a strong trend; the oscillator can stay pinned.
- Divergences are subjective and only visible in hindsight.
- Short windows are noisy, long windows lag.

## FAQ

**CMO or RSI?** They agree in direction; CMO is more sensitive since it does not smooth.

**Can AO be used on any timeframe?** Yes, but the 5/34 defaults were designed for daily bars.
