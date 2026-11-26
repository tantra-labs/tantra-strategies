"""Elephant Edge (EE+) level-map tests: fallback construction, confluence, snapping.

Covers plan §2: Elephant percentile / ORE fallback zones, round-number and
previous-day-OHLC levels, options augmentation, strike snapping, and the 0-4
clamped confluence score (OI-wall overlap, ΔOI dynamic, PCR tilt, dealer-gamma
regime, mid-month reversal gate). All prices exact ``Decimal``.
"""

from __future__ import annotations

from decimal import Decimal

from ee_helpers import (
    NIFTY,
    bar,
    resistance_snapshot,
    support_map,
    support_snapshot,
    warmup,
)

from tantra_strategies import (
    ElephantEdgeStrategy,
    Level,
    LevelKind,
    LevelMap,
    LevelSide,
    OptionLeg,
    OptionsSnapshot,
    SimulatedContext,
)


def test_fallback_level_map_ore_extensions() -> None:
    """Unseeded context degrades to first-candle ORE extensions (1.618x / 2.618x)."""
    strategy = ElephantEdgeStrategy()
    context = SimulatedContext()  # nothing seeded: LevelsUnavailable + OptionsUnavailable
    strategy.run(
        context,
        [
            bar(9, 0, "100", "102", "98", "100.5"),
            bar(9, 1, "100", "101", "99", "100"),
        ],
    )

    assert strategy._fallback is True
    assert strategy._level_map is not None
    levels = {level.level_id: level for level in strategy._level_map.levels}
    assert levels["ee:s1"].price == Decimal("94.028")
    assert levels["ee:s2"].price == Decimal("90.028")
    assert levels["ee:r1"].price == Decimal("106.972")
    assert levels["ee:r2"].price == Decimal("110.972")
    assert levels["ee:s1"].side is LevelSide.SUPPORT
    assert levels["ee:r1"].side is LevelSide.RESISTANCE
    assert levels["ee:s1"].kind is LevelKind.ELEPHANT_SUPPORT_1
    assert levels["ee:r2"].kind is LevelKind.ELEPHANT_RESISTANCE_2
    # band half-width falls back to half the first-candle range while ATR warms up
    assert levels["ee:s1"].band_half_width == Decimal("2.0")
    # round-number levels at the nearest 50s around the session price
    assert "rn:100" in levels and "rn:150" in levels
    assert levels["rn:100"].kind is LevelKind.STRIKE_ROUND
    # no previous-session OHLC derivable from a single-session run
    assert not any(
        level.kind is LevelKind.PREVIOUS_DAY_OHLC for level in strategy._level_map.levels
    )


def test_fallback_level_map_percentile_variant() -> None:
    """Two prior sessions -> percentile zones from prior (open - low) / (high - open)."""
    strategy = ElephantEdgeStrategy()
    context = SimulatedContext()
    strategy.run(
        context,
        [
            bar(9, 0, "100", "104", "96", "101", day=12),  # down 4, up 4
            bar(9, 0, "100", "106", "90", "102", day=13),  # down 10, up 6
            bar(9, 0, "100", "103", "97", "100.5", day=14),
        ],
    )

    assert strategy._level_map is not None
    levels = {level.level_id: level for level in strategy._level_map.levels}
    # downs [4, 10] -> p25 = p35 = 4; ups [4, 6] -> p63 = p74 = 6
    assert levels["ee:s1"].price == Decimal("96")
    assert levels["ee:s2"].price == Decimal("96")
    assert levels["ee:r1"].price == Decimal("106")
    assert levels["ee:r2"].price == Decimal("106")
    # previous-day OHLC now derivable from the prior session (day 13: 100/106/90/102)
    pdh = next(level for level in strategy._level_map.levels if level.level_id == "pdh")
    pdl = next(level for level in strategy._level_map.levels if level.level_id == "pdl")
    pdc = next(level for level in strategy._level_map.levels if level.level_id == "pdc")
    assert pdh.price == Decimal("106")
    assert pdl.price == Decimal("90")
    assert pdc.price == Decimal("102")
    assert pdh.kind is LevelKind.PREVIOUS_DAY_OHLC


def test_support_level_full_confluence_scores_four() -> None:
    """OI-wall overlap + building ΔOI + PCR>1 + long-gamma regime -> score 4."""
    strategy = ElephantEdgeStrategy()
    context = SimulatedContext()
    context.seed_level_map(support_map())
    context.seed_options(support_snapshot())
    strategy.run(context, warmup(22))

    assert strategy._level_map is not None
    levels = {level.level_id: level for level in strategy._level_map.levels}
    assert levels["s1"].score == 4
    assert levels["s1"].price == Decimal("100")
    # the options pass adds the OI-wall / gamma / max-pain levels to the map
    assert any(level.kind is LevelKind.OI_WALL_PUT for level in strategy._level_map.levels)
    assert any(level.kind is LevelKind.OI_WALL_CALL for level in strategy._level_map.levels)
    assert any(level.kind is LevelKind.GAMMA_FLIP for level in strategy._level_map.levels)
    assert any(level.kind is LevelKind.MAX_PAIN for level in strategy._level_map.levels)
    max_pain = next(
        level for level in strategy._level_map.levels if level.kind is LevelKind.MAX_PAIN
    )
    assert max_pain.price == Decimal("100")


def test_mid_month_boost_and_penalty() -> None:
    """Mid-month gate: +1 counter-trend reversal, -1 late trend-continuation breakout."""
    strategy = ElephantEdgeStrategy(
        use_mid_month_cycle=True,
        mid_month_window_days=(14, 16),
        mid_month_stretch_atr="2.5",
    )
    strategy._context = SimulatedContext()
    for warmed in warmup(14, day=14):  # constant TR 2.0 -> ATR exactly 2.0
        strategy._ingest(warmed)
    assert strategy._atr_value() == Decimal("2.0")

    resistance = Level(
        "r1",
        LevelKind.ELEPHANT_RESISTANCE_1,
        LevelSide.RESISTANCE,
        Decimal("107"),
        Decimal("0.5"),
        0,
    )
    support = Level(
        "s1", LevelKind.ELEPHANT_SUPPORT_1, LevelSide.SUPPORT, Decimal("99"), Decimal("0.5"), 0
    )
    rally = bar(10, 0, "105", "107", "105", "106", day=14)  # stretch 6 >= 2.5x2.0 ATR
    selloff = bar(11, 0, "95", "96", "93", "94", day=14)

    assert strategy._mid_month_adjust(resistance, rally) == 1  # counter-trend short at R
    assert strategy._mid_month_adjust(support, rally) == -1  # late breakout-long into exhaustion
    assert strategy._mid_month_adjust(support, selloff) == 1  # counter-trend long at S
    assert strategy._mid_month_adjust(resistance, selloff) == -1
    # outside the mid-month window the gate is inert
    assert strategy._mid_month_adjust(resistance, bar(10, 0, "105", "107", "105", "106")) == 0
    # below the stretch threshold the gate is inert
    small_rally = bar(10, 0, "100.5", "101", "100", "100.6", day=14)
    assert strategy._mid_month_adjust(resistance, small_rally) == 0


def test_score_clamped_to_upper_four() -> None:
    """Every confluence source fires; the score clamps at the plan ceiling of 4."""
    strategy = ElephantEdgeStrategy()
    resistance = Level(
        "r1",
        LevelKind.ELEPHANT_RESISTANCE_1,
        LevelSide.RESISTANCE,
        Decimal("105"),
        Decimal("0.5"),
        0,
    )
    wall = Level(
        "oi:call:105",
        LevelKind.OI_WALL_CALL,
        LevelSide.RESISTANCE,
        Decimal("105"),
        Decimal("0.5"),
        0,
    )
    level_map = LevelMap(instrument=NIFTY, levels=(resistance, wall))
    score = strategy._score_level(
        resistance, level_map, resistance_snapshot(), bar(10, 0, "104", "106", "104", "105")
    )
    assert score == 4


def test_score_clamped_to_lower_zero() -> None:
    """A mid-month penalty with no positive confluence clamps the score at 0."""
    strategy = ElephantEdgeStrategy(
        use_oi_walls=False,
        use_gamma=False,
        use_order_blocks=False,
        use_pdh_pdl=False,
        use_max_pain=False,
        use_mid_month_cycle=True,
        mid_month_window_days=(14, 16),
        mid_month_stretch_atr="2.5",
    )
    strategy._context = SimulatedContext()
    for warmed in warmup(14, day=14):
        strategy._ingest(warmed)
    support = Level(
        "s1", LevelKind.ELEPHANT_SUPPORT_1, LevelSide.SUPPORT, Decimal("99"), Decimal("0.5"), 0
    )
    level_map = LevelMap(instrument=NIFTY, levels=(support,))
    rally = bar(10, 0, "105", "107", "105", "106", day=14)
    score = strategy._score_level(support, level_map, None, rally)
    assert score == 0


def test_snap_elephant_zones_to_oi_strikes() -> None:
    """Elephant zones within +/-1 strike of an OI wall snap to the wall strike."""
    strategy = ElephantEdgeStrategy(snap_zones_to_oi_strikes=True)
    level_map = LevelMap(
        instrument=NIFTY,
        levels=(
            Level(
                "ee:s1",
                LevelKind.ELEPHANT_SUPPORT_1,
                LevelSide.SUPPORT,
                Decimal("100.8"),
                Decimal("1"),
                0,
            ),
            Level(
                "ee:r1",
                LevelKind.ELEPHANT_RESISTANCE_1,
                LevelSide.RESISTANCE,
                Decimal("105.6"),
                Decimal("1"),
                0,
            ),
            Level(
                "ee:r2",
                LevelKind.ELEPHANT_RESISTANCE_2,
                LevelSide.RESISTANCE,
                Decimal("108.9"),
                Decimal("1"),
                0,
            ),
        ),
    )
    snapshot = OptionsSnapshot(
        instrument=NIFTY,
        legs=(
            OptionLeg(Decimal("100"), "PE", Decimal("5000")),
            OptionLeg(Decimal("102"), "PE", Decimal("100")),
            OptionLeg(Decimal("106"), "CE", Decimal("6000")),
            OptionLeg(Decimal("108"), "CE", Decimal("100")),
        ),
    )
    snapped = {
        level.level_id: level for level in strategy._snap_elephant_zones(level_map, snapshot).levels
    }
    assert snapped["ee:s1"].price == Decimal("100")  # put wall 100
    assert snapped["ee:r1"].price == Decimal("106")  # call wall 106
    assert snapped["ee:r2"].price == Decimal("108")  # call wall 108 (nearest within 1 strike)
