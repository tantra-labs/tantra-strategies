"""Tests for Orb15Strategy — proving cross-strategy primitive reuse (Track T21.2)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from tantra_strategies import (
    Bar,
    HedgeMode,
    Orb15Strategy,
    Orb15ZoneExtractor,
    OrderSide,
    OuterBufferStopPolicy,
    SimulatedContext,
    SlMode,
)
from tantra_strategies.sdk.primitives import IST


def _bar(instrument: str, minute_offset: int, o: str, h: str, low_s: str, c: str) -> Bar:
    base = dt.datetime(2026, 5, 14, 9, 15, tzinfo=IST)
    return Bar(
        instrument=instrument,
        ts=base + dt.timedelta(minutes=5 * minute_offset),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low_s),
        close=Decimal(c),
        volume=100_000,
        interval="5m",
    )


def test_orb15_reuses_outer_buffer_stop_and_overlay_scene_across_equity_and_mcx() -> None:
    """Orb15Strategy plugs into the exact same OuterBufferStopPolicy + OverlaySceneEmitter."""
    inst = "NSE:NIFTY50-INDEX"
    bars = [
        # 3 opening range bars (9:15, 9:20, 9:25): OR_HIGH=105, OR_LOW=99
        _bar(inst, 0, "100", "105", "99", "102"),
        _bar(inst, 1, "102", "104", "100", "103"),
        _bar(inst, 2, "103", "105", "101", "104"),
        # Breakout bar above OR_HIGH=105
        _bar(inst, 3, "104", "108", "103", "107"),
        # Retest sweep to 98.5 (hunts tight centerline SL=99, holds above outer SL=95.25)
        _bar(inst, 4, "107", "107", "98.5", "106"),
        # Target extension to R2
        _bar(inst, 5, "106", "145", "105", "144"),
    ]

    strat = Orb15Strategy(
        instrument=inst,
        opening_bars=3,
        sl_mode="outer_atr_buffer",
        sl_buffer_atr="0.50",
        hedge_mode="auto",
    )
    assert isinstance(strat.zone_extractor, Orb15ZoneExtractor)
    assert isinstance(strat.stop_policy, OuterBufferStopPolicy)

    ctx = SimulatedContext()
    strat.run(ctx, bars)

    assert len(strat.signal_log) == 1
    assert strat.signal_log[0].side is OrderSide.BUY
    assert strat.hedge_log
    assert strat.hedge_log[0].structure is HedgeMode.BULL_CALL_SPREAD

    scene = strat.emit_scene()
    counts = scene.layer_counts()
    assert scene.strategy_id == "orb_15"
    assert counts["signals"] >= 2  # entry + target exit
    assert counts["bands"] >= 3  # OR_HIGH, OR_LOW, OR_MID (+ Eq)
    assert counts["stops"] >= 3
    assert counts["hints"] >= 1
    assert counts["hedges"] == 2
    assert scene.connectors and scene.connectors[0].stopped_out is False

    # Tight centerline stop stops out on the 98.5 sweep bar instead of winning
    tight_strat = Orb15Strategy(instrument=inst, opening_bars=3, sl_mode=SlMode.TIGHT_CENTER.value)
    tight_ctx = SimulatedContext()
    tight_strat.run(tight_ctx, bars)
    tight_scene = tight_strat.emit_scene()
    assert tight_scene.connectors and tight_scene.connectors[0].stopped_out is True

    # Verify MCX commodity asset class runs cleanly with evening hours
    mcx_strat = Orb15Strategy(
        instrument="MCX:CRUDEOIL",
        asset_class="commodity",
        horizon_mode="commodity_cycle",
        opening_bars=2,
        max_position_fraction="1.0",
    )
    mcx_base = dt.datetime(2026, 5, 14, 19, 0, tzinfo=IST)
    mcx_bars = [
        Bar(
            "MCX:CRUDEOIL",
            mcx_base,
            Decimal("6500"),
            Decimal("6520"),
            Decimal("6490"),
            Decimal("6510"),
            10000,
            "5m",
        ),
        Bar(
            "MCX:CRUDEOIL",
            mcx_base + dt.timedelta(minutes=5),
            Decimal("6510"),
            Decimal("6525"),
            Decimal("6495"),
            Decimal("6515"),
            10000,
            "5m",
        ),
        Bar(
            "MCX:CRUDEOIL",
            mcx_base + dt.timedelta(minutes=10),
            Decimal("6515"),
            Decimal("6555"),
            Decimal("6512"),
            Decimal("6550"),
            25000,
            "5m",
        ),
    ]
    mcx_ctx = SimulatedContext()
    mcx_strat.run(mcx_ctx, mcx_bars)
    assert len(mcx_strat.signal_log) == 1
    assert mcx_strat.hedge_log[0].structure is HedgeMode.PROTECTIVE_COLLAR
