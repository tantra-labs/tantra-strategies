# `tantra-strategies` — Inter-Agent Handoff

## Latest Batch
* **Architectural-analysis unification (2026-11-20, root `docs/plans/Here is an architectural analysis of the.md` §2/§3)** — all landed:
  - One Decimal indicator kernel: `sdk/indicators.py` wraps `tantra_library` (EMA/RSI/Bollinger added) (`268b368`); strict `decimal` step param type (`tools/validate_chain.py`, `schema/step.schema.json` rewritten for `catalog_steps`).
  - EE+ / ORB-15 / outer-buffer stop registered in `tantra_library` (`tantra_library/zones.py`, `ind.elephant-zones`, `ind.opening-range`, `det.ee-sweep`, `det.orb15-breakout`, `prim.outer-buffer-stop`) (`d4d8045`).
  - Gap 0008 closed: SDK OCO `Strategy.bracket` + intrabar stop/target fills in `SimulatedContext` (`fe5b170`).
  - PR recipes emit `OverlayScene` + `stop_policy` (`5874557`); `WheelSdkBridge` (position reconciliation) + runnable `catalog_steps/signal/pr_{trend_pullback,vidya_breakout}`; `Entry.runnable_step` (`2e233fc`).
  - Legacy `catalog/` retired into `manifests/strategies/` (`c08867c`); two catalogs remain: `catalog_steps/`+`registry.json` and `manifests/`.
  - `LakehouseBarSource` (tantra-data `LakehouseBarReader`, env `TANTRA_LIBRARY_LAKEHOUSE_ROOT`) closes data gap 0026 (`9299121`); generic `tantra_library.scene_projection` + MCP `overlay_scene` flag (`5a2a595`); search lists by kind without a query, limit <= 200 (`628b348`).
* Gap 0007 closed 2026-11-17 (runnable `equal_weight` / `alpha30_factor` catalog steps).

## Phase / Slice Status
* **Gap 0006 / plan 0001 §7 SHIPPED (2026-11-14)**: SDK stop-protection +
  level-map/options context surface — new `sdk/stop_protection.py`
  (`StopProtection`, `StopUpdate`, `TrailMode`) and `sdk/levels.py`
  (`Level`, `LevelMap`, `LevelSide`/`LevelKind`/`SignalKind`, `StrategySignal`,
  `PositionIntent`, `OptionLeg`, `OptionsSnapshot`); `Strategy.stop_loss` /
  `trail_stop` / `_emit_stop_update` + `on_stop_update` hook;
  `StrategyContext.level_map()` / `options_snapshot()` with seedable
  `SimulatedContext` stores and honest `LevelsUnavailable`/`OptionsUnavailable`
  degradation (LiveContext raises; messages cite market 0005 / data 0016).
  Tests: `tests/sdk/test_stop_protection.py`, `test_levels.py`,
  `test_options_context.py` + golden `tests/golden/stop_trail_golden.json`.
  Gates: pytest 181 green, `ruff check`/`format --check` clean; mypy delta
  zero (14 pre-existing baseline errors remain in untouched files).

## Phase / Slice Status
* **Tier 6C (COMPLETE, `af20843`)**: Strategy SDK (`sdk/`) + 10 ported strategy
  classes (`strategies/`) + declarative manifests (legacy `catalog/` migrated into
  `manifests/strategies/` on 2026-11-20) + `schema/` + `tools/validate_manifests.py`.
* **Plan 0001 Layer 3 (COMPLETE, `207a70c`)**: `manifest/` package —
  `StrategyManifest`, `BasketManifest`, promotion workflow, POC sidecars,
  `tools/validate_manifests.py`.
* **T8 track (COMPLETE 2026-11-14, gaps 0001–0005 closed)**: tick dispatch,
  `LiveContext`, catalog step executor, basket run loop + `RiskBudget`
  optimizer.

## Decisions & Discoveries
* **Tick dispatch (gap 0001)**: `Tick` model (`sdk/tick.py`, exact Decimal,
  `bid <= ask`) + `Strategy.run_ticks` / `SimulatedContext.run_ticks` /
  `LiveContext.run_ticks`. `Strategy.run`/`run_ticks` duck-type the drive loop
  (`getattr(context, "run")`) so `SimulatedContext`, `LiveContext`, and bare
  protocol contexts all work.
* **Live parity seam (gap 0002)**: `sdk/live.py` — `MarketDataFeed` /
  `ExecutionGateway` runtime-checkable Protocols + `LiveContext` (feed-first
  `current_price` with local fallback, COMPLETE fills mirrored into Decimal
  positions). Same strategy + same bars under `SimulatedContext` and
  `LiveContext` → identical order streams (parity test).
* **Catalog executor (gap 0003)**: `tools/run_step.py` runs every `step.toml`
  through `SimulatedContext` on a deterministic 45-bar series; proves
  runnable + deterministic (two runs, identical event fingerprints).
* **Basket run loop (gaps 0004/0005)**: `optimize_allocations` (in
  `manifest/basket.py`) sizes member capital under the `RiskBudget` caps —
  `max_position_fraction` (total + per-member) then `max_loss` (total
  deployment ≤ cap; worst case = 100% loss of deployed capital). `basket_run.run_basket`
  resolves members via `resolve_manifest`, runs each through `SimulatedContext`
  under its slice, and raises `RiskBudgetViolation` when the notional position
  fraction or realized loss exceeds the caps. Full `tantra-ledger-allocation`
  optimizer remains cross-repo.
* **Zero-float guard (ruff RUF032)**: `Decimal(<float literal>)` is rejected;
  all literals are strings. RUF022 sorts `__all__` isort-style (constants,
  CamelCase, `__version__`, then lowercase functions).

## Immediate Next Step
* Indicator Lab tab UI in `tantra-ui-web` (its plan 0017: client + `OverlayScenePrimitive` renderer are done) and
  root plan 0015 Track T21.6 agent loop tools (`strategy_loop_eval`, `chart_scene_annotate`, ...).
* `pr_trend_pullback` wheel step: add a deterministic series that triggers an entry in
  `tests/integration/test_catalog_runnable.py` (today only the no-error/scene path is asserted).

## Operating Invariants
* Zero floats in financial math; `Parameter` bounds/step validated at
  assignment; tests live in `tests/` only.
* `docs/roadmap/` is gone — completed milestones live in
  `docs/design/implementation-record.md`; new work goes to `docs/gaps/`
  (numbered 0007+ if added).
