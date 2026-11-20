## What it is

A reversal bar is a single candle that pokes beyond the recent run, then closes back in
the opposite half of its own range. It records a failed push and a possible turn.

## How it's calculated

For a bullish bar, after `lookback` earlier bars made progressively lower highs:

```
mid = (high + low) / 2
bullish = close > mid
          and low < min(low of previous lookback bars)
          and highs of previous bars strictly descending
```

The bearish bar is the mirror image with higher lows. Optionally the bar must reach the
Alligator (high above the lowest line for a bullish bar) and the Awesome Oscillator must
be turning against the prior move. The trigger is the bar's high (bullish) or low (bearish).

## How traders use it

- Entry on a break of the trigger level on the next bar.
- Stop beyond the extreme of the reversal bar.
- Combined with a trend filter so only with-trend reversals (pullback ends) are taken.

## Compared with

Pin bars and engulfings are looser candle patterns. See `concept.alligator`,
`concept.trend-pullback` and `concept.swing-structure`.

## Pitfalls

- The signal is known only at bar close; acting inside the bar repaints.
- Rules here are reconstructed from a public description; volume "squat" filters are not
  implemented.
- Counter-trend reversal bars in a strong trend fail often.

## FAQ

**How many bars of lookback?** Three is the default; higher values give rarer signals.

**Is the Alligator filter required?** It is on by default, and removable by parameter.
