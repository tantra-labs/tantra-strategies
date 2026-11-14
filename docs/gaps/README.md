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

| # | Title | Severity | Status | Plan |
|---|-------|----------|--------|------|
| [0006](0006-strategy-sdk-stop-protection-and-options-context.md) | SDK has no stop-loss/trailing-stop primitive and no level-map/options context surface | High | Open | [0001](../plans/0001-elephant-edge-strategy.md) |

The remaining gap is the EE+ (Elephant Edge) SDK surface; it is intentionally
**not** grouped into the T8 track (which closed 0001–0005 on 2026-11-14).

## Closed Gaps

| # | Title | Closed In |
|---|-------|-----------|
| 0001 | `Strategy.on_tick` declared but never dispatched — `Tick` model + `Strategy.run_ticks` / `SimulatedContext.run_ticks` / `LiveContext.run_ticks` dispatch (T8.1) | 2026-11-14 |
| 0002 | No live/feed-backed `StrategyContext` in-repo (only `SimulatedContext`) — `LiveContext` + `MarketDataFeed`/`ExecutionGateway` seams in `sdk/live.py`, sim/live parity tests (T8.2) | 2026-11-14 |
| 0003 | Catalog `step.toml` is declarative-only — in-repo executor `tools/run_step.py` proves every step runs deterministically on `SimulatedContext` (T8.3) | 2026-11-14 |
| 0004 | No `BasketManifest`-driven run loop in-repo — `basket_run.run_basket` resolves members, sizes by `optimize_allocations`, enforces the `RiskBudget` (T8.4) | 2026-11-14 |
| 0005 | Basket `RiskBudget` is a Phase-1 simple cap; no allocation optimizer — `optimize_allocations` cap math + run-loop enforcement; full `tantra-ledger-allocation` optimizer remains cross-repo (T8.5) | 2026-11-14 |
