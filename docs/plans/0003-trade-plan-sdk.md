# 0003 — Trade Plan SDK (`plan_trade`, trade actions, presets)

**Status**: Proposed

## 0. Executive Summary & Objective

Give strategy authors one call to turn a signal into a sized, protected plan and a hook to react to managed stop/target actions:
`Strategy.plan_trade(signal, preset="atr_swing", **overrides) -> TradePlan`. Presets live in TOML. Roadmap: [root plan 0008](../../../docs/plans/0008-trade-signal-generator.md).
Closes the SDK items of Qullamaggie gap row 22 (root plan 0006): partial_exit, close-based trailing, `equity()`.

## 1. Context & Gaps Covered

- `sdk/stop_protection.py`: `TrailMode{OFF, ATR, SWING}`, `StopProtection(... activation_after_r)` — activation is never enforced; `StopUpdate`.
- `sdk/strategy.py`: `stop_loss(side, level_band, buffer_atr)` is level-band only; `trail_stop(...)` never widens; `_emit_stop_update` has no external caller; only buy/sell market/limit.
- `sdk/order.py`: `OrderRequest` has no trigger price. `sdk/levels.py`: `PositionIntent` has a single target.
- No `ctx.equity()`, no partial-exit intent. Related: plan [0001](0001-elephant-edge-strategy.md), plan [0002](0002-universe-screen-context.md), gap `../gaps/0006-strategy-sdk-stop-protection-and-options-context.md`.
- Upstream: `tantra-core/docs/plans/0005-trade-planner-and-manager.md`, `tantra-ffi/docs/plans/0002-trade-planner-bindings.md`, `tantra-market/docs/gaps/0007-adr-pct-and-chandelier-exit.md`.

## 2. Component Specifications & Phases

- **P1**: `ctx.equity()` (Decimal); `OrderRequest.trigger_price`; `partial_exit(...)` intent; `on_trade_action(action)` hook, routed via `_emit_stop_update`.
- **P2**: `Strategy.plan_trade` over `tantra.trade_plan`; enforce `activation_after_r`; `CloseBelowMa` trail evaluated on daily close.
- **P3**: migrate `StopProtection`, `trail_stop`, `PositionIntent` onto core types with thin compat shims (deprecated).
- **P4 Presets**: `catalog/plan/{qullamaggie,ee_plus,atr_swing}.toml` (versioned, all fields overridable); sizing reuses `catalog/size/fixed_fractional.toml`
  -> `tantra_strategies.strategies.sizing:FixedFractional`.
- **P5**: `SimulatedContext` drives `TradeManager` per bar so backtests match live; example strategies in `tantra-examples` as follow-up (not in this plan).
- SDK keeps depending only on `tantra` FFI + pydantic; Decimal only.

## 3. Test Plan (TDD)

`tests/` only: preset TOML load/validation tests; per-preset golden plans (shared vectors with core); `activation_after_r` enforcement;
partial-exit/trail flow in `SimulatedContext`; compat-shim regression tests; `ruff`, `mypy --strict`, `pytest -v`.

## 4. Dependencies & Tier Notes

L6 -> L4 only. Blocked on ffi plan 0002 and market gap 0007 (indicator inputs; interim: strategy computes ADR%/chandelier locally with a citation comment to the gap).

## 5. Open Questions

- Should preset TOMLs be the single source (read by Rust too) or mirrored from core?
