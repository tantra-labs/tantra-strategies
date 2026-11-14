"""Live / feed-backed execution context: strategy-side parity seam (gap 0002).

The canonical Rust traits are owned by ``tantra-market`` (``MarketDataFeed``)
and ``tantra-exec`` (``ExecutionGateway``); the production wiring that bridges
this Python seam to those actors is tracked by gap 0002 (cross-repo).
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Protocol, runtime_checkable

from tantra_strategies.sdk.bar import Bar
from tantra_strategies.sdk.order import (
    OrderEvent,
    OrderRequest,
    OrderSide,
    OrderStatus,
)
from tantra_strategies.sdk.tick import Tick


@runtime_checkable
class MarketDataFeed(Protocol):
    """Canonical feed seam: live prices (mirrors ``tantra-market`` ``MarketDataFeed``)."""

    def current_price(self, instrument: str) -> Decimal: ...


@runtime_checkable
class ExecutionGateway(Protocol):
    """Canonical execution seam: order submission (mirrors ``tantra-exec`` ``ExecutionGateway``)."""

    def submit(self, request: OrderRequest) -> OrderEvent: ...


class LiveContext:
    """Feed + gateway backed execution context for live / paper trading.

    Orders are routed through the injected ``ExecutionGateway``; fills update
    exact ``Decimal`` positions. Prices come from the ``MarketDataFeed`` with a
    locally fed fallback (``feed_bar`` / ``feed_tick``).
    """

    def __init__(
        self,
        feed: MarketDataFeed,
        gateway: ExecutionGateway,
        logger: logging.Logger | None = None,
    ) -> None:
        self._feed = feed
        self._gateway = gateway
        self._prices: dict[str, Decimal] = {}
        self._positions: dict[str, Decimal] = {}
        self.events: list[OrderEvent] = []
        self.orders: list[OrderRequest] = []
        self.logger = logger or logging.getLogger("tantra.live")

    def feed_bar(self, bar: Bar) -> None:
        """Record a bar close as the locally known price."""
        self._prices[bar.instrument] = bar.close

    def feed_tick(self, tick: Tick) -> None:
        """Record a tick's last price as the locally known price."""
        self._prices[tick.instrument] = tick.last_price

    def current_price(self, instrument: str) -> Decimal:
        try:
            return self._feed.current_price(instrument)
        except KeyError:
            price = self._prices.get(instrument)
            if price is None:
                raise
            return price

    def position(self, instrument: str) -> Decimal:
        return self._positions.get(instrument, Decimal(0))

    def submit(self, request: OrderRequest) -> OrderEvent:
        self.orders.append(request)
        event = self._gateway.submit(request)
        self.events.append(event)
        if event.status is OrderStatus.COMPLETE and event.filled_quantity > 0:
            signed = (
                event.filled_quantity if event.side is OrderSide.BUY else -event.filled_quantity
            )
            self._positions[event.instrument] = (
                self._positions.get(event.instrument, Decimal(0)) + signed
            )
        return event

    def run(self, strategy: object, bars: list[Bar]) -> None:
        """Drive a strategy through a bar sequence via the live feed."""
        strategy._context = self  # type: ignore[attr-defined]
        strategy.on_start()  # type: ignore[attr-defined]
        for bar in bars:
            self.feed_bar(bar)
            strategy.on_bar(bar)  # type: ignore[attr-defined]
        strategy.on_stop()  # type: ignore[attr-defined]

    def run_ticks(self, strategy: object, ticks: list[Tick]) -> None:
        """Drive a strategy through a tick sequence via the live feed."""
        strategy._context = self  # type: ignore[attr-defined]
        strategy.on_start()  # type: ignore[attr-defined]
        for tick in ticks:
            self.feed_tick(tick)
            strategy.on_tick(tick)  # type: ignore[attr-defined]
        strategy.on_stop()  # type: ignore[attr-defined]
