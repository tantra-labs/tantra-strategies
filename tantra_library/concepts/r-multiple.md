## What it is

R is the amount risked on a trade: the distance from entry to stop. An R-multiple states
profit or loss as a multiple of that unit, so a trade that gains twice what it risked is
+2R regardless of price level or position size.

## How it's calculated

```
risk   = |entry - stop|
target = entry + k * risk        (long, k = reward multiple)
R      = (exit - entry) / risk   (long; invert sign for shorts)
```

Position size follows from the cash you accept to lose per trade:
`size = risk_cash / risk` in price units.

## How traders use it

- Compare strategies on a common scale.
- Set targets at fixed multiples such as 1.5R.
- Compute expectancy: `win_rate * avg_win_R - loss_rate * avg_loss_R`.

## Compared with

Percentage return depends on price level; R depends on the stop. See `concept.atr`
for volatility-based stops and `concept.swing-structure` for structure-based stops.

## Pitfalls

- Tiny stops inflate R-multiples; slippage and spread then dominate.
- Gaps through the stop produce losses worse than -1R.
- Target multiples fixed in advance can cap trend winners.
- Costs should be included in realised R.

## FAQ

**What is a good expectancy?** Anything consistently positive after costs, which needs a
large sample to establish.

**Is 1.5R a recommendation?** No, it is a default used by the sample recipe.
