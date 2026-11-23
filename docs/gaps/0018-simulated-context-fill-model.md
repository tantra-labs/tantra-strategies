# 0018 — `SimulatedContext` fills at close with no tick rounding, fees or slippage

**Status**: open
**Filed**: 2026-11-23 — workspace design review (root plan 0021) · **Kind**: design-flaw · **Severity**: medium
**Plan**: [0006](../plans/0006-design-review-2026-11.md)

## What's stubbed or hardcoded

- `tantra_strategies/sdk/context.py:45-60,125-150` fills market orders at `current_price` (bar close); there is no commission, tax, slippage, or lot/tick validation in `submit` / `_fill`.
- Strategy-computed prices (`tantra_strategies/strategies/elephant_edge.py:621` floors to a `step`; `tantra_strategies/sdk/primitives.py:636-644` snaps only hedge strikes) are submitted as `limit_price` / `stop_price` without tick-size rounding. `OrderRequest` carries no `tick_size` or instrument spec.
- Three fill models exist: this one, `tantra-ffi/python/tantra/backtest/simulated.py`, and the Rust paper/backtest engines (`tantra-exec` paper, `tantra-runtime-backtest`) that hold the real cost model.

## Why

Backtest P&L from `run_basket` / `run_step` is optimistic and not comparable with `tantra-runtime-backtest`. A stop at a non-tick price would be rejected by the exchange live.

## How to close it

1. Introduce an `InstrumentSpec` (tick, lot, freeze) passed in the context; `OrderRequest.__post_init__` or `Strategy.submit` rounds to tick per side (`ROUND_DOWN` for buy stops/limits as appropriate).
2. Drive costs from the `tantra-ledger-journal` cost tables via the wheel rather than re-implementing them.
3. Mark `SimulatedContext` as "logic-test only" in its docstring until (1) and (2) land.
4. Add a cross-engine golden test against `tantra-exec-paper`.

**Verification**: hypothesis test (rounded prices are tick multiples); golden cross-engine trace; `ruff check .`, `mypy --strict`, `pytest -q tests/`.

## Related

- Root gap 0021 (simulation/fill-model unification for research harnesses); root plan 0019 P3.5 touches `l2_sim` file size only.
- [0009](0009-live-context-parity.md).
