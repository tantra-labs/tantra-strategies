"""Live / feed-backed context: lifecycle parity with the simulated harness."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from conftest import make_bars

from tantra_strategies.sdk import (
    Bar,
    OrderEvent,
    OrderRequest,
    OrderSide,
    OrderStatus,
    SimulatedContext,
    Strategy,
    Tick,
)
from tantra_strategies.sdk.live import ExecutionGateway, LiveContext, MarketDataFeed


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


class ScriptedFeed:
    """In-memory feed: prices dict served through ``current_price``."""

    def __init__(self) -> None:
        self.prices: dict[str, Decimal] = {}

    def current_price(self, instrument: str) -> Decimal:
        return self.prices[instrument]

    def set_price(self, instrument: str, price: Decimal) -> None:
        self.prices[instrument] = price


class ScriptedGateway:
    """Immediate-fill gateway that executes at the current feed price."""

    def __init__(self, feed: ScriptedFeed) -> None:
        self._feed = feed
        self._counter = 0
        self.submissions: list[OrderRequest] = []

    def submit(self, request: OrderRequest) -> OrderEvent:
        self._counter += 1
        self.submissions.append(request)
        return OrderEvent(
            order_id=f"LIVE-{self._counter:05d}",
            instrument=request.instrument,
            side=request.side,
            status=OrderStatus.COMPLETE,
            quantity=request.quantity,
            filled_quantity=request.quantity,
            price=self._feed.current_price(request.instrument),
        )


class WiredLiveContext(LiveContext):
    """Live context whose feed mirrors each fed bar/tick (as a live feed would)."""

    def feed_bar(self, bar: Bar) -> None:
        super().feed_bar(bar)
        self._feed.set_price(bar.instrument, bar.close)  # type: ignore[attr-defined]

    def feed_tick(self, tick: Tick) -> None:
        super().feed_tick(tick)
        self._feed.set_price(tick.instrument, tick.last_price)  # type: ignore[attr-defined]


class LiveBuyStrategy(Strategy):
    """Buys on the third bar and on the second tick."""

    def __init__(self, **overrides: object) -> None:
        super().__init__(**overrides)
        self.started = False
        self.stopped = False
        self.bar_count = 0
        self.tick_count = 0
        self.events: list[OrderEvent] = []

    def on_start(self) -> None:
        self.started = True

    def on_bar(self, bar: Bar) -> None:
        self.bar_count += 1
        if self.bar_count == 3:
            self.buy(bar.instrument, Decimal(5))

    def on_tick(self, tick: Tick) -> None:
        self.tick_count += 1
        if self.tick_count == 2:
            self.buy(tick.instrument, Decimal(5))

    def on_order_event(self, event: OrderEvent) -> None:
        self.events.append(event)

    def on_stop(self) -> None:
        self.stopped = True


class PriceProbeStrategy(Strategy):
    """Probes ``current_price`` for an instrument and records result or error."""

    def __init__(self, **overrides: object) -> None:
        super().__init__(**overrides)
        self.probe: Decimal | None = None
        self.error: KeyError | None = None

    def on_bar(self, bar: Bar) -> None:
        try:
            self.probe = self.current_price("NSE:X")
        except KeyError as exc:
            self.error = exc


class BareBarContext:
    """Protocol context for bars: feed/execution only, no drive loop."""

    def __init__(self) -> None:
        self.prices: dict[str, Decimal] = {}
        self.events: list[OrderEvent] = []

    def current_price(self, instrument: str) -> Decimal:
        return self.prices[instrument]

    def position(self, instrument: str) -> Decimal:
        return Decimal(0)

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


def test_live_run_drives_lifecycle_and_routes_orders() -> None:
    feed = ScriptedFeed()
    gateway = ScriptedGateway(feed)
    context = WiredLiveContext(feed, gateway)
    strategy = LiveBuyStrategy()
    strategy.run(context, make_bars([Decimal(100)] * 5))

    assert isinstance(feed, MarketDataFeed)
    assert isinstance(gateway, ExecutionGateway)
    assert strategy.started
    assert strategy.stopped
    assert strategy.bar_count == 5
    assert len(context.orders) == 1
    assert len(gateway.submissions) == 1
    assert len(strategy.events) == 1
    event = strategy.events[0]
    assert event.status is OrderStatus.COMPLETE
    assert context.position("NSE:NIFTY50-INDEX") == Decimal(5)


def test_live_sim_parity() -> None:
    bars = make_bars([Decimal(100), Decimal(105), Decimal(110)])

    sim = SimulatedContext()
    sim_strategy = LiveBuyStrategy()
    sim_strategy.run(sim, bars)

    feed = ScriptedFeed()
    gateway = ScriptedGateway(feed)
    live = WiredLiveContext(feed, gateway)
    live_strategy = LiveBuyStrategy()
    live_strategy.run(live, bars)

    def stream(
        strategy: LiveBuyStrategy,
    ) -> list[tuple[OrderSide, OrderStatus, Decimal, Decimal | None, Decimal]]:
        return [(e.side, e.status, e.quantity, e.price, e.filled_quantity) for e in strategy.events]

    assert stream(live_strategy) == stream(sim_strategy)


def test_live_run_ticks() -> None:
    feed = ScriptedFeed()
    gateway = ScriptedGateway(feed)
    live = WiredLiveContext(feed, gateway)
    strategy = LiveBuyStrategy()
    ticks = make_ticks([Decimal(100), Decimal(105), Decimal(110)])
    strategy.run_ticks(live, ticks)

    assert strategy.tick_count == 3
    assert len(strategy.events) == 1
    event = strategy.events[0]
    assert event.status is OrderStatus.COMPLETE
    assert event.price == Decimal(105)


def test_live_current_price_from_feed_with_local_fallback() -> None:
    # feed price wins when the feed has the instrument
    feed = ScriptedFeed()
    feed.set_price("NSE:X", Decimal("300"))
    live = WiredLiveContext(feed, ScriptedGateway(feed))
    strategy = PriceProbeStrategy()
    strategy.run(live, make_bars([Decimal(100)]))
    assert strategy.probe == Decimal("300")
    assert strategy.error is None

    # local fallback when the feed has no price for the instrument
    feed = ScriptedFeed()
    live = LiveContext(feed, ScriptedGateway(feed))
    live.feed_tick(
        Tick(
            instrument="NSE:X",
            ts=datetime(2024, 1, 1, tzinfo=UTC),
            last_price=Decimal("200"),
        )
    )
    strategy = PriceProbeStrategy()
    strategy.run(live, make_bars([Decimal(100)]))
    assert strategy.probe == Decimal("200")
    assert strategy.error is None

    # KeyError propagates when neither the feed nor local prices have it
    feed = ScriptedFeed()
    live = LiveContext(feed, ScriptedGateway(feed))
    strategy = PriceProbeStrategy()
    strategy.run(live, make_bars([Decimal(100)]))
    assert strategy.probe is None
    assert isinstance(strategy.error, KeyError)


def test_bare_protocol_context_driven_by_strategy_run() -> None:
    context = BareBarContext()
    context.prices["NSE:NIFTY50-INDEX"] = Decimal("100")
    strategy = LiveBuyStrategy()
    strategy.run(context, make_bars([Decimal(100)] * 3))

    assert strategy.started
    assert strategy.stopped
    assert strategy.bar_count == 3
    assert len(context.events) == 1
