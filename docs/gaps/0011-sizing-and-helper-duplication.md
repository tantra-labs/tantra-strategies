# 0011 — Duplicated position sizing, percentile and IST helpers across strategies

**Status**: open
**Filed**: 2026-11-23 — workspace design review (root plan 0021) · **Kind**: duplication · **Severity**: medium
**Plan**: [0006](../plans/0006-design-review-2026-11.md)

## What's stubbed or hardcoded

- `tantra_strategies/strategies/elephant_edge.py:1206-1219` and `tantra_strategies/strategies/orb15.py:310-322` are the same risk-per-trade / lot-round / notional-cap algorithm. `tantra_strategies/strategies/sizing.py:50-55` is a third copy (stop-distance sizing).
- `_nearest_rank_percentile` is defined at `tantra_strategies/strategies/elephant_edge.py:160` and `tantra_strategies/sdk/primitives.py:69`; `_ist_datetime` at `elephant_edge.py:169` and `tantra_strategies/sdk/primitives.py:~62`.
- `IST = timezone(timedelta(hours=5, minutes=30))` is defined three times: `elephant_edge.py:83`, `orb15.py:58`, `tantra_strategies/sdk/primitives.py:49`.
- Ten sites do `Decimal(str(self.<param>))` to coerce `Parameter` values (`account_equity`, `risk_per_trade_pct`, `max_position_fraction`, `lot_size`).
- Sizing is also implemented in `tantra-risk/src/sizing_gate.rs` and `tantra-ffi/python/tantra/sizing.py`.

## Why

A lot-rounding or cap fix lands in one strategy and not the others, and strategy sizing can silently disagree with the risk gate's sizing check (root gap 0013).

## How to close it

1. Create `tantra_strategies/sdk/sizing.py` with `risk_per_trade_qty(equity, risk_pct, one_r, lot, entry, max_fraction)`; both strategies call it.
2. Add a shared `IST` / `to_ist` in `tantra_strategies/sdk/clock.py`; import `nearest_rank_percentile` from `tantra_strategies/sdk/primitives.py`.
3. Keep `strategies/sizing.FixedFractional` as an example only.
4. Check parity with `tantra-ffi/python/tantra/sizing.py` through a golden JSON vector in `tests/golden/`.

**Verification**: hypothesis tests (qty is a multiple of lot; `qty*entry <= cap`); golden vector test; `ruff check .`, `mypy --strict`, `pytest -q tests/`.

## Related

- Root gap 0013; root plan 0019 P3.5 (file split, does not cover shared helpers).
- [0012](0012-typed-validated-parameters.md) removes the `Decimal(str(...))` coercion sites.
