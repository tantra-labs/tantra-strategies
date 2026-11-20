# 0005 — Concept & Indicator Library (`tantra_library`), Predictive Range Recipes and Library MCP Server

**Status**: Implemented 2026-11-20 (T22.1–T22.5; commits `cb7efbb` S1 core, `24c8aa3` S2 composites/detectors,
`86c6b63` S3 catalog, `2487490` S4 study + recipes, `4eef653` S5 MCP). Root plan: `docs/plans/0016-concept-indicator-library-for-agents.md`.
This file is kept as the library's reference document. Wiring into Rust/TS repos is planned, not done (see §9).

## 1. Package layout (`tantra_library/`)

| Module | Role |
|---|---|
| `errors.py` | Typed errors (`InputQualityError`, validation errors) |
| `model.py` | `Entry`, `ParamSpec`, `OutputSpec`, `Provenance`, `Frame`, `StreamingComputation`, enums |
| `registry.py` | `Registry`: `register/get/entries/search/validate/resolve_params/build/evaluate/describe_markdown` |
| `primitives.py` / `indicators.py` / `composites.py` / `detectors.py` | Computations |
| `adapters.py` | Input adapters (bars to computation inputs) |
| `catalog.py` | `default_registry()` — 44 entries |
| `concepts/*.md` | 12 concept pages |
| `study.py` | `signal_study`, `EventFilter`, `StudyResult` |
| `bar_source.py` | `BarSource` Protocol, `CsvBarSource`, `bars_from_json` |
| `mcp/server.py` | `LibraryMcpServer` (stdio) |

## 2. Entry model

`Entry(id, kind, title, summary, family, concepts, depends_on, params, outputs, inputs, volume_quality,
determinism, aliases, related, provenance, body_md, factory)`. Kinds: family, concept, primitive, indicator,
composite, detector, recipe. Params are typed (int/decimal/enum/bool) with bounds; floats are rejected
(`ParamSpec.coerce`). `volume_quality: real` entries refuse tick-volume sources. `depends_on` is validated
for existence and acyclicity at build time.

## 3. Catalog layers (44 entries)

Families 6; concepts 12; primitives 8 (true-range, rma, sma, highest, lowest, swing-pivot, up-down-volume,
linreg); indicators 7 (atr, atr-bands, cmo, vidya, volume-delta-pct, alligator, awesome-oscillator);
composites 3 (predictive-ranges, vidya-trend, reversal-bars); detectors 6 (pr-center-step, pr-trend-regime,
pr-zone-touch, pr-zone-close-break, reversal-bar, vidya-trend-flip); recipes 2 (not computable).
Zone/break detectors compare against the previous bar's levels because a breakout re-centers the range on
the same bar. Reversal Bars / VIDYA-trend rules are reconstructed from published descriptions (all rules are
parameters; MFI "squat" filter not implemented).

## 4. Recipes (`tantra_strategies/strategies/predictive_ranges.py`)

`PrTrendPullbackStrategy` and `PrVidyaBreakoutStrategy` are ordinary SDK `Strategy` subclasses consuming
library entries by id; they trade only via `Strategy` and `RiskEngine`. Recipe entries in the registry
(`pr-trend-pullback`, `pr-vidya-breakout`) point to them and are not computable.
Exits are an OCO bracket (`Strategy.bracket`: STOP_MARKET stop + LIMIT target) that `SimulatedContext`
fills intrabar at the level (gap-through bars fill at the open; the stop wins when both legs trigger on one
bar). Gap 0008 (bar-close exits) is closed.

## 5. Signal study

`signal_study(...)` converts a detector column into forward-return, hit-rate, MFE/MAE and by-year
statistics, with an optional `EventFilter` (another entry's column equals a value). Levels are pinned
pre-bar so there is no look-ahead.

## 6. MCP server

Newline-delimited JSON-RPC 2.0 over stdio. Tools:
- `tantra_library_search {query, kind?, family?, limit?}`
- `tantra_library_describe {id, format: markdown|json}`
- `tantra_indicator_compute {id, params?, bars? | bars_file?, instrument, interval?, volume_quality?, tail? <=2000}`
- `tantra_signal_study {id, params?, event_column, direction?, horizons? <=10, filter?{id,params?,column,equals}, bars? | bars_file?, instrument, interval?, volume_quality?, max_events?}`

Run: `cd tantra-strategies && TANTRA_LIBRARY_DATA_ROOT=/path/to/csv/bars .venv/bin/tantra-library-mcp`
(or `python -m tantra_library.mcp`). Register in any MCP client as a stdio server with command
`tantra-library-mcp`.

## 7. Invariants

Zero floats (Decimal everywhere; JSON parsed with `parse_float=Decimal`); closed-bar determinism; bounded
work (<=200k bars per evaluate, <=5000 inline bars via `bars_from_json`, <=10 horizons, <=2000 returned
rows, <=8 MiB per JSON-RPC line); `CsvBarSource` confined to `TANTRA_LIBRARY_DATA_ROOT`; MCP inputs
validated against entry manifests; the library never places orders.

## 8. Tests

`tests/library/*` (model, registry, primitives, indicators, composites, detectors, catalog, study, bar
source, MCP) and `tests/strategies/test_predictive_ranges.py`. Gates: `ruff check .`, `ruff format --check .`,
`mypy --strict`, `pytest -q`.

## 9. Known limitations and next steps

- Bars come from CSV only; lakehouse v3 source is `tantra-data` gap 0026 (cited in `bar_source.py`).
- Wiring (not done): runtime `docs/plans/0010` (MCP supervisor + `/api/v2` proxy), agent
  `docs/plans/0017` (copilot access), ui-web `docs/plans/0017` (Indicator Lab tab).
- Deferred: optional Rust port of hot indicators, `tantra-market` plan 0005.
