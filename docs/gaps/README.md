# Gap Index — `tantra-strategies`

Per workspace rule `.agents/rules/gap-tracking.md`:
- **Gaps** (`docs/gaps/XXXX-*.md`): individual missing features, stubs, or
  cross-repo dependencies.
- **Plans** (`docs/plans/XXXX-*.md`): collections of gaps.
- Numbering is per-repo, sequential, never reused.

Dismantled from the former `docs/roadmap/` directory: every completed milestone
now lives in [`docs/design/`](../design/architecture.md) +
[`docs/design/implementation-record.md`](../design/implementation-record.md);
the remaining future work is enumerated below.

## Open Gaps

| # | Title | Plan |
|---|-------|------|
| [0008](0008-recipe-exits-at-bar-close.md) | Predictive Range recipe strategies exit stop/target hits at bar close, not at the stop/target price | root plan 0016 |

## Closed Gaps

| # | Title | Closed In |
|---|-------|-----------|
| 0007 | `signal.alpha30_factor` step manifest is declarative-only (validated, not runnable) — runnable catalog strategies `equal_weight` + `alpha30_factor` (SDK `Strategy` subclasses + harness-loader `strategy.py`/`config.toml`/`step.toml` in the loader layout, registered in `registry.json`); un-skips tantra-examples `test_07_alpha30_backtest.py` (T17.6) | 2026-11-17 |
| 0001 | `Strategy.on_tick` declared but never dispatched — `Tick` model + `Strategy.run_ticks` / `SimulatedContext.run_ticks` / `LiveContext.run_ticks` dispatch (T8.1) | 2026-11-14 |
| 0002 | No live/feed-backed `StrategyContext` in-repo (only `SimulatedContext`) — `LiveContext` + `MarketDataFeed`/`ExecutionGateway` seams in `sdk/live.py`, sim/live parity tests (T8.2) | 2026-11-14 |
| 0003 | Catalog `step.toml` is declarative-only — in-repo executor `tools/run_step.py` proves every step runs deterministically on `SimulatedContext` (T8.3) | 2026-11-14 |
| 0004 | No `BasketManifest`-driven run loop in-repo — `basket_run.run_basket` resolves members, sizes by `optimize_allocations`, enforces the `RiskBudget` (T8.4) | 2026-11-14 |
| 0005 | Basket `RiskBudget` is a Phase-1 simple cap; no allocation optimizer — `optimize_allocations` cap math + run-loop enforcement; full `tantra-ledger-allocation` optimizer remains cross-repo (T8.5) | 2026-11-14 |
| 0006 | SDK has no stop-loss/trailing-stop primitive and no level-map/options context surface | 2026-11-14 (plan 0001 §7): `sdk/stop_protection.py` + `sdk/levels.py` + `Strategy.stop_loss`/`trail_stop`/`on_stop_update` + `StrategyContext.level_map`/`options_snapshot` with seedable `SimulatedContext` stores; honest `LevelsUnavailable`/`OptionsUnavailable` degradation citing market 0005 / data 0016 |
