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
| [0001](0001-elephant-edge-strategy.md) | Elephant Edge (EE+) Intraday Strategy — level map, buy/sell signals, SL/TSL, positioning (with Order Blocks & OI/gamma confluence) | `tantra-strategies` (+ SDK additions in gap 0006) | Proposed — tracks gap 0006; master plan root `docs/plans/0005` |
| [0002](0002-universe-screen-context.md) | Universe, Classification & Screen Context for Strategies (`StrategyContext.universe/classification/screen`, `on_rebalance`) | `tantra-strategies` SDK | Proposed — research `docs/research/trendlyne-screener-alerts-mcp.md`; root plan `docs/plans/0010` (F6) |
| [0003](0003-trade-plan-sdk.md) | Trade Plan SDK (`plan_trade`, `on_trade_action`, `partial_exit`, preset TOMLs) | `tantra-strategies` SDK | Proposed — root plan `docs/plans/0008` |

## Open Gaps (un-grouped)

| Gap | Title | Plan |
|-----|-------|------|
| [0006](../gaps/0006-strategy-sdk-stop-protection-and-options-context.md) | SDK has no stop-loss/trailing-stop primitive and no level-map/options context surface | [0001](0001-elephant-edge-strategy.md) |

## Implemented Plans

| # | Title | Target Scope | Implemented In |
|---|-------|--------------|----------------|
| 0001 | Versioned Strategy Manifests & Basket Strategies | `tantra-strategies` | Implemented in commit `207a70c` (`StrategyManifest`, `BasketManifest`, promotion workflow) |
