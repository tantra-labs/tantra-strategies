# 0016 — Manifests, schema and catalog are not packaged; no `py.typed`

**Status**: open
**Filed**: 2026-11-23 — workspace design review (root plan 0021) · **Kind**: deployment · **Severity**: medium
**Plan**: [0006](../plans/0006-design-review-2026-11.md)

## What's stubbed or hardcoded

- `tantra_strategies/manifest/basket_run.py:39` sets `DEFAULT_STRATEGIES_DIR = Path(__file__).resolve().parent.parent.parent / "manifests" / "strategies"`, which resolves above the package.
- `pyproject.toml:33-34` `packages.find include = ["tantra_strategies*", "tantra_library*"]`; package-data covers only `tantra_library/concepts/*.md`. `manifests/`, `schema/`, `catalog_steps/`, `registry.json` and `tools/` are therefore absent from a built wheel.
- The `tantra-examples` harness `find_catalog()` accepts a directory only because `registry.json` exists, so catalog discovery depends on a source checkout.
- No `py.typed` marker anywhere, despite `mypy disallow_untyped_defs`.

## Why

`pip install tantra-strategies` in a container breaks `run_basket`, manifest validation and catalog loading with `FileNotFoundError`. Downstream mypy cannot use the SDK types.

## How to close it

1. Move manifests, schema and catalog into the package (`tantra_strategies/_data/`) or declare them in package-data, and read them through `importlib.resources`.
2. Add `py.typed` to both packages and list it in package-data.
3. Expose the manifest validator as a console script.
4. Add a CI smoke test: build the wheel, install into a clean venv, run the validator and a minimal `run_basket`.

**Verification**: wheel-install smoke test; `ruff check .`, `mypy --strict`, `pytest -q tests/`.

## Related

- Root plan 0023 (build, CI and release engineering).
- [0017](0017-dependency-pins-and-wheel-contract.md); `tantra-examples` harness catalog discovery.
