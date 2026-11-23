# 0012 — `Parameter` is untyped and unvalidated at default; unknown overrides and floats are accepted

**Status**: open
**Filed**: 2026-11-23 — workspace design review (root plan 0021) · **Kind**: design-flaw · **Severity**: medium
**Plan**: [0006](../plans/0006-design-review-2026-11.md)

## What's stubbed or hardcoded

- `tantra_strategies/sdk/parameter.py:28-37` stores `default: Any` with no type. `validate` runs only from `__set__` (`:50-52`), so a default outside `[min, max]` or off-step is never checked at class creation. (`tools/validate_manifests.py` checks this only for manifest-declared params.)
- `tantra_strategies/sdk/strategy.py:79-80` runs `setattr(self, name, value)` for every override. A typo such as `risk_per_trade_pc=2` silently creates a plain attribute and the strategy runs with the default.
- `tantra_strategies/sdk/parameter.py:20-21` uses `Decimal(str(value))`, which accepts floats. The same applies to `Bar.__post_init__` (`tantra_strategies/sdk/bar.py:21-24`) and `OrderRequest.__post_init__` (`tantra_strategies/sdk/order.py:52-53`): silent float-to-Decimal laundering against the Zero-Floats policy. The `bar_source` path rejects floats (`tantra_library/bar_source.py:30-31`), so the two paths disagree.

## Why

A mistyped config in a live manifest is accepted and trades with defaults. A float price such as `100.1` becomes `Decimal("100.1")` only via `str()`, hiding upstream float use (`.agents/rules/interface-first-and-modularity.md` §2.3).

## How to close it

1. Make `Parameter` generic (`Parameter[Decimal]`) with an explicit `kind` (int / Decimal / enum / str) and validate defaults in `__set_name__`.
2. `Strategy.__init__` raises on any override name that is not a `Parameter`.
3. Add a strict mode (default on) in `Bar` and `OrderRequest` that raises `TypeError` on float input.

**Verification**: hypothesis tests over parameter bounds and step; unknown override raises; float `Bar`/`OrderRequest` raises; `ruff check .`, `mypy --strict`, `pytest -q tests/`.

## Related

- Root plan 0019 P4.5 (unify `Parameter` onto the wheel); apply this fix there if it lands first.
- [0011](0011-sizing-and-helper-duplication.md).
