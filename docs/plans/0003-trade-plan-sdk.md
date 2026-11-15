# 0003 — Trade Plan SDK (`plan_trade`, trade actions, presets)

**Status**: Proposed

## 0. Executive Summary & Objective

Give strategy authors one call to turn a signal or `ChartPattern` into a sized, protected plan and a hook to react to managed stop/target actions:
`Strategy.plan_trade(signal, preset="atr_swing", **overrides) -> TradePlan`. Canonical presets live in `tantra-core` and are exposed via `tantra.trade_plan` (zero duplicated TOMLs).
Roadmap: [root plan 0008](../../../docs/plans/0008-trade-signal-generator.md).
Closes the SDK items of Qullamaggie gap row 22 (root plan 0006): `partial_exit`, close-based trailing, `equity()`.

## 1. Context & Gaps Covered

- `sdk/stop_protection.py`: `TrailMode{OFF, ATR, SWING}`, `StopProtection(... activation_after_r)` — activation is never enforced; `StopUpdate`.
- `sdk/strategy.py`: `stop_loss(side, level_band, buffer_atr)` is level-band only; `trail_stop(...)` never widens; `_emit_stop_update` has no external caller; only buy/sell market/limit. Also overlaps with `tantra.declarative.DeclarativeStrategy` in `tantra-ffi` (reconciled in `tantra-ffi` plan 0002 P4).
- `sdk/order.py`: `OrderRequest` has no trigger price (`StopAbove`/`StopBelow`). `sdk/levels.py`: `PositionIntent` has a single target.
- No `ctx.equity()`, no partial-exit intent, no `ChartPattern` helper. Related: plan [0001](0001-elephant-edge-strategy.md), plan [0002](0002-universe-screen-context.md), gap `../gaps/0006-strategy-sdk-stop-protection-and-options-context.md`.
- Upstream: `tantra-core/docs/plans/0005-trade-planner-and-manager.md`, `tantra-market/docs/plans/0002-chart-pattern-analyzer.md`, `tantra-ffi/docs/plans/0002-trade-planner-bindings.md`, `tantra-market/docs/gaps/0007-adr-pct-and-chandelier-exit.md`.

## 2. Component Specifications & Phases

- **P1**: `ctx.equity()` (`Decimal` mark-to-market equity, currency-aware); `OrderRequest.trigger_price`; `partial_exit(...)` intent; `on_trade_action(action)` hook routed via `_emit_stop_update`.
- **P2**: `Strategy.plan_trade(signal_or_pattern, preset=..., **overrides)` over `tantra.trade_plan` (supports `Signal`, `StrategySignal`, and `ChartPattern` for `pattern_breakout`); enforce `activation_after_r`; `CloseMa` trail evaluated strictly via `on_session_close` on daily close.
- **P3**: Migrate `StopProtection`, `trail_stop`, `PositionIntent` onto `tantra.trade_plan` core types with thin deprecated compat shims (aligning with `tantra-ffi` plan 0002 P4 so SDK and `declarative.py` share one protection/action path).
- **P4 Canonical Presets**: Consume canonical `{qullamaggie, ee_plus, atr_swing, pattern_breakout}` specs from `tantra.trade_plan` (`tantra-core` SSOT) — do **not** maintain a separate drifting TOML copy in `catalog/plan/`; SDK sizing wrappers delegate to core `RiskBudget`/`SizingSpec` (while preserving `catalog/size/fixed_fractional.toml` compatibility).
- **P5**: `SimulatedContext` delegates directly to the PyO3 Rust `TradeManager` (`on_entry_fill`, `on_bar`, `on_session_close`) so Python backtests match Rust backtest/live byte-for-byte; example strategies belong in `tantra-examples` as follow-up.
- SDK keeps depending only on `tantra` FFI + pydantic; `Decimal` only (zero floats).

## 3. Test Plan (TDD)

`tests/` only:
- Preset load & override validation tests verifying SDK preset defaults equal `tantra.trade_plan` canonical presets byte-for-byte;
- Per-preset golden plans (shared vectors with core, including `pattern_breakout` and VCP `measured_target=None` fallback);
- `activation_after_r` enforcement, `on_entry_fill` R-re-anchoring, and `on_session_close` `CloseMa` tests in `SimulatedContext`;
- Compat-shim regression tests; `ruff`, `mypy --strict`, `pytest -v`.

## 4. Dependencies & Tier Notes

L6 → L4 only. Blocked on `tantra-ffi` plan `0002`, `tantra-market` gap `0007`, and `tantra-market` plan `0002` (interim: strategy computes ADR%/Chandelier locally only with an explicit citation comment to gap `0007`).

## 5. Decisions Locked (Previously Open)

- **Preset SSOT**: `tantra-core` embeds and validates the canonical TOML presets and `tantra-ffi` exports them (`TradePlanSpec.from_preset(...)`); `tantra-strategies` loads from FFI rather than keeping a duplicate copy.
