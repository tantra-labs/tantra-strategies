# 0004 — FIRE Acceleration Strategy Templates (Stage-2 Compounding + Automated Theta Cashflow)

**Status**: Proposed (2026-11-18) — Track **T19.7**

Master plan: root [`docs/plans/0013-fire-planning-and-cashflow-platform.md`](../../../docs/plans/0013-fire-planning-and-cashflow-platform.md).
Depends on: [`tantra-ledger` plan 0006](../../../tantra-ledger/docs/plans/0006-fire-bucket-glidepath-and-swr-metrics.md), [`tantra-ffi` plan 0005](../../../tantra-ffi/docs/plans/0005-fire-planning-python-bindings.md).

---

## 0. Executive Summary & Objective

Operationalize the **"Engineer's 3 Pillars"** showcased in `Elicherla01/fireapp` inside `tantra-strategies` so that projected CAGR, theta yield, and risk limits in the FIRE planner can be backed by reproducible, risk-gated strategy backtests rather than arbitrary percentage assumptions.

---

## 1. Deliverables

1. **Three-Bucket Wealth & Cashflow Basket Manifest (`manifests/fire_barbell_basket.toml`)**:
   - **Sleeve 1 — Direct Equity Compounding (`65%`)**: Pairs `Alpha30Factor` / Stage-2 momentum equity rotation (`strategies/alpha30.py`) under strict `RiskBudget` position caps.
   - **Sleeve 2 — Liquidity / Arbitrage Runway (`25%`)**: Low-volatility defensive cash/arbitrage allocation (`strategies/arbitrage.py`) maintaining 3–4 years of living-expense liquidity.
   - **Sleeve 3 — Automated Theta Cashflow (`10%`)**: Risk-bounded non-directional OTM strangle / covered-call strategy (`strategies/options.py`) harvesting monthly theta yield while obeying `tantra-risk` 1–2% stop limits (`RiskBudget`).
2. **Empirical Yield Bridge (`tantra_strategies/planning/fire_bridge.py`)**:
   - Pure `Decimal` helper translating a completed `BacktestResult` + basket sleeve returns into a `FirePlanConfig` / `CashflowBucketConfig` benchmark payload (net CAGR, historical max drawdown for SoRR `annual_volatility_pct`, average monthly realized theta yield).
   - Feeds directly into `tantra.fire.simulate_runway` (L4 FFI).

---

## 2. Tests & Verification

- `tests/integration/test_fire_barbell_basket.py`: deterministic `SimulatedContext` basket execution verifying `RiskBudget` enforcement and `Decimal` bridge conversion to `tantra.fire`.
- Gate: `ruff check . && ruff format --check . && mypy --strict && pytest -q`.
