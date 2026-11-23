# 0017 — Dependency pins and extras: unpinned `tantra`, unversioned `tantra-data`, no lock, no wheel contract

**Status**: open
**Filed**: 2026-11-23 — workspace design review (root plan 0021) · **Kind**: deployment · **Severity**: medium
**Plan**: [0006](../plans/0006-design-review-2026-11.md)

## What's stubbed or hardcoded

- `pyproject.toml:16-19` `tantra>=0.1.0`, `pydantic>=2.0.0` (no upper bound); `:24-26` `lakehouse = ["tantra-data"]` with no bounds. No lockfile or constraints file exists in the repo root.
- `tantra_strategies/sdk/wheel_bridge.py:14-17` documents that it "does not import the `tantra` wheel" and types the host with local `Protocol`s using `Any`, so a wheel API change is caught only at runtime.
- Manifests drive live promotion, yet nothing records which `tantra` or `tantra_strategies` version produced the evidence.

## Why

Reproducible research and live parity need the exact wheel and data-library versions recorded. A floating `tantra` can change `Bar` / `StrategyRunner` semantics under a promoted manifest.

## How to close it

1. Add compatible-release bounds (`tantra~=0.1`, `tantra-data~=<current>`, an upper bound on `pydantic`) and commit a constraints file.
2. Record `tantra.__version__` and `tantra_strategies.__version__` in `PromotionRecord` ([0015](0015-promotion-evidence-digest.md)).
3. Add a contract test that instantiates the real wheel host (skipped if the wheel is absent) against `WheelHost`, and replace the `Any`-typed protocols with typed ones.

**Verification**: wheel-host contract test; install from the constraints file in CI; `ruff check .`, `mypy --strict`, `pytest -q tests/`.

## Related

- Root gap 0025 (non-reproducible builds, no Python lockfiles).
- [0015](0015-promotion-evidence-digest.md), [0016](0016-package-data-and-py-typed.md).
