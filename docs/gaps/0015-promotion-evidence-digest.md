# 0015 — Manifest promotion evidence is an unchecked prefix string

**Status**: open
**Filed**: 2026-11-23 — workspace design review (root plan 0021) · **Kind**: design-flaw · **Severity**: medium
**Plan**: [0006](../plans/0006-design-review-2026-11.md)

## What's stubbed or hardcoded

- `tantra_strategies/manifest/strategy.py:136-170` `promote()` only checks one-step-forward and `evidence_ref.startswith("backtest:"|"paper:"|"live:")`.
- `PromotionRecord` (`tantra_strategies/manifest/version.py:~45-54`) has `evidence_ref: str`, `recorded_at` and `note`: no code hash, no param hash and no lakehouse commit. The `datetime.now(UTC)` default at `version.py:62` is the only clock.
- `StrategyManifest.strategy` (`tantra_strategies/manifest/strategy.py:93`) is a dotted path with no code revision; `tools/run_step.py:74` fingerprints events but nothing stores the fingerprint in the manifest.
- No seed is recorded anywhere; `tantra_library/bar_source.py:142` already resolves the lakehouse commit but it is not persisted.

## Why

A manifest version "1.0.0" can be promoted to `live` on evidence from a different code or parameter set (class edited after backtest). Research results are not reproducible: no seed, bar-set hash or lakehouse commit is recorded.

## How to close it

1. Extend `PromotionRecord` with `code_digest` (sha256 of the strategy module source), `params_digest`, `data_snapshot` (lakehouse commit sha), `result_digest` (the `fingerprint()` from `tools/run_step.py`), a `seed` where applicable, and the `tantra.__version__` / `tantra_strategies.__version__` (see [0017](0017-dependency-pins-and-wheel-contract.md)).
2. `promote()` recomputes the digests and rejects a mismatch with the loaded manifest.
3. Inject the clock instead of defaulting to `datetime.now(UTC)`.

**Verification**: golden TOML for a promotion record; mutate a parameter or the strategy source and expect rejection; `ruff check .`, `mypy --strict`, `pytest -q tests/manifests`.

## Related

- Root gap 0018 (lakehouse manifest/ref contract; commit shas must be stable).
- [0014](0014-library-provenance-and-licensing.md), [0017](0017-dependency-pins-and-wheel-contract.md).
