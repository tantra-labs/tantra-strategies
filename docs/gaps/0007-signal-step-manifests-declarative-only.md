# 0007 — Signal step manifests are declarative-only (no runnable strategy class)

**Status**: open.

The chain validator (`tools/validate_chain.py`) and the tantra-examples chain
runner know the catalog id `signal.alpha30_factor` through
`registry.json` → `catalog_steps/signal/alpha30_factor/step.toml`. That
manifest is **declarative-only**: it describes the step's `consumes`/`emits`,
kind (`signal`) and params so chains validate, but there is no runnable
`alpha30_factor` strategy class in `tantra-strategies` yet (no `strategy.py`,
no `config.toml`). The examples pipeline therefore treats it as "validated but
not runnable" (`ChainNotRunnableError`).

## What's real

- `registry.json` at the catalog root (the tantra-examples harness loader's
  catalog marker) and `tools/validate_chain.py` (the chain validator the
  examples runner loads) are real artifacts consumed by tantra-examples.
- The `signal.alpha30_factor` step manifest follows the pipeline manifest
  shape: consumes `universe`, emits `orders`, params `{}`.

## What remains

A runnable `alpha30_factor` strategy (a real `Strategy` subclass with
declarative `Parameter`s, plus `config.toml` and `step.toml` beside it) so the
step can be executed rather than merely validated. Until then, chains using it
validate and the examples runner refuses to run them with a clear error, per
`tantra-docs/docs/strategies/step_manifests_and_chaining.md` ("Validated versus
runnable").

## Verification

- `tantra-examples` `tests/unit/test_pipeline_chain.py` +
  `tests/unit/test_pipeline_manifests.py` fully green (44 collected) with the
  catalog resolving through `tantra_examples.catalog.strategies_catalog_dir()`.
- `tantra-strategies` own suite green (`pytest -q`, exit 0); `ruff check .` and
  `ruff format --check .` clean.

## Related follow-on (same root cause)

Making the catalog resolvable also unskips the catalog-gated examples
integration tests. They now run and fail on the *runnable* half of the catalog,
which this gap does not ship:

- `tests/integration/test_07_alpha30_backtest.py` calls
  `load_named("equal_weight")`, which needs a strategy directory with
  `strategy.py` + `config.toml` in the loader's expected layout; no runnable
  `equal_weight` (or `alpha30_*`) strategy exists in `tantra-strategies` yet.
- `tests/integration/test_run_chain.py` runs the full pipeline and needs the
  1D NSE Parquet data catalog (`<data_dir>/catalog/1D/NSE`), which is absent in
  this environment.

Both are tracked here because the fix belongs to `tantra-strategies` (runnable
catalog strategies in the loader layout) plus the data lakehouse, not to the
chain validator.
