# 0002 — Universe, Classification & Screen Context for Strategies

**Status**: Proposed (updated 2026-11-16)

## 0. Executive Summary & Objective

Let strategies ask "what is my universe, how is this stock classified, which stocks pass this
screen" through `StrategyContext`, point-in-time in backtests, so basket and sector-rotation
strategies need no ad-hoc data access. The SDK defines Protocols only; a tantra-data-backed adapter
lives in the composition layer.

References: research [`trendlyne-screener-alerts-mcp.md`](../../../docs/research/trendlyne-screener-alerts-mcp.md) (F6);
root roadmap [`0010`](../../../docs/plans/0010-screener-taxonomy-and-alerts.md).
Depends on: [tantra-core 0004 (Implemented 2026-11-17)](../../../tantra-core/docs/plans/README.md#implemented-plans) (slim classification VOs & converged Screener DSL),
[tantra-data 0007](../../../tantra-data/docs/plans/0007-instrument-master-index-membership.md),
[tantra-data 0008](../../../tantra-data/docs/plans/0008-screen-dsl-catalog-qvm.md).

## 1. Context & Gaps Covered

`sdk/context.py` `StrategyContext` exposes `submit`, `current_price`, `position`, `level_map()`,
`options_snapshot(...)`; unwired surfaces raise `LevelsUnavailable`/`OptionsUnavailable`. There is no
universe, classification, or screen access. The package depends only on the `tantra` FFI wheel and
pydantic and must not import `tantra_data`.

## 2. Component Specifications & Phases

### Phase A — Protocol surface (`sdk/context.py`)
- `universe(name: str, as_of: date | None = None) -> list[str]`
- `classification(instrument: str) -> InstrumentClassification`
- `screen(query) -> ScreenResult` (accepting either a catalog preset ID or converged `ScreenQuery`/`ScreenerScanRequest`)
- SDK-local frozen DTOs (`InstrumentClassification`, `ScreenQuery`, `ScreenResult`) mirroring the
  `tantra-core` 0004 / `tantra-data` 0007–0008 wire strings (or obtained from `tantra` FFI when exposed); `Decimal` only.
- Errors `UniverseUnavailable`, `ClassificationUnavailable`, `ScreenUnavailable` raised when unwired,
  same pattern as `LevelsUnavailable`.

### Phase B — Simulated context
- `SimulatedContext.seed_universe/seed_classification/seed_screen`; as-of aware so backtests see the
  point-in-time universe (no survivorship bias).

### Phase C — Declarative strategy surface
- `Strategy.universe = Parameter("NIFTY500")`-style attribute (validated through `Parameter`).
- `on_rebalance(universe_snapshot)` hook for basket/rotation strategies, invoked by the runner at the
  declared cadence with the as-of universe.
- Basket manifest (`manifest/basket.py`) accepts `universe: {index: NIFTY500, cap_bucket: Mid, sector: ...}`
  or `screen: <catalog preset id>`; manifest version bumped, old manifests still load.

### Phase D — Composition adapter (outside the SDK)
- A `tantra-data`-backed adapter satisfying the Protocols, wired by the runner/composition root
  (documented here, implemented where `tantra_data` is already a dependency).

## 3. Test Plan (TDD)

In `tests/`: `test_context_universe.py` (runtime_checkable conformance, unwired raises),
`test_simulated_context_universe.py` (as-of correctness), `test_on_rebalance.py`,
`test_basket_manifest_universe.py` (old and new manifest forms), `mypy --strict` over the new Protocols.

## 4. Dependencies & Tier Notes

L6; no new dependencies. Never `isinstance(ctx, SimulatedContext)`; add capability methods on the
Protocol. Consumed by [tantra-examples 0005](../../../tantra-examples/docs/plans/0005-categorized-examples.md).

## 5. Open Questions

- Do converged Screener/Classification DTOs come from the `tantra` FFI wheel (needs core 0004 exposed in `tantra-ffi`) or stay SDK-local until then?
- Rebalance cadence declaration: per-strategy parameter or manifest field?
