# 0004 — Predictive Range Strategy Recipes

**Status**: Proposed (2026-11-20) — design only. Parent: root plan 0016 (Track T22, phase T22.6).

## 0. Executive Summary & Objective

Implement two strategies from root plan 0016 §2.5 as `tantra-strategies` recipes, consuming library indicators via
`tantra-ffi` (`tantra.library`): `recipe.pr-trend-pullback` and `recipe.pr-vidya-breakout`, each with long and short
mirrors, validated in the Strategy Tester. Execution logic stays in Python strategies; all orders go through `RiskEngine`.

## 1. Context & Gaps Covered

- Depends on market plan 0005 (`ind.predictive-ranges`, `ind.vidya-trend`, `ind.volume-delta-pct`, `det.*`), `tantra-ffi`
  `tantra.library` (root plan 0016 T22.6), and the Trade Plan SDK (plan 0003) for stop/target handling (to confirm in T22.6).
- Repo has `manifests/`, `registry.json`, `catalog_steps/`, `tantra_strategies/`. Recipe manifests are also discoverable in the
  library (root plan 0016 §7.2, proposed: manifest in library, code here, linked by id).

## 2. Component Specifications & Phases

### 2.1 Library access

`tantra.library.compute(entry_id, params, bars) -> pyarrow.Table` (Decimal columns as Arrow `Decimal128(38,8)`; state/event columns int8/bool).
Strategy code converts to `decimal.Decimal` from Arrow/strings only — never `float` for prices, levels, stops, R multiples.
Same Rust evaluator as Experimental Analysis (research-live parity; frames identical Rust vs Python).
Bars are closed only; HTF `timeframe` params resolve to last closed HTF bar.

### 2.2 `recipe.pr-trend-pullback` (long; short = mirror)

| Part | Rule (library ids) |
|---|---|
| Filter | `det.pr-trend-regime` = up (K >= 2 consecutive up steps of `ind.predictive-ranges`) |
| Trigger | `det.pr-zone-touch`(support: bar low <= S1) **and** `det.reversal-bar`(bullish) within the zone, same or next closed bar |
| Entry | next-bar open after the confirmed trigger bar close (market/limit per Trade Plan SDK) |
| Stop | below S2, or zone low - `buffer * ATR` (param `stop_mode`) |
| Target | R1, or ladder center -> R1 (`partial_exit`) |
Short mirror: regime down, resistance touch (high >= R1), bearish reversal bar, stop above R2, target S1 / center -> S1.
Params (manifest): `pr_length=200`, `pr_factor="6"`, `k_steps=2`, `buffer_atr="0.25"`, `stop_mode`, `ladder`.

### 2.3 `recipe.pr-vidya-breakout` (long; short = mirror)

| Part | Rule |
|---|---|
| Filter | `ind.vidya-trend` = up **and** `ind.volume-delta-pct >= +30%` (`volume_quality: real` required) |
| Trigger | close > R1 of **the range active before the bar** (pinned prior-range level; the bar's own range may re-centre) |
| Stop | last swing low (`prim.swing-pivot`) or below R1 (param) |
| Target | 1.5R (`r_multiple` param) |
Short mirror: trend down, delta <= -30%, close < S1 of prior range, swing high stop, 1.5R.
On tick-volume instruments the recipe refuses to start (`LibraryError::InputQuality` surfaced as a configuration error).

### 2.4 Files and registration

- `tantra_strategies/predictive_range/{pr_trend_pullback.py, pr_vidya_breakout.py, _library.py}` (thin wrapper over `tantra.library`; shared sizing/stop helpers via Trade Plan SDK).
- `manifests/recipe.pr-trend-pullback.toml`, `manifests/recipe.pr-vidya-breakout.toml` (params, library ids, instrument/timeframe defaults, `universe` hints) and entries in `registry.json` (schema as existing entries; to confirm in T22.6); optional `catalog_steps/` entry if the step catalog pattern fits.
- Strategy classes use `StrategyContext` protocols only (no `isinstance(context, SimulatedContext)`); injected clock; `Decimal` money math.

### 2.5 Risk path

Strategies only emit order intents; every order passes `RiskEngine` pre-trade checks (price bands, freeze limits, OTR, reduce-only)
unconditionally in backtest and live. Agent-varied parameter sets are research artefacts only; promotion to live follows existing approval flow.

### 2.6 Strategy Tester validation plan

1. **Event sanity** first: run Signal Study (runtime plan 0010) on `det.pr-zone-touch` / pinned breakout for NIFTY 5m, 2019–2026, to see raw forward-move edge before costs.
2. **IS/OOS**: chronological split (e.g. 2019–2023 IS, 2024–2026 OOS) plus walk-forward using T21 `ParameterSweepRunner` (WFE, DSR); parameters frozen from IS only.
3. **Costs**: full Indian cost schedule (brokerage, STT, exchange, stamp, GST) and slippage via the runtime cost model; report gross vs net.
4. **By regime**: breakdown by trend/range regime (`det.pr-trend-regime`), volatility tercile (ATR percentile), year, and session bucket.
5. **Robustness**: parameter-neighbourhood heatmap (length x factor), min trade count threshold, drawdown/MAR, R-multiple distribution, no-lookahead assertion (re-run with truncated data yields identical past signals).
6. Reproducibility: pin `data_commit` + entry versions in each report.

## 3. Tests & Verification

pytest in `tests/`: library-wrapper Decimal conversion (no floats), recipe rule unit tests on synthetic Arrow tables (long and short, pinned-level regression), refuse-on-tick-volume, manifest/registry schema tests, Rust-vs-Python frame parity (with ffi), backtest smoke test on a short fixture asserting orders reach `RiskEngine`.
Gates: `ruff check . && ruff format --check .`, `mypy --strict`, `pytest -v`.

## 4. Open Questions

1. Exact trigger-confirmation timing (same bar vs next bar) for pullback; fixed after Signal Study (T22.4) evidence.
2. Whether Trade Plan SDK (plan 0003) supports ladder partial exits needed by `ladder` mode.
3. Recipe manifest ownership (library vs strategies) per root plan 0016 §7.2.
4. Instruments for which `volume_quality: real` holds (index futures vs spot index).
