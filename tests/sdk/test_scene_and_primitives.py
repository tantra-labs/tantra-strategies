"""Tests for Phase 2 (Track T21.2) SDK composable primitives & OverlayScene."""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

import pytest

from tantra_strategies.sdk import (
    AssetClass,
    Bar,
    ElephantZonesExtractor,
    EntryTriggerMode,
    HedgeMode,
    HedgeOverlayPolicy,
    HintSeverity,
    HorizonMode,
    LevelMap,
    MarkerKind,
    MarkerSide,
    OptionLeg,
    OptionsSnapshot,
    Orb15ZoneExtractor,
    OrderSide,
    OuterBufferStopPolicy,
    OverlaySceneEmitter,
    SceneLayerGroup,
    SceneLayerMask,
    SessionClock,
    SlMode,
    ZoneExtractionContext,
    ZoneExtractor,
)
from tantra_strategies.sdk.primitives import IST


def _bar(
    hour: int,
    minute: int,
    o: str,
    h: str,
    low_s: str,
    c: str,
    vol: int = 100_000,
    day: int = 10,
    instrument: str = "NSE:NIFTY50-INDEX",
) -> Bar:
    return Bar(
        instrument=instrument,
        ts=dt.datetime(2026, 5, day, hour, minute, tzinfo=IST),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low_s),
        close=Decimal(c),
        volume=vol,
        interval="5m",
    )


def test_overlay_scene_emitter_all_six_layers_and_mask() -> None:
    emitter = OverlaySceneEmitter("elephant_edge_v3", "NSE:NIFTY50-INDEX", "5m")
    emitter.add_signal("24120", 12, MarkerSide.BUY, MarkerKind.SWEEP_SAVED)
    emitter.add_connector(
        from_index=12,
        from_price="24120",
        to_index=18,
        to_price="24360",
        side=MarkerSide.BUY,
        realized_r="3.0",
        stopped_out=False,
        label="+3R Target",
    )
    emitter.upsert_band("ee:s1", "24080", "24130", x0=0, x1=18, fill_index=0, label="S1")
    emitter.upsert_level("eq", "24200", x0=0, x1=18, label="Eq")
    policy = OuterBufferStopPolicy(sl_mode=SlMode.OUTER_ATR_BUFFER, buffer_atr="0.25")
    plan = policy.compute_plan(
        entry=Decimal("24120"),
        side=OrderSide.BUY,
        level_band=(Decimal("24080"), Decimal("24130")),
        atr=Decimal("40"),
    )
    policy.emit_stop_lines(emitter, plan, 12, 18)
    emitter.record_indicator_point("ATR(14)", 12, Decimal("40"))
    emitter.add_hint(
        12,
        "24120",
        HintSeverity.POSITIVE,
        "Sweep Saved (+3.0R)",
        "Tight SL swept at 24105 while outer SL 24070 held.",
    )
    hedge = HedgeOverlayPolicy().synthesize(
        spot=Decimal("24120"),
        atr=Decimal("40"),
        side=OrderSide.BUY,
        level_map=None,
        horizon_mode=HorizonMode.WEEKLY_EXPIRY,
        hedge_mode=HedgeMode.AUTO,
        lot_size="75",
    )
    HedgeOverlayPolicy.emit_to_scene(emitter, hedge, 12, 18)

    scene = emitter.emit()
    counts = scene.layer_counts()
    assert counts == {
        "signals": 1,
        "bands": 2,  # 1 band + 1 level
        "stops": 3,  # initial + R1 + R2
        "indicators": 1,
        "hints": 1,
        "hedges": 2,  # bull put credit spread (SELL PE + BUY PE)
    }

    masked = scene.filtered_visible(SceneLayerMask(bands=False, hedges=False))
    assert masked.layer_counts()["bands"] == 0
    assert masked.layer_counts()["hedges"] == 0
    assert masked.layer_counts()["signals"] == 1
    assert masked.layers.is_visible(SceneLayerGroup.SIGNALS) is True
    assert masked.layers.is_visible(SceneLayerGroup.HEDGES) is False

    wire = json.loads(json.dumps(scene.to_dict()))
    assert wire["strategy_id"] == "elephant_edge_v3"
    assert wire["signals"][0]["kind"] == "sweep_saved"
    assert wire["stops"][0]["price"] == "24070.00" or wire["stops"][0]["price"] == "24070"
    assert wire["hedges"][0]["option_kind"] == "put"


def test_session_clock_presets() -> None:
    ts = dt.datetime(2026, 5, 14, 15, 20, tzinfo=IST)
    assert SessionClock.session_key(ts, HorizonMode.INTRADAY, AssetClass.INDEX) == "2026-05-14"
    assert SessionClock.session_key(ts, HorizonMode.WEEKLY_EXPIRY, AssetClass.INDEX) == "2026-W20"
    assert (
        SessionClock.session_key(ts, HorizonMode.MONTHLY_EXPIRY, AssetClass.EQUITY_FNO) == "2026-05"
    )
    assert (
        SessionClock.session_key(ts, HorizonMode.COMMODITY_CYCLE, AssetClass.COMMODITY)
        == "MCX-2026-05"
    )
    assert SessionClock.default_square_off_time(AssetClass.COMMODITY) == "23:10"
    assert SessionClock.default_entry_window(AssetClass.COMMODITY) == ("09:15", "22:30")
    assert SessionClock.is_intraday_square_off_enabled(HorizonMode.INTRADAY) is True
    assert SessionClock.is_intraday_square_off_enabled(HorizonMode.WEEKLY_EXPIRY) is False


def test_zone_extractors_conform_to_protocol() -> None:
    ee = ElephantZonesExtractor()
    orb = Orb15ZoneExtractor(opening_bars=3)
    assert isinstance(ee, ZoneExtractor)
    assert isinstance(orb, ZoneExtractor)

    bars = (
        _bar(9, 15, "100", "103", "99", "102"),
        _bar(9, 20, "102", "105", "101", "104"),
        _bar(9, 25, "104", "106", "102", "105"),
    )
    ctx = ZoneExtractionContext(
        instrument="NSE:NIFTY50-INDEX",
        bar=bars[-1],
        bar_index=2,
        session_open=bars[0].open,
        session_bars=bars,
        completed_sessions=(),
        atr=Decimal("3"),
    )
    ee_map = ee.extract(ctx)
    orb_map = orb.extract(ctx)
    assert any(lvl.level_id == "ee:s1" for lvl in ee_map.levels)
    assert {lvl.level_id for lvl in orb_map.levels} == {"orb:high", "orb:low", "orb:mid"}


def test_outer_buffer_stop_policy_modes() -> None:
    band = (Decimal("100"), Decimal("104"))
    atr = Decimal("4")
    entry = Decimal("104")

    tight = OuterBufferStopPolicy(sl_mode=SlMode.TIGHT_CENTER).compute_plan(
        entry=entry, side=OrderSide.BUY, level_band=band, atr=atr
    )
    edge = OuterBufferStopPolicy(sl_mode=SlMode.OUTER_EDGE).compute_plan(
        entry=entry, side=OrderSide.BUY, level_band=band, atr=atr
    )
    buf = OuterBufferStopPolicy(sl_mode=SlMode.OUTER_ATR_BUFFER, buffer_atr="0.25").compute_plan(
        entry=entry, side=OrderSide.BUY, level_band=band, atr=atr
    )
    pct = OuterBufferStopPolicy(
        sl_mode=SlMode.PERCENTILE_SHIELD, percentile_atr="0.50"
    ).compute_plan(entry=entry, side=OrderSide.BUY, level_band=band, atr=atr)

    assert tight.sl == Decimal("102")
    assert edge.sl == Decimal("100")
    assert buf.sl == Decimal("99.00")
    assert pct.sl == Decimal("98.00")
    assert buf.sl < edge.sl < tight.sl
    assert buf.saved_cushion > 0
    assert pct.target_r2 > pct.target_r1 > entry


def test_hedge_overlay_policy_chain_vs_theoretical_and_unhedged() -> None:
    policy = HedgeOverlayPolicy()
    assert (
        policy.synthesize(
            spot=Decimal("24000"),
            atr=Decimal("120"),
            side=OrderSide.BUY,
            level_map=None,
            horizon_mode=HorizonMode.WEEKLY_EXPIRY,
            hedge_mode=HedgeMode.UNHEDGED,
        )
        is None
    )

    # Honest theoretical fallback when chain is absent
    theo = policy.synthesize(
        spot=Decimal("72000"),
        atr=Decimal("400"),
        side=OrderSide.BUY,
        level_map=None,
        horizon_mode=HorizonMode.COMMODITY_CYCLE,
        hedge_mode=HedgeMode.AUTO,
        lot_size="1",
    )
    assert theo is not None
    assert theo.structure is HedgeMode.PROTECTIVE_COLLAR
    assert theo.quote_source == "theoretical_model"
    assert len(theo.legs) == 3

    # Seeded option chain resolves exact chain strikes
    chain = OptionsSnapshot(
        instrument="NSE:NIFTY50-INDEX",
        expiry="2026-05-21",
        underlying_spot=Decimal("24100"),
        legs=(
            OptionLeg(strike=Decimal("23900"), option_type="PE", open_interest=Decimal("100000")),
            OptionLeg(strike=Decimal("23700"), option_type="PE", open_interest=Decimal("120000")),
            OptionLeg(strike=Decimal("24300"), option_type="CE", open_interest=Decimal("110000")),
        ),
    )
    live = policy.synthesize(
        spot=Decimal("24100"),
        atr=Decimal("120"),
        side=OrderSide.BUY,
        level_map=LevelMap(instrument="NSE:NIFTY50-INDEX"),
        horizon_mode=HorizonMode.WEEKLY_EXPIRY,
        hedge_mode=HedgeMode.AUTO,
        lot_size="75",
        snapshot=chain,
    )
    assert live is not None
    assert live.structure is HedgeMode.BULL_PUT_CREDIT_SPREAD
    assert live.quote_source == "chain_strike_theoretical"
    assert live.legs[0].strike == Decimal("23900")


def test_enums_cover_all_plan_0015_modes() -> None:
    assert {m.value for m in HorizonMode} == {
        "intraday",
        "weekly_expiry",
        "monthly_expiry",
        "commodity_cycle",
    }
    assert {m.value for m in EntryTriggerMode} == {"all", "rejection_wick", "zone_touch_close"}
    assert {m.value for m in SlMode} == {
        "tight_center",
        "outer_edge",
        "outer_atr_buffer",
        "percentile_shield",
    }
    with pytest.raises(ValueError):
        SlMode("invalid")
