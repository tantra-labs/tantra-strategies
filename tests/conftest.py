"""Shared fixtures: deterministic bar builders."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tantra_strategies import Bar


def make_bars(
    closes: list[Decimal | int | str],
    instrument: str = "NSE:NIFTY50-INDEX",
    start: datetime | None = None,
) -> list[Bar]:
    """Build a daily bar sequence from closing prices (OHLC = close)."""
    day = start or datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    for i, close in enumerate(closes):
        value = close if isinstance(close, Decimal) else Decimal(str(close))
        bars.append(
            Bar(
                instrument=instrument,
                ts=day + timedelta(days=i),
                open=value,
                high=value,
                low=value,
                close=value,
                volume=100_000,
            )
        )
    return bars


@pytest.fixture
def trending_closes() -> list[Decimal]:
    """A rising then falling series that triggers a turtle breakout and exit."""
    values = [Decimal(100) + Decimal(i) for i in range(30)] + [
        Decimal(130) - Decimal(i) for i in range(15)
    ]
    return values


def basket_bars(
    members: list[str],
    closes: list[list[Decimal | int | str]],
    start: datetime | None = None,
) -> list[Bar]:
    """Interleaved daily bars for a basket: one bar per member per session day.

    ``closes`` is ``[session][member]``; every session must have exactly one
    close per member. Timestamps advance one day per session, so the first bar
    of a session is a driving bar.
    """
    day = start or datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    for i, session in enumerate(closes):
        if len(session) != len(members):
            raise ValueError(f"session {i}: expected {len(members)} closes, got {len(session)}")
        for member, close in zip(members, session, strict=True):
            value = close if isinstance(close, Decimal) else Decimal(str(close))
            bars.append(
                Bar(
                    instrument=member,
                    ts=day + timedelta(days=i),
                    open=value,
                    high=value,
                    low=value,
                    close=value,
                    volume=100_000,
                )
            )
    return bars
