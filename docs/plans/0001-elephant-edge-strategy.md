# 0001 — Elephant Edge (EE+) Intraday Strategy

**Status**: Proposed — SDK prerequisite (gap 0006) shipped 2026-11-14 (see §7); the full EE+ strategy itself remains the future slice of this plan
**Target Scope**: `tantra_strategies` (strategy module + SDK additions)
**Upstream Dependencies**: `tantra-core` (plan 0003 / gap 0002 — level-map &
stop-protection domain types), `tantra-market` (gap 0005 — Elephant/OI/OB
indicators; gaps 0001/0002 already closed for chain + OI stores), `tantra-data`
(gap 0016 — option-chain snapshot lakehouse; gap 0013 — FII/DII flows),
`tantra-exec` (gap 0003 — bracket/SL-TSL execution), `tantra-risk` (gap 0005 —
stop-protection validation), `tantra-ledger` (gap 0012 — bracket OMS lifecycle),
`tantra-agent` (plan 0011 — `level_map` chat tool)
**Master plan**: root [`docs/plans/0005-elephant-edge-strategy-platform.md`](../../../docs/plans/0005-elephant-edge-strategy-platform.md)

---

## 0. Objective

Implement the **Elephant Edge (EE+)** production intraday strategy in
`tantra-strategies` on the pure-Python SDK (`sdk/strategy.py`). The strategy:

1. builds the day's **level map** at the open (after the first 1-minute candle
   closes at 09:16 IST), with optional dynamic strike-wall snapping,
2. fuses price-derived levels with **option-chain / OI / dealer-gamma** levels,
   **Order Blocks**, and the **mid-month (15th $\pm$ 1 day) institutional
   reversal cycle** into a **0–4 confluence score** per level,
3. emits **possible buy/sell signals** (`StrategySignal`) only at high-confluence
   levels with a confirmed price-action trigger, volume, and **Plus-Two**
   breakout confirmation, gated by $\Delta\text{OI}$ buildup vs short-covering,
4. attaches **stop-loss (SL)** ($1R$ beyond the zone cluster), **asymmetric
   $3R$ partial-booking & $4R\text{--}5R$ runner targets**, **trailing stop-loss
   (TSL)**, and the **6-candle stagnation time-stop** to every signal,
5. computes **positioning** (`PositionIntent`) from risk budgets, and
6. squares off intraday, with research-live parity and `tantra-risk` clamping
   downstream.

Strategy signature follows the repo conventions: declarative `Parameter`s,
`on_start` / `on_bar` / `on_order_event` / `on_stop` hooks, `decimal.Decimal`
everywhere, tests in `tests/` parallel to `src/` (TDD, Red-Green-Refactor).

## 1. Verified Current State (probe-verified 2026-11-13)

- SDK `Strategy` exposes `buy`/`sell`/`submit`/`position`/`current_price`,
  `IndicatorRegistry` (SMA/EMA/RSI/ATR/Bollinger), `Parameter`, and the
  `SimulatedContext` harness. **Gap 0006 shipped 2026-11-14**: `stop_loss()` /
  `trail_stop()` helpers, `StopProtection`/`StopUpdate`/`TrailMode`, and a
  level-map/options context surface (`StrategyContext.level_map()` /
  `options_snapshot()`) with seedable `SimulatedContext` stores — the SDK
  prerequisites below are in place; the EE+ strategy module is the next slice.
- `on_tick` is dispatched via `Strategy.run_ticks` / `SimulatedContext.run_ticks`
  (gap 0001 closed) — EE+ runs on `on_bar` (1-minute) plus a snapshot-based
  `on_levels`/options pull at the open, and could add tick-level entry checks
  on the shipped level/options context surface (gap 0006).
- `StrategyContext` (gap 0006) now adds `level_map()` and
  `options_snapshot(instrument, expiry)` protocol methods with honest
  `LevelsUnavailable` / `OptionsUnavailable` degradation (citing `tantra-market`
  gap 0005 / `tantra-data` gap 0016); `SimulatedContext` carries seedable
  level/OI stores and `LiveContext` degrades honestly until the upstream data
  gaps close, mirroring the seedable-adapter pattern used across the workspace.

## 2. Level Map

Built once at the open anchor (first 1-minute bar close at 09:16 IST) and
re-scored every N bars (default 5) as OI/price evolve:

| Kind | Source | Side | Notes |
| :--- | :--- | :--- | :--- |
| `ElephantSupport1..2` / `ElephantResistance1..2` | session-range percentile zones (defaults 25/35 support, 63/74 resistance) or 1.618×/2.618× 1-min anchor range extensions from `tantra-market` gap 0005 | S / R | the "two supports + two resistances"; bands, not lines; optionally snapped to nearest OI strike wall |
| `PreviousDayOHLC` | prior session O/H/L/C | both | PDH/PDL/PDC; stop-cluster & breakout levels |
| `OiWallCall` / `OiWallPut` | top-2 CE OI strikes above spot / top-2 PE OI strikes below spot (nearest weekly expiry) | R / S | from the closed `ChainReader`/`OpenInterestStore` |
| `GammaFlip` | spot level where net dealer gamma crosses zero | both | regime boundary |
| `GammaWallCall` / `GammaWallPut` | largest gamma-concentration strikes | R / S | strongest mechanical hedging levels |
| `MaxPain` | option-chain max-pain strike (+ intraday migration direction) | both | expiry-day target/context, not morning S/R |
| `StrikeRound` | round-number / strike-interval lines (50/100) | both | liquidity clusters |
| `OrderBlock` | last opposite-color candle before a displacement move | R (bearish OB) / S (bullish OB) | smart-money resting-order footprints |

**Confluence score (0–4, clamped)** per level, summed only over *distinct*
sources that overlap within a band (default band width = one strike or 0.5×ATR,
whichever is wider):

- +1 level aligns with an OI wall, PDH/PDL, gamma wall, or Order Block (with
  dynamic strike snapping when an Elephant zone sits within $\pm 1$ strike of
  an OI wall);
- +1 the wall matches the required intraday $\Delta\text{OI}$ dynamic (building
  $\Delta\text{OI} > 0$ for Reversal plays; unwinding / short-covering
  $\Delta\text{OI} < 0$ at the broken strike for Breakout plays — Layer B of
  the research doc);
- +1 Local Range PCR (computed across strikes in $[S_2, R_2]$) / IV-skew tilt
  supports trading that side ($\text{PCR}_{\text{Local}} > 1.0 \to$ support
  side preferred; $\text{PCR}_{\text{Local}} < 0.75 \to$ resistances firmer);
- +1 the dealer-gamma regime agrees with the planned play (long-gamma +
  Reversal, short-gamma + Breakout), **OR** the **Mid-Month (15th $\pm$ 1 day)
  Institutional Reversal Gate** is active (`use_mid_month_cycle = True`, session
  date $\in [14, 16]$ or nearest trading day, and 1st-to-15th directional
  stretch $|\text{Stretch}_{1\to 15}| \ge \text{mid\_month\_stretch\_atr}$):
  +1 boost to counter-trend Reversal / role-reversal setups at $R_1/R_2$ (after
  a first-half rally) or $S_1/S_2$ (after a first-half selloff), and -1 penalty
  to late trend-continuation breakouts into exhaustion.

Levels with score < 3 are **not tradeable**.

## 3. Signal Generation (possible buy/sell)

A `StrategySignal` is emitted only when **all** hold on the same bar:

1. **Level**: price trades into (or breaks) a score ≥ 3 level band (never enter
   in the "No-Trade / Avoid Mid-Zone" between $S_1$ and $R_1$ unless a valid
   Order Block + OI wall cluster sits there).
2. **Regime, $\Delta\text{OI}$ & Mid-Month Cycle gate**: signal kind allowed by
   the gamma regime, $\Delta\text{OI}$ sign, Local PCR tilt, and mid-month
   exhaustion filter (see §4).
3. **Trigger candle**: a confirmed reaction candle at the level —
   - *Reversal*: hammer / bullish-engulfing at support, or shooting-star /
     bearish-engulfing at resistance, plus wick:body ratio filter (default body
     ≤ 45% for hammers, ≥ 60% for marubozu breaks), plus candle-size filter
     (exclude noise candles < 0.2×ATR and outliers > 4×ATR).
   - *Breakout*: an **Elephant marubozu-style close beyond the band** (body ≥
     60% of range, range ≥ 1.5×ATR) with the band pierced (touch filter),
     validated by the **"Plus-Two" confirmation rule** (configurable
     `confirm_bars_breakout`, default 1–2 follow-through bars sustaining outside
     the zone to filter morning fakeouts) and negative $\Delta\text{OI}$
     (short-covering) at the broken strike.
   - *Retest*: after a break, the first pullback to the band with a hold
     candle (role reversal).
4. **Volume**: participation ≥ 1.5× the 20-bar average volume.
5. **Discipline**: inside the entry window (default 09:20–14:30), max trades
   per day (default 3), no duplicate signal at the same level, no new entries
   in the last 30 minutes of the session.
6. **No open opposing position**: EE+ is one-position-per-instrument intraday.

`StrategySignal` carries `side` (Buy/Sell), `kind` (Breakout/Reversal/Retest),
`ref_levels: list[LevelId]`, and `confidence: Decimal` (0–100, from the level
score × trigger quality).

**Order Block handling**: a valid OB adds +1 to the confluence score of any
level overlapping it; a *bearish* OB above price upgrades a resistance play,
a *bullish* OB below price upgrades a support play. OBs detected at session
open (prior-session displacement) and intraday (1-minute displacement).

## 4. SL, TSL, R-Multiple Milestones (3R / 4R / 5R), and 6-Candle Time-Stop

Every signal attaches a `StopProtection` (SDK primitive, gap 0006):

- **Initial SL** (`sl` / $1R$ anchor): placed **beyond the level cluster + buffer** —
  - Reversal at support: `level_low − buffer`; buffer default = 0.25×ATR.
  - Breakout long: beyond the *broken* band opposite side (role-reversal
    stop), i.e. `band_low − buffer`.
  - Mirror for shorts. All `Decimal`; never within the band.
  - ATR-based minimum stop distance guard: `|entry − sl| ≥ 0.5×ATR`, else the
    setup is skipped (too tight for costs).
- **Asymmetric R-Multiple Targets ($3R$ and $4R\text{--}5R$)**:
  - Defining $1R = |\text{entry} - \text{sl}|$:
  - **Primary Target ($3R$ / Next Confluence Zone):** In standard long-gamma
    reversal trades, full or partial (default 50–75%) take-profit is set at
    `target_r1` (default `3.0R` or the next confluence level); upon hitting
    `target_r1`, the remaining position's stop is moved to breakeven (`entry`).
  - **Extended Runner Target ($4R\text{--}5R$):** In short-gamma / short-covering
    breakout trades **or confirmed Mid-Month (15th $\pm$ 1 day) institutional
    cycle reversals**, the runner leg targets `target_r2` (default `5.0R`),
    managed by the active trailing stop.
  - If the IV-implied expected daily move cannot reach at least `2.0R`, the
    setup is skipped.
- **The "6-Candle Rule" (Time-Stop)**:
  - If an open position has not achieved at least `0.5R` favorable excursion
    within `max_stagnant_bars` (default `6` bars), the strategy emits a market
    scratch/close order to prevent options theta decay in sideways chop.
- **Trailing stop (TSL)** (`trail`): activates after the trade reaches
  `activation_after_r` (default 1R = entry − SL distance) and then trails:
  - `AtrTrail`: `max(sl, highest_close_since_entry − trail_atr_mult×ATR)` per
    bar for longs (mirror for shorts); default `trail_atr_mult = 2`.
  - `SwingTrail`: park the stop under the most recent higher-low (lower-high
    for shorts) once confirmed.
  - `Off`: fixed SL only (allowed only when `allow_fixed_sl_only` is on, and
    flagged for the risk gate).
- TSL updates are emitted as `StopUpdate` events (`on_stop_update`) so
  `tantra-exec` (gap 0003) can `modify` the resting stop and `tantra-ledger`
  (gap 0012) can journal them.

## 5. Positioning

`PositionIntent` computed per signal in `on_signal`:

1. **Risk per trade** (`risk_per_trade_pct`, default 0.5% of account equity).
2. **Quantity**: `qty = (equity × risk_pct) / (|entry − sl| × instrument_value_per_unit)`
   rounded **down to whole lots** (NSE lot sizes for the instrument), exact
   `Decimal`.
3. **Caps**: `max_position_fraction` (default 0.25 of equity per instrument),
   basket `RiskBudget.max_loss` (gap 0005), and intraday `max_trades_per_day`.
4. **Alternate mode**: when `alternate_mode = True`, the next signal must be
   the *opposite* side (long → short → long …), preventing same-direction
   stacking (mirrors the AlgoBing alternate-mode concept).
5. **Square-off**: `on_stop` / end-of-window exit (default 15:10) using the
   opposite `sell`/`buy`; SL/TSL exits are market-on-stop.

## 6. Parameters (declarative)

| Parameter | Default | Min | Max | Step |
| :--- | :--- | :--- | :--- | :--- |
| `elephant_support_percentiles` | `(25, 35)` | — | — | — |
| `elephant_resistance_percentiles` | `(63, 74)` | — | — | — |
| `use_oi_walls` / `use_gamma` / `use_order_blocks` / `use_pdh_pdl` / `use_max_pain` | `True` | — | — | — |
| `snap_zones_to_oi_strikes` | `True` | — | — | — |
| `use_mid_month_cycle` | `True` | — | — | — |
| `mid_month_window_days` | `(14, 16)` | — | — | — |
| `mid_month_stretch_atr` | `2.5` | 1.5 | 5.0 | 0.5 |
| `min_level_score` | `3` | 0 | 4 | 1 |
| `entry_window` | `(09:20, 14:30)` | — | — | — |
| `square_off_time` | `15:10` | — | — | — |
| `max_trades_per_day` | `3` | 1 | 10 | 1 |
| `risk_per_trade_pct` | `0.5` | 0.1 | 2.0 | 0.1 |
| `max_position_fraction` | `0.25` | 0.05 | 1.0 | 0.05 |
| `target_r1` | `3.0` | 1.5 | 5.0 | 0.5 |
| `target_r2` | `5.0` | 3.0 | 10.0 | 0.5 |
| `confirm_bars_breakout` | `2` | 0 | 3 | 1 |
| `max_stagnant_bars` | `6` | 3 | 15 | 1 |
| `trail_mode` | `"atr"` | `off`/`atr`/`swing` | — | — |
| `trail_atr_mult` | `2.0` | 1.0 | 5.0 | 0.5 |
| `activation_after_r` | `1.0` | 0.5 | 3.0 | 0.5 |
| `sl_buffer_atr` | `0.25` | 0.1 | 1.0 | 0.05 |
| `min_sl_atr` | `0.5` | 0.2 | 3.0 | 0.1 |
| `volume_mult` | `1.5` | 1.0 | 5.0 | 0.1 |
| `body_ratio_breakout` | `0.6` | 0.5 | 0.9 | 0.05 |
| `alternate_mode` | `False` | — | — | — |

## 7. SDK Additions (gap 0006) — SHIPPED 2026-11-14

All items below landed with gap 0006 closed (see the Closed table in
`docs/gaps/README.md`):

- `StopProtection` value object (`sdk/stop_protection.py`) with `sl`,
  `trail` (`TrailMode`: off/atr/swing), `trail_distance`,
  `activation_after_r`; exact `Decimal`; self-validating (`sl > 0`,
  `trail_distance ≥ 0`, `activation_after_r ≥ 0`) with a `to_dict()`;
  `StopUpdate` event model ships alongside.
- `Level`, `LevelMap`, `StrategySignal`, `PositionIntent`, `OptionLeg`,
  `OptionsSnapshot` domain models in `sdk/levels.py` (mirroring
  `tantra-core` plan 0003 types 1:1), with `Level.band()` /
  `LevelMap.overlapping()` filtering and `OptionsSnapshot` max-pain / OI-wall
  helpers.
- `Strategy.stop_loss(side, level_band, buffer_atr)` and
  `Strategy.trail_stop(...)` helpers returning `StopProtection` /
  emitting `StopUpdate`, plus the `on_stop_update` lifecycle hook.
- `StrategyContext` extension: `level_map()` and
  `options_snapshot(instrument, expiry)` protocol methods (honest
  `LevelsUnavailable` / `OptionsUnavailable` degradation citing
  `tantra-market` gap 0005 / `tantra-data` gap 0016); `SimulatedContext`
  gains seedable level/OI stores for tests; `LiveContext` degrades honestly.
- Tests: `tests/sdk/test_stop_protection.py`, `tests/sdk/test_levels.py`,
  `tests/sdk/test_options_context.py`, and golden vectors
  `tests/golden/stop_trail_golden.json`.

## 8. TDD Plan (`tests/`)

- `tests/unit/test_levels.py` — band overlap, strike-wall snapping, confluence
  scoring, OrderBlock overlap, mid-month (15th $\pm$ 1 day) reversal score
  boost & late-breakout penalty.
- `tests/unit/test_signals.py` — trigger-candle filters, breakout vs reversal,
  Plus-Two confirmation, $\Delta\text{OI}$ trap rejection, mid-month cycle
  reversal gating, touch filter, time/trade-count discipline.
- `tests/unit/test_stops.py` — SL placement rules, 3R partial / breakeven trail
  & 5R runner targets, 6-candle stagnation time-stop, ATR/Swing trailing
  arithmetic (golden vectors), activation-after-R.
- `tests/unit/test_positioning.py` — risk-based quantity, lot rounding, caps,
  alternate-mode, square-off.
- `tests/integration/test_elephant_edge_sim.py` — full-day simulation on
  seeded bars + seeded OI/level stores (Red-Green-Refactor; assert fills,
  SL/TSL/time-stop exits, journaled `StopUpdate`s).

## 9. Subagent Execution Invariants

1. **Zero inline tests** — all tests in `tests/` (repo rule, AGENTS.md §3.2).
2. **Zero floats** — `decimal.Decimal` for every price, stop, band, quantity.
3. **Honest degradation** — unavailable chain/OI/level data answers
   `unavailable`/`NotImplementedError` citing the specific upstream gap; never
   fabricate levels.
4. **Parity** — identical logic in `SimulatedContext` and any future live
   context; golden vectors in `tests/golden/`.
5. **Quality gates** — `ruff check . && ruff format --check .`, `pytest -q`,
   `pyright` clean per slice.

## 10. Related

- Research: [`docs/research/elephant-edge-strategy.md`](../../../docs/research/elephant-edge-strategy.md) (level map, OI walls, GEX & mid-month cycle layers)
- Root master: [`docs/plans/0005-elephant-edge-strategy-platform.md`](../../../docs/plans/0005-elephant-edge-strategy-platform.md)
- SDK reference: [`docs/design/code-sdk.md`](../design/code-sdk.md)
- Gap 0006 (SDK prerequisites, CLOSED 2026-11-14): see the Closed table in [`docs/gaps/README.md`](../gaps/README.md)
