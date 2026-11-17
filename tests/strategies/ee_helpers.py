"""Shared deterministic builders for the Elephant Edge (EE+) strategy tests.

Every price is an exact ``Decimal`` (zero floats, repo rule). Bar timestamps are
IST-aware; the default session date is 2024-03-20 (outside the mid-month
window) so the confluence tests can exercise the mid-month gate explicitly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tantra_strategies import (
    Bar,
    Level,
    LevelKind,
    LevelMap,
    LevelSide,
    OptionLeg,
    OptionsSnapshot,
)

IST = timezone(timedelta(hours=5, minutes=30))
NIFTY = "NSE:NIFTY50-INDEX"
# Default session date: 2024-03-20, deliberately outside the mid-month window.
DAY = 20


def ist(hour: int, minute: int = 0, day: int = DAY, month: int = 3, year: int = 2024) -> datetime:
    """An IST-aware session timestamp."""
    return datetime(year, month, day, hour, minute, tzinfo=IST)


def bar(
    hour: int,
    minute: int,
    open_: str | Decimal,
    high: str | Decimal,
    low: str | Decimal,
    close: str | Decimal,
    volume: int = 100_000,
    instrument: str = NIFTY,
    day: int = DAY,
) -> Bar:
    """One 1-minute bar with exact ``Decimal`` OHLC."""
    return Bar(
        instrument,
        ist(hour, minute, day=day),
        Decimal(str(open_)),
        Decimal(str(high)),
        Decimal(str(low)),
        Decimal(str(close)),
        volume,
    )


def warmup(
    n: int,
    hour: int = 9,
    minute: int = 0,
    base: str | Decimal = "100",
    half_range: str | Decimal = "1",
    volume: int = 100_000,
    instrument: str = NIFTY,
    day: int = DAY,
) -> list[Bar]:
    """``n`` identical 1-minute bars oscillating around ``base`` (constant TR)."""
    base_d = Decimal(str(base))
    spread = Decimal(str(half_range))
    return [
        bar(
            hour,
            minute + i,
            base_d,
            base_d + spread,
            base_d - spread,
            base_d,
            volume,
            instrument,
            day,
        )
        for i in range(n)
    ]


def support_map(
    instrument: str = NIFTY,
    price: str | Decimal = "100",
    half: str | Decimal = "1",
    level_id: str = "s1",
) -> LevelMap:
    """A single seeded support (Elephant) level."""
    return LevelMap(
        instrument=instrument,
        levels=(
            Level(
                level_id,
                LevelKind.ELEPHANT_SUPPORT_1,
                LevelSide.SUPPORT,
                Decimal(str(price)),
                Decimal(str(half)),
                0,
            ),
        ),
    )


def resistance_map(
    instrument: str = NIFTY,
    price: str | Decimal = "105",
    half: str | Decimal = "0.15",
    level_id: str = "r1",
) -> LevelMap:
    """A single seeded resistance (Elephant) level."""
    return LevelMap(
        instrument=instrument,
        levels=(
            Level(
                level_id,
                LevelKind.ELEPHANT_RESISTANCE_1,
                LevelSide.RESISTANCE,
                Decimal(str(price)),
                Decimal(str(half)),
                0,
            ),
        ),
    )


def support_snapshot(instrument: str = NIFTY) -> OptionsSnapshot:
    """Long-gamma chain: building put wall at 100, PCR>1 -> support reversals score 4."""
    return OptionsSnapshot(
        instrument=instrument,
        legs=(
            OptionLeg(
                Decimal("100"),
                "PE",
                Decimal("5000"),
                open_interest_change=Decimal("400"),
                gamma=Decimal("0.01"),
            ),
            OptionLeg(
                Decimal("102"),
                "PE",
                Decimal("3000"),
                open_interest_change=Decimal("100"),
                gamma=Decimal("0.005"),
            ),
            OptionLeg(
                Decimal("100"),
                "CE",
                Decimal("1500"),
                open_interest_change=Decimal("-100"),
                gamma=Decimal("0.02"),
            ),
            OptionLeg(
                Decimal("102"),
                "CE",
                Decimal("1000"),
                open_interest_change=Decimal("50"),
                gamma=Decimal("0.01"),
            ),
        ),
    )


def resistance_snapshot(
    instrument: str = NIFTY,
    wall: str | Decimal = "105",
    delta: str | Decimal = "-300",
) -> OptionsSnapshot:
    """Short-gamma chain: call wall (short-covering ``delta``), PCR<0.75."""
    wall_d = Decimal(str(wall))
    return OptionsSnapshot(
        instrument=instrument,
        legs=(
            OptionLeg(
                wall_d,
                "CE",
                Decimal("6000"),
                open_interest_change=Decimal(str(delta)),
                gamma=Decimal("0.01"),
            ),
            OptionLeg(
                wall_d + Decimal("2"),
                "CE",
                Decimal("2000"),
                open_interest_change=Decimal("-50"),
                gamma=Decimal("0.005"),
            ),
            OptionLeg(
                wall_d,
                "PE",
                Decimal("1500"),
                open_interest_change=Decimal("100"),
                gamma=Decimal("0.02"),
            ),
            OptionLeg(
                wall_d + Decimal("2"),
                "PE",
                Decimal("1000"),
                open_interest_change=Decimal("20"),
                gamma=Decimal("0.01"),
            ),
        ),
    )


def combined_snapshot(instrument: str = NIFTY) -> OptionsSnapshot:
    """Mixed chain: building PE wall at 100 and building CE wall at 105 (PCR<0.75, short gamma)."""
    return OptionsSnapshot(
        instrument=instrument,
        legs=(
            OptionLeg(
                Decimal("100"),
                "PE",
                Decimal("5000"),
                open_interest_change=Decimal("400"),
                gamma=Decimal("0.01"),
            ),
            OptionLeg(
                Decimal("100"),
                "CE",
                Decimal("6000"),
                open_interest_change=Decimal("200"),
                gamma=Decimal("0.02"),
            ),
            OptionLeg(
                Decimal("105"),
                "CE",
                Decimal("2000"),
                open_interest_change=Decimal("100"),
                gamma=Decimal("0.005"),
            ),
            OptionLeg(
                Decimal("105"),
                "PE",
                Decimal("1000"),
                open_interest_change=Decimal("50"),
                gamma=Decimal("0.015"),
            ),
        ),
    )


def drive(strategy, context, bars) -> None:
    """Feed bars one at a time exactly as ``SimulatedContext.run`` would."""
    from tantra_strategies import SimulatedContext

    assert isinstance(context, SimulatedContext)
    for current in bars:
        context.feed(current)
        for event in context._drain_outbox():
            strategy.on_order_event(event)
        strategy.on_bar(current)
