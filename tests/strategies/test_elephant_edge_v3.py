"""Phase 2 (Track T21.2) generalized ElephantEdgeStrategy tests.

Covers Index (``NSE:NIFTY50-INDEX``), F&O Equity (``NSE:RELIANCE-EQ``), and MCX
Commodity (``MCX:GOLD``) fixtures across ``horizon_mode``, ``entry_trigger_mode``,
``sl_mode``, ``hedge_mode``, and 6-layer ``OverlayScene`` emission. Zero floats.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from ee_helpers import (
    NIFTY,
    support_map,
    support_snapshot,
    warmup,
)
from ee_helpers import (
    bar as ee_bar,
)

from tantra_strategies import (
    Bar,
    ElephantEdgeStrategy,
    HedgeMode,
    Level,
    LevelKind,
    LevelMap,
    LevelSide,
    MarkerKind,
    OrderSide,
    SimulatedContext,
)
from tantra_strategies.sdk.primitives import IST

RELIANCE = "NSE:RELIANCE-EQ"
MCX_GOLD = "MCX:GOLD"


def _custom_bar(
    instrument: str,
    ts: dt.datetime,
    o: str,
    h: str,
    low_s: str,
    c: str,
    vol: int = 200_000,
) -> Bar:
    return Bar(
        instrument=instrument,
        ts=ts,
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low_s),
        close=Decimal(c),
        volume=vol,
        interval="15m",
    )


def test_outer_atr_buffer_survives_tight_sl_sweep_and_emits_scene_hint() -> None:
    """Bar probes tight centerline stop while outer-buffer SL survives and wins."""
    s1 = LevelMap(
        instrument=NIFTY,
        levels=(
            Level(
                "s1",
                LevelKind.ELEPHANT_SUPPORT_1,
                LevelSide.SUPPORT,
                Decimal("100"),
                Decimal("2"),
                4,
            ),
        ),
    )

    def _run_case(sl_mode: str) -> ElephantEdgeStrategy:
        ctx = SimulatedContext()
        ctx.seed_level_map(s1)
        strat = ElephantEdgeStrategy(
            sl_mode=sl_mode,
            sl_buffer_atr="0.25",
            min_level_score=0,
            use_oi_walls=False,
            use_gamma=False,
            use_max_pain=False,
            target_r1="2.0",
            target_r2="3.0",
        )
        bars = warmup(22, base="102", half_range="1.0")
        bars.append(ee_bar(9, 22, "101.5", "102.0", "99.5", "101.6", 350_000))
        bars.append(ee_bar(9, 23, "101.6", "102.0", "99.6", "101.4", 200_000))
        bars.append(ee_bar(9, 24, "101.4", "110.0", "101.0", "109.5", 200_000))
        bars.append(ee_bar(9, 25, "109.5", "114.5", "109.0", "114.0", 200_000))
        strat.run(ctx, bars)
        return strat

    tight = _run_case("tight_center")
    outer = _run_case("outer_atr_buffer")

    tight_scene = tight.emit_scene()
    outer_scene = outer.emit_scene()
    assert tight_scene.connectors and tight_scene.connectors[0].stopped_out is True
    assert outer_scene.connectors and outer_scene.connectors[0].stopped_out is False
    assert outer_scene.connectors[0].realized_r > 0
    assert any(sig.kind is MarkerKind.SWEEP_SAVED for sig in outer_scene.signals)
    assert any("Outer-SL Shield" in hint.title for hint in outer_scene.hints)
    assert outer_scene.indicators
    assert outer.hedge_log


def test_entry_trigger_mode_rejection_wick_vs_zone_touch_close() -> None:
    """Weak touch-and-close candle is skipped in rejection_wick but enters in zone_touch_close."""
    touch_bar = ee_bar(9, 22, "100.0", "101.2", "99.8", "101.0", 350_000)

    def _run(mode: str) -> ElephantEdgeStrategy:
        ctx = SimulatedContext()
        ctx.seed_level_map(support_map())
        ctx.seed_options(support_snapshot())
        strat = ElephantEdgeStrategy(entry_trigger_mode=mode)
        strat.run(ctx, [*warmup(22), touch_bar])
        return strat

    wick_only = _run("rejection_wick")
    touch_close = _run("zone_touch_close")
    assert len(wick_only.signal_log) == 0
    assert len(touch_close.signal_log) == 1
    assert touch_close.signal_log[0].side is OrderSide.BUY


def test_weekly_expiry_and_equity_fno_hold_across_sessions() -> None:
    """F&O Equity weekly_expiry mode holds across 15:10 boundary and synthesizes weekly hedge."""
    rel_map = LevelMap(
        instrument=RELIANCE,
        levels=(
            Level(
                "s1",
                LevelKind.ELEPHANT_SUPPORT_1,
                LevelSide.SUPPORT,
                Decimal("2900"),
                Decimal("10"),
                4,
            ),
        ),
    )
    ctx = SimulatedContext()
    ctx.seed_level_map(rel_map)
    strat = ElephantEdgeStrategy(
        instrument=RELIANCE,
        asset_class="equity_fno",
        horizon_mode="weekly_expiry",
        hedge_mode="auto",
        min_level_score=0,
        lot_size="250",
        risk_per_trade_pct="1.0",
        max_position_fraction="1.0",
        max_stagnant_bars=12,
    )

    bars: list[Bar] = []
    t0 = dt.datetime(2026, 5, 11, 9, 15, tzinfo=IST)
    for idx in range(22):
        ts = t0 + dt.timedelta(minutes=15 * idx)
        bars.append(_custom_bar(RELIANCE, ts, "2910", "2920", "2900", "2910", 100_000))
    t_entry = dt.datetime(2026, 5, 11, 15, 15, tzinfo=IST)
    bars.append(_custom_bar(RELIANCE, t_entry, "2908", "2912", "2892", "2910", 400_000))
    t_next = dt.datetime(2026, 5, 12, 9, 30, tzinfo=IST)
    bars.append(_custom_bar(RELIANCE, t_next, "2910", "2950", "2908", "2945", 200_000))

    strat.run(ctx, bars)
    assert len(strat.signal_log) == 1
    assert strat.hedge_log
    assert strat.hedge_log[0].structure is HedgeMode.BULL_PUT_CREDIT_SPREAD
    scene = strat.emit_scene()
    assert scene.symbol == RELIANCE
    assert scene.hedges


def test_mcx_commodity_cycle_extended_hours_and_protective_collar() -> None:
    """MCX Gold extended session & commodity_cycle generates ProtectiveCollar hedge."""
    gold_map = LevelMap(
        instrument=MCX_GOLD,
        levels=(
            Level(
                "s1",
                LevelKind.ELEPHANT_SUPPORT_1,
                LevelSide.SUPPORT,
                Decimal("72000"),
                Decimal("100"),
                4,
            ),
        ),
    )
    ctx = SimulatedContext()
    ctx.seed_level_map(gold_map)
    strat = ElephantEdgeStrategy(
        instrument=MCX_GOLD,
        asset_class="commodity",
        horizon_mode="commodity_cycle",
        hedge_mode="auto",
        min_level_score=0,
        lot_size="1",
        zone_round_step="100",
        max_position_fraction="1.0",
        account_equity="1000000",
    )

    bars: list[Bar] = []
    t0 = dt.datetime(2026, 5, 12, 17, 0, tzinfo=IST)
    for idx in range(22):
        ts = t0 + dt.timedelta(minutes=15 * idx)
        bars.append(_custom_bar(MCX_GOLD, ts, "72100", "72250", "72050", "72100", 50_000))
    t_evening = dt.datetime(2026, 5, 12, 21, 45, tzinfo=IST)
    bars.append(_custom_bar(MCX_GOLD, t_evening, "72080", "72100", "71900", "72090", 150_000))
    strat.run(ctx, bars)

    assert len(strat.signal_log) == 1
    assert strat.hedge_log[0].structure is HedgeMode.PROTECTIVE_COLLAR
    assert strat.hedge_log[0].quote_source == "theoretical_model"
    assert strat.emit_scene().hedges
