from decimal import Decimal

import pytest

from tantra_strategies import (
    Level,
    LevelKind,
    LevelMap,
    LevelSide,
    OptionLeg,
    OptionsSnapshot,
    OrderSide,
    PositionIntent,
    SignalKind,
    StrategySignal,
)


def test_level_validation_and_band() -> None:
    with pytest.raises(ValueError):
        Level(
            level_id="l1",
            kind=LevelKind.ELEPHANT_SUPPORT_1,
            side=LevelSide.SUPPORT,
            price=Decimal("0"),
        )
    with pytest.raises(ValueError):
        Level(
            level_id="l1",
            kind=LevelKind.ELEPHANT_SUPPORT_1,
            side=LevelSide.SUPPORT,
            price=Decimal("100"),
            score=5,
        )
    with pytest.raises(ValueError):
        Level(
            level_id="l1",
            kind=LevelKind.ELEPHANT_SUPPORT_1,
            side=LevelSide.SUPPORT,
            price=Decimal("100"),
            band_half_width=Decimal("-1"),
        )
    level = Level(
        level_id="l1",
        kind=LevelKind.ELEPHANT_SUPPORT_1,
        side=LevelSide.SUPPORT,
        price=Decimal("100"),
        band_half_width=Decimal("0.5"),
        score=2,
        source="tantra-market",
    )
    assert level.band() == (Decimal("99.5"), Decimal("100.5"))


def test_level_map_supports_resistances() -> None:
    level_map = LevelMap(
        instrument="NSE:NIFTY50-INDEX",
        levels=(
            Level("s1", LevelKind.ELEPHANT_SUPPORT_1, LevelSide.SUPPORT, Decimal("100")),
            Level("s2", LevelKind.ELEPHANT_SUPPORT_2, LevelSide.BOTH, Decimal("98")),
            Level("r1", LevelKind.ELEPHANT_RESISTANCE_1, LevelSide.RESISTANCE, Decimal("110")),
            Level("r2", LevelKind.ELEPHANT_RESISTANCE_2, LevelSide.BOTH, Decimal("112")),
        ),
    )
    assert {level.level_id for level in level_map.supports()} == {"s1", "s2", "r2"}
    assert {level.level_id for level in level_map.resistances()} == {"r1", "r2", "s2"}


def test_level_map_overlapping() -> None:
    level_map = LevelMap(
        instrument="NSE:NIFTY50-INDEX",
        levels=(
            Level(
                "s1",
                LevelKind.ELEPHANT_SUPPORT_1,
                LevelSide.SUPPORT,
                Decimal("100"),
                band_half_width=Decimal("1"),
            ),
            Level(
                "r1",
                LevelKind.ELEPHANT_RESISTANCE_1,
                LevelSide.RESISTANCE,
                Decimal("110"),
                band_half_width=Decimal("2"),
            ),
            Level(
                "s2",
                LevelKind.PREVIOUS_DAY_OHLC,
                LevelSide.BOTH,
                Decimal("105"),
            ),
        ),
    )
    assert {level.level_id for level in level_map.overlapping(Decimal("100.5"))} == {"s1"}
    assert {level.level_id for level in level_map.overlapping(Decimal("99"))} == {"s1"}
    assert level_map.overlapping(Decimal("50")) == ()
    assert {
        level.level_id for level in level_map.overlapping(Decimal("108.5"), width=Decimal("1"))
    } == {"r1"}
    # exactly at the window/band boundary counts as an overlap
    assert {
        level.level_id for level in level_map.overlapping(Decimal("107"), width=Decimal("1"))
    } == {"r1"}


def test_strategy_signal_and_position_intent() -> None:
    signal = StrategySignal(
        instrument="NSE:NIFTY50-INDEX",
        side=OrderSide.BUY,
        kind=SignalKind.BREAKOUT,
        ref_levels=("r1",),
        confidence=Decimal("80"),
    )
    assert signal.confidence == Decimal("80")
    assert signal.ref_levels == ("r1",)
    with pytest.raises(ValueError):
        StrategySignal(
            instrument="NSE:NIFTY50-INDEX",
            side=OrderSide.BUY,
            kind=SignalKind.BREAKOUT,
            confidence=Decimal("101"),
        )
    with pytest.raises(ValueError):
        StrategySignal(
            instrument="NSE:NIFTY50-INDEX",
            side=OrderSide.BUY,
            kind=SignalKind.BREAKOUT,
            confidence=Decimal("-1"),
        )
    intent = PositionIntent(
        instrument="NSE:NIFTY50-INDEX",
        side=OrderSide.BUY,
        quantity=Decimal("50"),
        entry=Decimal("101"),
        stop=Decimal("99.75"),
    )
    assert intent.quantity == Decimal("50")
    with pytest.raises(ValueError):
        PositionIntent(
            instrument="NSE:NIFTY50-INDEX",
            side=OrderSide.BUY,
            quantity=Decimal("0"),
            entry=Decimal("101"),
            stop=Decimal("99.75"),
        )


def test_options_snapshot_walls_and_max_pain() -> None:
    snapshot = OptionsSnapshot(
        instrument="NFO:NIFTY24NOV24000CE",
        expiry="2024-11-28",
        underlying_spot=Decimal("24400"),
        legs=(
            OptionLeg(strike=Decimal("24300"), option_type="CE", open_interest=Decimal("5000")),
            OptionLeg(strike=Decimal("24400"), option_type="CE", open_interest=Decimal("8000")),
            OptionLeg(strike=Decimal("24300"), option_type="PE", open_interest=Decimal("7000")),
            OptionLeg(strike=Decimal("24400"), option_type="PE", open_interest=Decimal("3000")),
        ),
    )
    assert snapshot.max_pain() == Decimal("24300")
    assert [leg.strike for leg in snapshot.call_walls(1)] == [Decimal("24400")]
    assert [leg.strike for leg in snapshot.put_walls(1)] == [Decimal("24300")]
    assert OptionsSnapshot(instrument="NFO:NIFTY24NOV24000CE").max_pain() is None
