# 0008 — Recipe stop/target exits fill at bar close

**Status**: open

## What's stubbed or hardcoded
`tantra_strategies/strategies/predictive_ranges.py` (`PrTrendPullbackStrategy`, `PrVidyaBreakoutStrategy`)
detect stop and target hits on a closed bar and exit with a market order at that bar's CLOSE, not at the
stop/target price. Backtest R-multiples are therefore distorted (slippage past the level is baked in, and
intrabar touches that reverse are missed or mis-priced).

## Why
The SDK `SimulatedContext` has no intrabar fill model for resting stop/limit orders at a given price; the
recipes were implemented (root plan 0016, T22.4) without it so they could ship deterministically.

## How to close it
Place SDK stop orders (`Strategy.stop_loss` / stop-limit exits) and have `SimulatedContext` fill them intrabar
at the stop/target price (gap-through bars fill at the open), then update the recipes to use them and add
tests comparing fills to the level. Remove the bar-close exit path and this gap.
