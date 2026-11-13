# Gap 0006 — Strategy SDK Missing Stop-Protection & Options/Level-Map Context

**Status**: open — tracked by [plan 0001](../plans/0001-elephant-edge-strategy.md)

## What's Missing

The SDK (`tantra_strategies/sdk/`) has no primitives an intraday
price-action strategy with SL/TSL and options confluence needs:

1. **No `stop_loss()` / trailing-stop primitive.** `docs/design/code-sdk.md`
   documents that the `Strategy` base deliberately has *no* `stop_loss()`
   helper and no `self.sma` sugar. `OrderRequest` has no stop field; the
   broker-agnostic order model stops at `OrderType.STOP_LIMIT/STOP_MARKET`
   with no attached SL/target/trail semantics. There is no way to express
   "entry + initial stop + ATR trail" as one unit, and no `StopUpdate` event
   for trailing-stop modifications.
2. **No level-map or options surface on `StrategyContext`.** The context
   protocol is exactly `submit / current_price / position`. A strategy cannot
   read the day's support/resistance level map (Elephant zones, OI walls,
   gamma flip, Order Blocks) or an option-chain snapshot, so options-aware
   confluence logic has no port to implement against. `SimulatedContext` is
   bars-only.

## Why

Plan 0001 (Elephant Edge EE+) requires, for every setup, an initial SL placed
beyond the level band, a TSL that trails by ATR/swing after 1R, and a
confluence score built from option-chain OI/gamma levels. Without these SDK
surfaces the strategy would have to re-implement stop math and re-invent a
level feed per strategy — violating "Consolidation Over Duplication"
(`.agents/AGENTS.md` §4.1) and making the live/backtest parity story
impossible to test with the seeded `SimulatedContext` pattern.

## How to Close It

1. `sdk/stop_protection.py` — `StopProtection` value object (`sl: Decimal`,
   `trail: TrailMode` (`off|atr|swing`), `trail_distance: Decimal`,
   `activation_after_r: Decimal`), self-validating (stop never inside the
   level band, distances ≥ 0).
2. `sdk/levels.py` — `Level`, `LevelMap`, `StrategySignal`, `PositionIntent`
   mirroring `tantra-core` plan 0003 / gap 0002 types 1:1 (Decimal, frozen
   dataclasses).
3. `sdk/strategy.py` — `Strategy.stop_loss(level_band, buffer_atr)` and
   `Strategy.trail_stop(...)` helpers; `on_stop_update(event)` lifecycle hook.
4. `sdk/context.py` — extend `StrategyContext` with `level_map()` and
   `options_snapshot(instrument, expiry)`; `SimulatedContext` gains seedable
   level/OI stores; other implementations degrade honestly (`unavailable`)
   citing the upstream gaps below.
5. Tests in `tests/` (see plan 0001 §8) with golden vectors for stop/trail
   arithmetic.

## Upstream Dependencies (cited at each workaround)

- `tantra-core` plan 0003 / gap 0002 — canonical level-map/stop domain types.
- `tantra-market` gap 0005 — Elephant/OI-wall/gamma/OB indicator feeds.
- `tantra-data` gap 0016 — option-chain snapshot persistence for backtest.

## Verification

`pytest -q` green; a `SimulatedContext` seeded with bars + a level map runs a
strategy whose `stop_loss(...)`/`trail_stop(...)` produce the golden
SL/TSL values; every level/OI read degrades to `unavailable` when unseeded.
