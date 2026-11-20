"""Execution contexts: protocol + deterministic simulated harness."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Protocol, runtime_checkable

from tantra_strategies.sdk.bar import Bar
from tantra_strategies.sdk.levels import LevelMap, OptionsSnapshot
from tantra_strategies.sdk.order import (
    OrderEvent,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
)
from tantra_strategies.sdk.tick import Tick


class LevelsUnavailable(RuntimeError):
    """Level-map data unavailable. Upstream: tantra-core plan 0003 / tantra-market gap 0005."""


class OptionsUnavailable(RuntimeError):
    """Option-chain snapshot unavailable. Upstream: tantra-data gap 0016."""


@runtime_checkable
class StrategyContext(Protocol):
    """The execution environment a strategy runs against (sim or live).

    Level-map and options-context surfaces degrade honestly: sim contexts are
    seedable; live contexts raise ``LevelsUnavailable`` / ``OptionsUnavailable``
    when no feed is wired.
    """

    def submit(self, request: OrderRequest) -> OrderEvent: ...
    def current_price(self, instrument: str) -> Decimal: ...
    def position(self, instrument: str) -> Decimal: ...
    def level_map(self) -> LevelMap: ...
    def options_snapshot(self, instrument: str, expiry: str | None = None) -> OptionsSnapshot: ...


class SimulatedContext:
    """Deterministic offline execution context.

    Market orders fill immediately at the current bar's close. Plain limit
    orders fill when the close has already crossed the limit, otherwise they
    rest and are re-checked on every subsequent bar's close.

    ``STOP_MARKET`` orders and any order carrying an ``oco_group`` are filled
    intrabar against the bar range: a sell stop fills at ``min(open, stop)``
    when ``low <= stop``, a buy stop at ``max(open, stop)`` when
    ``high >= stop`` (gap-through fills at the open); an OCO sell limit fills at
    ``max(open, limit)`` when ``high >= limit``, a buy limit at
    ``min(open, limit)`` when ``low <= limit``. When one OCO leg fills, its
    siblings are removed and CANCELLED events are emitted; if several legs
    trigger on one bar the stop leg wins. Ticks are evaluated as a
    degenerate bar at the last price. Positions are exact ``Decimal``
    arithmetic.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._bars: dict[str, Bar] = {}
        self._prices: dict[str, Decimal] = {}
        self._positions: dict[str, Decimal] = {}
        self._resting: list[tuple[str, OrderRequest]] = []
        # OCO groups with a filled leg: later legs of the group are cancelled on
        # submit so a bracket can never leave an orphaned leg resting.
        self._closed_groups: set[str] = set()
        self._outbox: list[OrderEvent] = []
        self._counter = 0
        self._level_map: LevelMap | None = None
        self._options: dict[tuple[str, str | None], OptionsSnapshot] = {}
        self.events: list[OrderEvent] = []
        self.orders: list[OrderRequest] = []
        self.logger = logger or logging.getLogger("tantra.strategy")

    def feed(self, bar: Bar) -> None:
        """Deliver a new bar; resting orders are evaluated (see class docstring)."""
        self._bars[bar.instrument] = bar
        self._prices[bar.instrument] = bar.close
        self._process_resting(bar.instrument, bar.open, bar.high, bar.low, bar.close)

    def feed_tick(self, tick: Tick) -> None:
        """Deliver a new tick; resting limit orders are evaluated at its price."""
        self._prices[tick.instrument] = tick.last_price
        last = tick.last_price
        self._process_resting(tick.instrument, last, last, last, last)

    def current_price(self, instrument: str) -> Decimal:
        price = self._prices.get(instrument)
        if price is None:
            raise KeyError(f"no price fed for {instrument}")
        return price

    def position(self, instrument: str) -> Decimal:
        return self._positions.get(instrument, Decimal(0))

    def seed_level_map(self, level_map: LevelMap) -> None:
        """Seed the level map the strategy will see via ``level_map()``."""
        self._level_map = level_map

    def seed_options(self, snapshot: OptionsSnapshot) -> None:
        """Seed an options snapshot, keyed by (instrument, expiry)."""
        self._options[(snapshot.instrument, snapshot.expiry)] = snapshot

    def level_map(self) -> LevelMap:
        if self._level_map is None:
            raise LevelsUnavailable(
                "no level map seeded; indicator feeds tracked by tantra-market/docs/gaps/0005"
            )
        return self._level_map

    def options_snapshot(self, instrument: str, expiry: str | None = None) -> OptionsSnapshot:
        snapshot = self._options.get((instrument, expiry))
        if snapshot is None:
            raise OptionsUnavailable(
                f"no options snapshot for {instrument} expiry={expiry}; "
                "tracked by tantra-data/docs/gaps/0016"
            )
        return snapshot

    def submit(self, request: OrderRequest) -> OrderEvent:
        self._counter += 1
        order_id = f"SIM-{self._counter:05d}"
        self.orders.append(request)
        price = self.current_price(request.instrument)

        if request.oco_group is not None and request.oco_group in self._closed_groups:
            return self._cancelled(order_id, request)
        if request.order_type is OrderType.MARKET:
            return self._fill(order_id, request, price)
        if request.order_type is OrderType.STOP_MARKET and request.stop_price is not None:
            stop = request.stop_price
            if (request.side is OrderSide.SELL and price <= stop) or (
                request.side is OrderSide.BUY and price >= stop
            ):
                return self._fill_leg(order_id, request, price)
            self._resting.append((order_id, request))
            return self._open_event(order_id, request)
        if request.limit_price is not None:
            crossed = (request.side is OrderSide.BUY and price <= request.limit_price) or (
                request.side is OrderSide.SELL and price >= request.limit_price
            )
            if crossed:
                return self._fill_leg(order_id, request, request.limit_price)
            self._resting.append((order_id, request))
        return self._open_event(order_id, request)

    def _fill_leg(self, order_id: str, request: OrderRequest, price: Decimal) -> OrderEvent:
        """Immediate fill on submit; closes the request's OCO group, if any."""
        event = self._fill(order_id, request, price)
        if request.oco_group is not None:
            self._closed_groups.add(request.oco_group)
            self._cancel_group(request.oco_group)
        return event

    def _open_event(self, order_id: str, request: OrderRequest) -> OrderEvent:
        event = OrderEvent(
            order_id=order_id,
            instrument=request.instrument,
            side=request.side,
            status=OrderStatus.OPEN,
            quantity=request.quantity,
            filled_quantity=Decimal(0),
            price=None,
        )
        self.events.append(event)
        return event

    def run(self, strategy: object, bars: list[Bar]) -> None:
        """Drive a strategy through a bar sequence deterministically."""
        strategy._context = self  # type: ignore[attr-defined]
        strategy.on_start()  # type: ignore[attr-defined]
        for bar in bars:
            self.feed(bar)
            for event in self._drain_outbox():
                strategy.on_order_event(event)  # type: ignore[attr-defined]
            strategy.on_bar(bar)  # type: ignore[attr-defined]
        strategy.on_stop()  # type: ignore[attr-defined]

    # gap 0001 (tantra-strategies/docs/gaps/0001-*): tick dispatch entry point.
    def run_ticks(self, strategy: object, ticks: list[Tick]) -> None:
        """Drive a strategy through a tick sequence deterministically."""
        strategy._context = self  # type: ignore[attr-defined]
        strategy.on_start()  # type: ignore[attr-defined]
        for tick in ticks:
            self.feed_tick(tick)
            for event in self._drain_outbox():
                strategy.on_order_event(event)  # type: ignore[attr-defined]
            strategy.on_tick(tick)  # type: ignore[attr-defined]
        strategy.on_stop()  # type: ignore[attr-defined]

    # -- internals ----------------------------------------------------------
    def _process_resting(
        self, instrument: str, open_: Decimal, high: Decimal, low: Decimal, close: Decimal
    ) -> None:
        """Evaluate resting orders of ``instrument`` against an OHLC range."""
        triggered: list[tuple[str, OrderRequest, Decimal]] = []
        for order_id, request in self._resting:
            if request.instrument != instrument:
                continue
            fill_price = self._trigger_price(request, open_, high, low, close)
            if fill_price is not None:
                triggered.append((order_id, request, fill_price))
        if not triggered:
            return
        winners: list[tuple[str, OrderRequest, Decimal]] = []
        groups_done: set[str] = set()
        for entry in triggered:
            group = entry[1].oco_group
            if group is None:
                winners.append(entry)
            elif group not in groups_done:
                groups_done.add(group)
                legs = [e for e in triggered if e[1].oco_group == group]
                stops = [e for e in legs if e[1].order_type is OrderType.STOP_MARKET]
                winners.append((stops or legs)[0])
        filled_ids = {w[0] for w in winners}
        self._resting = [r for r in self._resting if r[0] not in filled_ids]
        for order_id, request, fill_price in winners:
            self._outbox.append(self._fill(order_id, request, fill_price))
            if request.oco_group is not None:
                self._closed_groups.add(request.oco_group)
                self._cancel_group(request.oco_group)

    @staticmethod
    def _trigger_price(
        request: OrderRequest, open_: Decimal, high: Decimal, low: Decimal, close: Decimal
    ) -> Decimal | None:
        """Fill price if the range triggers ``request``, else ``None``."""
        sell = request.side is OrderSide.SELL
        if request.order_type is OrderType.STOP_MARKET and request.stop_price is not None:
            stop = request.stop_price
            if sell:
                return min(open_, stop) if low <= stop else None
            return max(open_, stop) if high >= stop else None
        limit = request.limit_price
        if limit is None:
            return close
        if request.oco_group is not None:
            if sell:
                return max(open_, limit) if high >= limit else None
            return min(open_, limit) if low <= limit else None
        crossed = close >= limit if sell else close <= limit
        return limit if crossed else None

    def _cancel_group(self, group: str) -> None:
        keep: list[tuple[str, OrderRequest]] = []
        for order_id, request in self._resting:
            if request.oco_group == group:
                self._outbox.append(self._cancelled(order_id, request))
            else:
                keep.append((order_id, request))
        self._resting = keep

    def _cancelled(self, order_id: str, request: OrderRequest) -> OrderEvent:
        event = OrderEvent(
            order_id=order_id,
            instrument=request.instrument,
            side=request.side,
            status=OrderStatus.CANCELLED,
            quantity=request.quantity,
            filled_quantity=Decimal(0),
            price=None,
        )
        self.events.append(event)
        return event

    def cancel(self, order_id: str) -> OrderEvent | None:
        """Cancel a resting order; ``None`` if it is not resting."""
        for index, (resting_id, request) in enumerate(self._resting):
            if resting_id == order_id:
                del self._resting[index]
                return self._cancelled(order_id, request)
        return None

    def _fill(self, order_id: str, request: OrderRequest, price: Decimal) -> OrderEvent:
        signed = request.quantity if request.side is OrderSide.BUY else -request.quantity
        self._positions[request.instrument] = (
            self._positions.get(request.instrument, Decimal(0)) + signed
        )
        event = OrderEvent(
            order_id=order_id,
            instrument=request.instrument,
            side=request.side,
            status=OrderStatus.COMPLETE,
            quantity=request.quantity,
            filled_quantity=request.quantity,
            price=price,
        )
        self.events.append(event)
        return event

    def _drain_outbox(self) -> list[OrderEvent]:
        events, self._outbox = self._outbox, []
        return events
