"""Tick dispatch: ``Tick`` model, ``run_ticks`` lifecycle, tick-priced fills."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tantra_strategies.sdk import (
    OrderEvent,
    OrderRequest,
    OrderStatus,
    SimulatedContext,
    Strategy,
    Tick,
)
from tantra_strategies.sdk.context import LevelsUnavailable, OptionsUnavailable
from tantra_strategies.sdk.levels import LevelMap, OptionsSnapshot


def make_ticks(
    prices: list[Decimal | int | str],
    instrument: str = "NSE:NIFTY50-INDEX",
) -> list[Tick]:
    """Build a one-minute tick sequence from last-trade prices."""
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        Tick(
            instrument=instrument,
            ts=start + timedelta(minutes=i),
            last_price=Decimal(str(p)),
        )
        for i, p in enumerate(prices)
    ]


class RecordingTickStrategy(Strategy):
    """Records lifecycle hooks and every dispatched tick in order."""

    def __init__(self, **overrides: object) -> None:
        super().__init__(**overrides)
        self.started = False
        self.stopped = False
        self.seen: list[tuple[Decimal, datetime]] = []
        self.events: list[OrderEvent] = []

    def on_start(self) -> None:
        self.started = True

    def on_tick(self, tick: Tick) -> None:
        self.seen.append((tick.last_price, tick.ts))

    def on_order_event(self, event: OrderEvent) -> None:
        self.events.append(event)

    def on_stop(self) -> None:
        self.stopped = True


class BuyOnSecondTickStrategy(RecordingTickStrategy):
    """Buys a fixed quantity on the second dispatched tick."""

    def __init__(self, **overrides: object) -> None:
        super().__init__(**overrides)
        self.tick_count = 0

    def on_tick(self, tick: Tick) -> None:
        super().on_tick(tick)
        self.tick_count += 1
        if self.tick_count == 2:
            self.buy(tick.instrument, Decimal(5))


class BuyLimitOnFirstTickStrategy(RecordingTickStrategy):
    """Places a limit buy on the first dispatched tick."""

    def __init__(self, **overrides: object) -> None:
        super().__init__(**overrides)
        self.tick_count = 0

    def on_tick(self, tick: Tick) -> None:
        super().on_tick(tick)
        self.tick_count += 1
        if self.tick_count == 1:
            self.buy(tick.instrument, Decimal(5), limit_price=Decimal("104"))


def test_tick_model_coerces_and_validates() -> None:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    tick = Tick(instrument="NSE:X", ts=ts, last_price="12.5")
    assert isinstance(tick.last_price, Decimal)
    assert tick.last_price == Decimal("12.5")
    assert Tick(instrument="NSE:X", ts=ts, last_price=10).last_price == Decimal("10")

    with pytest.raises(ValueError):
        Tick(instrument="NSE:X", ts=ts, last_price="-1")
    with pytest.raises(ValueError):
        Tick(
            instrument="NSE:X",
            ts=ts,
            last_price=Decimal("5"),
            bid=Decimal("7"),
            ask=Decimal("6"),
        )

    with pytest.raises(FrozenInstanceError):
        tick.last_price = Decimal("99")  # type: ignore[misc]


def test_run_ticks_dispatches_in_order() -> None:
    prices = [Decimal("100"), Decimal("105"), Decimal("110"), Decimal("108")]
    ticks = make_ticks(prices)
    context = SimulatedContext()
    strategy = RecordingTickStrategy()
    strategy.run_ticks(context, ticks)

    assert strategy.started
    assert strategy.stopped
    assert [price for price, _ in strategy.seen] == prices
    assert [ts for _, ts in strategy.seen] == [tick.ts for tick in ticks]
    assert context.current_price("NSE:NIFTY50-INDEX") == Decimal("108")


def test_tick_order_fills_at_last_tick_price() -> None:
    context = SimulatedContext()
    strategy = BuyOnSecondTickStrategy()
    strategy.run_ticks(context, make_ticks([Decimal("100"), Decimal("105"), Decimal("110")]))

    assert len(strategy.events) == 1
    event = strategy.events[0]
    assert event.status is OrderStatus.COMPLETE
    assert event.price == Decimal("105")
    assert context.position("NSE:NIFTY50-INDEX") == Decimal(5)


def test_resting_limit_order_checked_on_ticks() -> None:
    context = SimulatedContext()
    strategy = BuyLimitOnFirstTickStrategy()
    strategy.run_ticks(context, make_ticks([Decimal("100"), Decimal("103"), Decimal("106")]))

    assert len(strategy.events) == 1
    event = strategy.events[0]
    assert event.status is OrderStatus.COMPLETE
    assert event.filled_quantity == Decimal(5)


def test_tick_run_is_deterministic() -> None:
    ticks = make_ticks([Decimal("100"), Decimal("105"), Decimal("110")])

    def run_once() -> list[tuple[str, OrderStatus, Decimal | None, Decimal]]:
        context = SimulatedContext()
        strategy = BuyOnSecondTickStrategy()
        strategy.run_ticks(context, ticks)
        return [
            (event.order_id, event.status, event.price, event.filled_quantity)
            for event in strategy.events
        ]

    assert run_once() == run_once()


class BareContext:
    """Minimal protocol context: feed/execution only, no drive loop."""

    def __init__(self) -> None:
        self.prices: dict[str, Decimal] = {}
        self.events: list[OrderEvent] = []

    def current_price(self, instrument: str) -> Decimal:
        return self.prices[instrument]

    def position(self, instrument: str) -> Decimal:
        return Decimal(0)

    def level_map(self) -> LevelMap:
        raise LevelsUnavailable("no level map seeded; tracked by tantra-market/docs/gaps/0005")

    def options_snapshot(self, instrument: str, expiry: str | None = None) -> OptionsSnapshot:
        raise OptionsUnavailable("no options seeded; tracked by tantra-data/docs/gaps/0016")

    def submit(self, request: OrderRequest) -> OrderEvent:
        event = OrderEvent(
            order_id="B-1",
            instrument=request.instrument,
            side=request.side,
            status=OrderStatus.COMPLETE,
            quantity=request.quantity,
            filled_quantity=request.quantity,
            price=self.prices[request.instrument],
        )
        self.events.append(event)
        return event


def test_run_ticks_generic_branch() -> None:
    context = BareContext()
    context.prices["NSE:NIFTY50-INDEX"] = Decimal("100")
    ticks = make_ticks([Decimal("100"), Decimal("102"), Decimal("104")])
    strategy = RecordingTickStrategy()
    strategy.run_ticks(context, ticks)

    assert strategy.started
    assert strategy.stopped
    assert [price for price, _ in strategy.seen] == [
        Decimal("100"),
        Decimal("102"),
        Decimal("104"),
    ]
