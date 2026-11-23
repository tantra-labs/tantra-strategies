# 0013 — Two-way import cycle between `tantra_strategies.sdk` and `tantra_library`

**Status**: open
**Filed**: 2026-11-23 — workspace design review (root plan 0021) · **Kind**: refactor · **Severity**: medium
**Plan**: [0006](../plans/0006-design-review-2026-11.md)

## What's stubbed or hardcoded

- `tantra_library/indicators.py:20`, `tantra_library/primitives.py:9` and `tantra_library/registry.py:25` import `tantra_strategies.sdk.bar.Bar`.
- `tantra_strategies/sdk/indicators.py:~128-129` imports `tantra_library.indicators.ATR` inside `__init__` (same pattern for EMA/RSI/SMA wrappers), hiding the cycle behind function-local imports; `tantra_strategies/sdk/strategy.py:39-56` carries a `# type: ignore[return-value]`.
- The SDK `SMA/EMA/RSI/ATR` classes are thin wrappers over the library classes, yet expose a different API: `update(x)` + `.ready`/`.value` raising `ValueError`, versus `update` returning `Decimal | None`. Five `type: ignore`s in `IndicatorRegistry` exist because of this.

## Why

The cycle breaks at import time if anyone hoists a local import, and callers must learn two interfaces for the same indicator. The two indicator stacks look independent but are not.

## How to close it

1. Move `Bar` and the pure streaming primitives into one lower module; `tantra_library` owns the indicators (the library's home is this repo, Python).
2. Reduce `tantra_strategies/sdk/indicators.py` to re-exports under the old names (one deprecation cycle).
3. Add an import-graph test (`importlib` or `grimp`) in `tests/` forbidding `sdk -> library` and `library -> strategies`.
4. Extend the existing golden parity vectors (ATR/CMO, `tantra-market/.../golden/atr_cmo_tantra_library.json`) to RSI/EMA/SMA/Bollinger before any further Rust port.

**Verification**: import-graph test; existing indicator tests unchanged; `ruff check .`, `mypy --strict`, `pytest -q tests/`.

## Related

- Root gap 0016 (indicator golden-parity suite, `tantra_library` <-> `tantra-market-indicators`).
- `tantra-market` gap 0009 (Rust f64 indicator debt); root plan 0019 P4.5 (not the same issue).
