# 0009 — Wheel bridge and LiveContext break research/live parity (private simulator, no fill events, no cancel/resync)

**Status**: open
**Filed**: 2026-11-23 — workspace design review (root plan 0021) · **Kind**: design-flaw · **Severity**: high
**Plan**: [0006](../plans/0006-design-review-2026-11.md)

## What's stubbed or hardcoded

- `tantra_strategies/sdk/wheel_bridge.py:84,97` builds a private `SimulatedContext()`; `:103` injects it via `strategy._context = self._sim`.
- `wheel_bridge.py:131-132` feeds the bar to the sim and drains its fills (`self._sim._drain_outbox()`, a private member) into `on_order_event`. The strategy sees simulated fills at bar close or intrabar, never broker fills.
- `wheel_bridge.py:140-148` `reconcile()` sends only `host.buy/sell(delta)` for the position difference. STOP_MARKET and OCO bracket legs (closed gap 0008) stay inside the sim and never exist at the broker or risk gate. Host-side rejections, partial fills and slippage never reach the strategy.
- `tantra_strategies/sdk/live.py:104-110` `LiveContext.run` never dispatches `on_order_event` (unlike `tantra_strategies/sdk/context.py:180,192`).
- `tantra_strategies/sdk/live.py:91-100` updates `_positions` only on a synchronous `COMPLETE` event; PARTIAL or OPEN events never change the position.
- `LiveContext` has no `cancel` and no `_drain_outbox`, while `SimulatedContext` has both (`tantra_strategies/sdk/context.py:272,297`). `StrategyContext` (`context.py:30-42`) lacks `cancel` and `open_orders`.

## Why

A bracketed strategy (Elephant Edge, ORB-15, Predictive Range) has its stop evaluated in Python against a simulated fill. In paper or live the host fills at a different price and the stop is not resident at the broker; if the process dies the position is unprotected, and the strategy's internal `StopProtection` state diverges from the real position. Partial fills (slicer/TWAP strategies in `tantra_strategies/strategies/execution.py`) are silently lost, and after a reconnect the strategy trades on a stale position. Violates the non-bypassable risk-gate intent of `.agents/rules/security-and-secrets.md` (untrusted strategy output must reach the gate) and research-live parity.

## How to close it

1. Make `StrategyContext` event-driven: the host/gateway returns an ack and delivers fills asynchronously; `LiveContext` dispatches `on_order_event` from them and handles PARTIAL fills.
2. Add `submit_stop` / `cancel` / `replace` and `open_orders` to the context protocol and to `WheelHost`, so resting stops go to the exchange or the paper engine.
3. Extend `ExecutionGateway` with `positions()` and `open_orders()` snapshots used for resync in `on_start` and after reconnect.
4. Delete the private-sim path in `WheelSdkBridge`, or restrict it to an explicitly flagged "advisory" mode.

**Verification**: parity test in `tests/integration/` running one bar fixture through `SimulatedContext` and through the `tantra-exec-paper` backed host, comparing the order/fill trace as a golden vector; contract tests running one suite against `SimulatedContext` and `LiveContext` with a fake gateway; `ruff check .`, `mypy --strict`, `pytest -q tests/`.

## Related

- Root gap 0013 (single shared risk gate; Python strategy paths must not bypass it).
- Closed gap 0002 (seam only) and closed gap 0008 (SDK stops); root plan 0019 P4.5 (model unification) is related but does not cover this.
- Provider side: `tantra-runtime` `PythonStrategyActor` host contract and `tantra-ffi`.
