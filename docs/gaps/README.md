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
| [0009](0009-live-context-parity.md) | Wheel bridge/LiveContext break research-live parity: private simulator, no fill events, no cancel/resync | [0006](../plans/0006-design-review-2026-11.md) |
| [0010](0010-order-request-idempotency-key.md) | `OrderRequest` has no client order id; `SIM-n` counters | [0006](../plans/0006-design-review-2026-11.md) |
| [0011](0011-sizing-and-helper-duplication.md) | Duplicated sizing, percentile and IST helpers across strategies | [0006](../plans/0006-design-review-2026-11.md) |
| [0012](0012-typed-validated-parameters.md) | `Parameter` untyped/unvalidated; unknown overrides and floats accepted | [0006](../plans/0006-design-review-2026-11.md) |
| [0013](0013-sdk-library-import-cycle.md) | Import cycle between `tantra_strategies.sdk` and `tantra_library` | [0006](../plans/0006-design-review-2026-11.md) |
| [0014](0014-library-provenance-and-licensing.md) | Library provenance and licence labelling (attribution, SPDX, NOTICE) | [0006](../plans/0006-design-review-2026-11.md) |
| [0015](0015-promotion-evidence-digest.md) | Promotion evidence not bound to code, params or data snapshot | [0006](../plans/0006-design-review-2026-11.md) |
| [0016](0016-package-data-and-py-typed.md) | Manifests/catalog not packaged; no `py.typed` | [0006](../plans/0006-design-review-2026-11.md) |
| [0017](0017-dependency-pins-and-wheel-contract.md) | Dependency pins and wheel version contract | [0006](../plans/0006-design-review-2026-11.md) |
| [0018](0018-simulated-context-fill-model.md) | `SimulatedContext` fills at close without tick rounding, fees or slippage | [0006](../plans/0006-design-review-2026-11.md) |

## Closed Gaps

| # | Title | Closed In |
|---|-------|-----------|
| 0008 | Predictive Range recipe exits filled at bar close — SDK STOP_MARKET + OCO `Strategy.bracket`, `SimulatedContext` intrabar stop/target fills (gap-through at open, stop wins ties) | 2026-11-20 |
| 0007 | `signal.alpha30_factor` step manifest is declarative-only (validated, not runnable) — runnable catalog strategies `equal_weight` + `alpha30_factor` (SDK `Strategy` subclasses + harness-loader `strategy.py`/`config.toml`/`step.toml` in the loader layout, registered in `registry.json`); un-skips tantra-examples `test_07_alpha30_backtest.py` (T17.6) | 2026-11-17 |
| 0001 | `Strategy.on_tick` declared but never dispatched — `Tick` model + `Strategy.run_ticks` / `SimulatedContext.run_ticks` / `LiveContext.run_ticks` dispatch (T8.1) | 2026-11-14 |
| 0002 | No live/feed-backed `StrategyContext` in-repo (only `SimulatedContext`) — `LiveContext` + `MarketDataFeed`/`ExecutionGateway` seams in `sdk/live.py`, sim/live parity tests (T8.2) | 2026-11-14 |
| 0003 | Catalog `step.toml` is declarative-only — in-repo executor `tools/run_step.py` proves every step runs deterministically on `SimulatedContext` (T8.3) | 2026-11-14 |
| 0004 | No `BasketManifest`-driven run loop in-repo — `basket_run.run_basket` resolves members, sizes by `optimize_allocations`, enforces the `RiskBudget` (T8.4) | 2026-11-14 |
| 0005 | Basket `RiskBudget` is a Phase-1 simple cap; no allocation optimizer — `optimize_allocations` cap math + run-loop enforcement; full `tantra-ledger-allocation` optimizer remains cross-repo (T8.5) | 2026-11-14 |
| 0006 | SDK has no stop-loss/trailing-stop primitive and no level-map/options context surface | 2026-11-14 (plan 0001 §7): `sdk/stop_protection.py` + `sdk/levels.py` + `Strategy.stop_loss`/`trail_stop`/`on_stop_update` + `StrategyContext.level_map`/`options_snapshot` with seedable `SimulatedContext` stores; honest `LevelsUnavailable`/`OptionsUnavailable` degradation citing market 0005 / data 0016 |
