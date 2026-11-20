"""Bridge a ``tantra`` wheel strategy host to an SDK :class:`Strategy`.

The SDK strategy runs against a private :class:`SimulatedContext`. After every
bar the bridge *reconciles positions*: it sends the wheel host the signed delta
between the SDK position (which only moves on fills) and the host position.
Resting orders (e.g. OCO bracket legs) are therefore never forwarded until they
fill, a fill that arrives while the host is ``busy`` is retried on the next bar
instead of being lost, and an SDK exit can never open an unintended host short.

This module deliberately does not import the ``tantra`` wheel; the wheel side is
typed structurally with :class:`typing.Protocol`.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Protocol

from tantra_strategies.sdk.bar import Bar
from tantra_strategies.sdk.context import SimulatedContext
from tantra_strategies.sdk.scene import OverlayScene
from tantra_strategies.sdk.strategy import Strategy


class WheelInstrument(Protocol):
    symbol: str
    exchange: str


class WheelBar(Protocol):
    instrument_id: Any
    ts: Any
    open: Any
    high: Any
    low: Any
    close: Any


class WheelHost(Protocol):
    def buy(self, instrument_id: Any, quantity: Any) -> Any: ...

    def sell(self, instrument_id: Any, quantity: Any) -> Any: ...

    def position(self, instrument_id: Any) -> Any: ...


def _as_sdk_instrument(symbol: str, exchange: str) -> str:
    return symbol if ":" in symbol else f"{exchange}:{symbol}"


def _coerce_datetime(ts: object) -> dt.datetime:
    """Normalise a wheel bar timestamp to an aware UTC ``datetime``.

    The wheel engine (``tantra_examples`` ``StrategyRunner``) stamps bars with integer
    epoch nanoseconds; hand-built bars may carry a ``datetime`` or an ISO-8601 string.
    """
    if isinstance(ts, dt.datetime):
        return ts
    if isinstance(ts, int) and not isinstance(ts, bool):
        seconds, nanos = divmod(ts, 1_000_000_000)
        return dt.datetime.fromtimestamp(seconds, tz=dt.UTC) + dt.timedelta(
            microseconds=nanos // 1_000
        )
    return dt.datetime.fromisoformat(str(ts))


class WheelSdkBridge:
    """Run an SDK strategy inside a wheel strategy host."""

    def __init__(
        self,
        factory: Callable[[str], Strategy],
        *,
        symbol: str,
        exchange: str,
        empty_scene_id: str,
    ) -> None:
        self._factory = factory
        self._config_symbol = symbol
        self._instrument = _as_sdk_instrument(symbol, exchange)
        self._empty_scene_id = empty_scene_id
        self._sim = SimulatedContext()
        self._strategy: Strategy | None = None
        self._bars_seen = 0

    @property
    def sdk_strategy(self) -> Strategy | None:
        return self._strategy

    @property
    def instrument(self) -> str:
        return self._instrument

    def start(self) -> None:
        self._sim = SimulatedContext()
        self._bars_seen = 0
        self._build()

    def _build(self) -> None:
        strategy = self._factory(self._instrument)
        strategy._context = self._sim
        strategy.on_start()
        self._strategy = strategy

    def on_wheel_bar(self, host: Any, bar: Any) -> None:
        if self._strategy is None:
            self.start()
        assert self._strategy is not None

        iid = bar.instrument_id
        bar_instrument = f"{iid.exchange}:{iid.symbol}"
        if bar_instrument != self._instrument and iid.symbol != self._config_symbol:
            if self._bars_seen:
                return
            self._instrument = bar_instrument
            self._build()
        assert self._strategy is not None

        sdk_bar = Bar(
            instrument=self._instrument,
            ts=_coerce_datetime(bar.ts),
            open=Decimal(str(bar.open)),
            high=Decimal(str(bar.high)),
            low=Decimal(str(bar.low)),
            close=Decimal(str(bar.close)),
            volume=int(getattr(bar, "volume", 0)),
        )
        self._bars_seen += 1
        self._sim.feed(sdk_bar)
        for event in self._sim._drain_outbox():
            self._strategy.on_order_event(event)
        self._strategy.on_bar(sdk_bar)
        self.reconcile(host, iid)

    def reconcile(self, host: Any, iid: Any) -> None:
        """Bring the host position to the SDK position (no-op while the host is busy)."""
        ctx = getattr(host, "ctx", None)
        if ctx is not None and ctx.busy(iid):
            return  # pending host intent: retry on the next bar, never drop the delta
        target = self._sim.position(self._instrument)
        held = Decimal(str(host.position(iid)))
        delta = target - held
        if delta > 0:
            host.buy(iid, delta)
        elif delta < 0:
            host.sell(iid, -delta)

    def emit_scene(self) -> OverlayScene:
        if self._strategy is None:
            return OverlayScene(
                strategy_id=self._empty_scene_id, symbol=self._instrument, timeframe="1m"
            )
        return self._strategy.emit_scene()  # type: ignore[attr-defined,no-any-return]

    def stop(self) -> None:
        if self._strategy is not None:
            self._strategy.on_stop()
