# Plans Index — `tantra-strategies`

Per workspace rule `.agents/rules/gap-tracking.md`:
- Gaps are individual features (`docs/gaps/XXXX-*.md`).
- Plans are collections of gaps (`docs/plans/XXXX-*.md`).
- When implemented, plan documents are cleaned up from `docs/plans/` and
  recorded in this index.

Dismantled from the former `docs/roadmap/` directory: completed migration
milestones live in [`docs/design/implementation-record.md`](../design/implementation-record.md)
and open gaps in [`docs/gaps/README.md`](../gaps/README.md).

## Active Plans

| # | Title | Target Scope | Status |
|---|-------|--------------|--------|
| [0002](0002-universe-screen-context.md) | Universe, Classification & Screen Context for Strategies (`StrategyContext.universe/classification/screen`, `on_rebalance`) | `tantra-strategies` SDK | Proposed — research `docs/research/trendlyne-screener-alerts-mcp.md`; root plan `docs/plans/0010` (F6) |
| [0003](0003-trade-plan-sdk.md) | Trade Plan SDK (`plan_trade`, `on_trade_action`, `partial_exit`, preset TOMLs) | `tantra-strategies` SDK | Proposed — root plan `docs/plans/0008` |
| [0004](0004-fire-cashflow-theta-and-compounding-templates.md) | FIRE Acceleration Strategy Templates (Stage-2 Compounding Basket + Automated Theta Cashflow + Empirical Yield Bridge) | `manifests/`, `tantra_strategies/planning/` | Proposed (2026-11-18) — Track **T19.7**; root plan `docs/plans/0013`; depends on `tantra-ledger` 0006 + `tantra-ffi` 0005 |

## Implemented Plans

| # | Title | Target Scope | Implemented In |
|---|-------|--------------|----------------|
| 0001 (EE+) | Elephant Edge (EE+) Intraday Strategy — level map, buy/sell signals, SL/TSL, positioning (with Order Blocks & OI/gamma confluence) | `tantra-strategies/strategies/elephant_edge.py` | Closed 2026-11-17 (T12.4, `adcb8d9`): `ElephantEdgeStrategy` with declarative `Parameter`s — session level-map (`_build_level_map` + price-action fallback), 0–4 confluence scoring (OI walls / PDH-PDL / gamma / OB / mid-month gate), signal generation (`SignalKind` Breakout/Reversal/Retest + Plus-Two confirmation + ΔOI trap gate), SL/TSL/R-multiple management (3R partial + breakeven, 5R runner, 6-candle time-stop, ATR/swing trail → `StopUpdate`s), `PositionIntent` positioning (lot rounding, caps, alternate mode), square-off. Tests `tests/strategies/test_elephant_edge_{levels,signals,stops,positioning}.py` (35) + `tests/integration/test_elephant_edge_sim.py`; full suite 218 passed. SDK prerequisite (gap 0006) shipped 2026-11-14. |
| 0001 | Versioned Strategy Manifests & Basket Strategies | `tantra-strategies` | Implemented in commit `207a70c` (`StrategyManifest`, `BasketManifest`, promotion workflow) |
