# 0003 — Trade Plan SDK (`plan_trade`, trade actions, presets)

**Status**: Proposed

## 0. Executive Summary & Objective

Give strategy authors one call to turn a signal or `ChartPattern` into a sized, protected plan and a hook to react to managed stop/target actions:
`Strategy.plan_trade(signal, preset="atr_swing", **overrides) -> TradePlan`. Canonical presets live in `tantra-core` and are exposed via `tantra.trade_plan` (zero duplicated TOMLs).
Roadmap: [root plan 0008](../../../docs/plans/0008-trade-signal-generator.md).
Closes the SDK items of Qullamaggie gap row 22 (root plan 0009): `partial_exit`, close-based trailing, `equity()`.

## 1. Context & Gaps Covered

- `sdk/stop_protection.py`: `TrailMode{OFF, ATR, SWING}`, `StopProtection(... activation_after_r)` — activation is never enforced; `StopUpdate`.
- `sdk/strategy.py`: `stop_loss(side, level_band, buffer_atr)` is level-band only; `trail_stop(...)` never widens; `_emit_stop_update` has no external caller; only buy/sell market/limit. Also overlaps with `tantra.declarative.DeclarativeStrategy` in `tantra-ffi` (reconciled in `tantra-ffi` plan 0004 P4).
- `sdk/order.py`: `OrderRequest` has no trigger price (`StopAbove`/`StopBelow`). `sdk/levels.py`: `PositionIntent` has a single target.
- No `ctx.equity()`, no partial-exit intent, no `ChartPattern` helper. Related: plan [0001](README.md) (EE+ strategy — **implemented 2026-11-17, T12.4**), plan [0002](0002-universe-screen-context.md) (see closed gap `0006` in [`gaps/README.md`](../gaps/README.md#closed-gaps)).
- Upstream: `tantra-core/docs/plans/README.md#implemented-plans`, `tantra-market/docs/plans/0002-chart-pattern-analyzer.md`, `tantra-ffi/docs/plans/0004-trade-planner-bindings.md`, `tantra-market/docs/gaps/README.md#closed-gaps` (gap `0007` closed 2026-11-24).

## 2. Component Specifications & Phases

- **P1**: `ctx.equity()` (`Decimal` mark-to-market equity, currency-aware); `OrderRequest.trigger_price`; `partial_exit(...)` intent; `on_trade_action(action)` hook routed via `_emit_stop_update`.
- **P2**: `Strategy.plan_trade(signal_or_pattern, preset=..., **overrides)` over `tantra.trade_plan` (supports `Signal`, `StrategySignal`, and `ChartPattern` for `pattern_breakout`); enforce `activation_after_r`; `CloseMa` trail evaluated strictly via `on_session_close` on daily close.
- **P3**: Migrate `StopProtection`, `trail_stop`, `PositionIntent` onto `tantra.trade_plan` core types with thin deprecated compat shims (aligning with `tantra-ffi` plan 0004 P4 so SDK and `declarative.py` share one protection/action path).
- **P4 Canonical Presets**: Consume canonical `{qullamaggie, ee_plus, atr_swing, pattern_breakout}` specs from `tantra.trade_plan` (`tantra-core` SSOT) — do **not** maintain a separate drifting TOML copy in `manifests/strategies/`; SDK sizing wrappers delegate to core `RiskBudget`/`SizingSpec` (while preserving `manifests/strategies/fixed_fractional.toml` compatibility).
- **P5**: `SimulatedContext` delegates directly to the PyO3 Rust `TradeManager` (`on_entry_fill`, `on_bar`, `on_session_close`) so Python backtests match Rust backtest/live byte-for-byte; example strategies belong in `tantra-examples` as follow-up.
- SDK keeps depending only on `tantra` FFI + pydantic; `Decimal` only (zero floats).

## 3. Test Plan (TDD)

In `tests/`:
- `test_trade_plan_sdk.py`: `plan_trade` for signal + `ChartPattern` + preset override; `activation_after_r` enforced; `on_trade_action` emitted; `ctx.equity()`, `partial_exit`, `trigger_price`.
- `test_stop_protection_compat.py`: old `StopProtection` shim still works alongside `TradePlan`.
- `test_simulated_context_trade_manager.py`: deterministic PyO3 `TradeManager` delegation on `SimulatedContext` matches core SL/TSL/partial state transitions without duplicated logic; `Decimal` only (zero floats); `mypy --strict` green.

## 4. Dependencies & Tier Notes

L6 SDK (`tantra` wheel + pydantic); consumes [tantra-ffi plan 0004](../../../tantra-ffi/docs/plans/0004-trade-planner-bindings.md) & `tantra-core` `TradePlan`; consumed by [tantra-examples](../../../tantra-examples/docs/plans/README.md).
Note: Keep strategy examples in `tantra-examples`; keep SDK pure and adapter-free.

## 5. Open Questions

- Exact deprecation release for `StopProtection` alias once `TradePlan` lands.
