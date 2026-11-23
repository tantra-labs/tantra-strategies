# 0010 — `OrderRequest` has no client order id; order ids are `SIM-n` counters

**Status**: open
**Filed**: 2026-11-23 — workspace design review (root plan 0021) · **Kind**: design-flaw · **Severity**: high
**Plan**: [0006](../plans/0006-design-review-2026-11.md)

## What's stubbed or hardcoded

- `tantra_strategies/sdk/order.py:39-49` defines `instrument, side, quantity, order_type, limit_price, tag, stop_price, oco_group`. There is no `client_order_id`; a search for `client_order_id|idempot` under `tantra_strategies` returns nothing.
- `tantra_strategies/sdk/context.py:126-127` assigns `SIM-{counter}`, so ids are not stable across a restart or replay.
- `tantra_strategies/sdk/live.py:91-100` submits straight to the gateway with no dedupe; `LiveContext.positions` is local in-memory state.
- `OrderRequest.tag` is free text; the SDK does not expose an `algo_id`.

## Why

The root rules require unique, stable order idempotency keys (`.agents/rules/security-and-secrets.md` §2.3). A retried `submit` after a gateway timeout, or a strategy restart that replays the last bar, can double an order. The runtime has `ClientOrderId` (`tantra-core`), but the Python SDK cannot supply one.

## How to close it

1. Add `client_order_id: str` to `OrderRequest`, derived deterministically from `(strategy_id, instrument, bar_ts, intent_seq)`.
2. `LiveContext` keeps a bounded recent-id set and treats duplicates as no-ops; pass the id through the gateway/host so the runtime can use it as the broker-facing idempotency key.
3. Decide whether the SDK exposes `algo_id`, or whether it is always injected by the runtime risk gate (document the decision).

**Verification**: hypothesis test that replaying a bar yields identical ids; test that a duplicate `submit` is a no-op; `ruff check .`, `mypy --strict`, `pytest -q tests/`.

## Related

- Root gap 0010 (end-to-end order idempotency and unknown-outcome handling).
- Provider: `tantra-core` `ClientOrderId`, `tantra-ffi`.
- [0009](0009-live-context-parity.md) (event-driven context carries the acks).
