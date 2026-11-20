"""Strategy base class: lifecycle hooks, order helpers, indicator registry."""

from __future__ import annotations

import logging
from decimal import Decimal

from tantra_strategies.sdk.bar import Bar
from tantra_strategies.sdk.context import StrategyContext
from tantra_strategies.sdk.indicators import (
    ATR,
    EMA,
    RSI,
    SMA,
    BollingerBands,
    Indicator,
)
from tantra_strategies.sdk.order import (
    OrderEvent,
    OrderRequest,
    OrderSide,
    OrderType,
)
from tantra_strategies.sdk.stop_protection import StopProtection, StopUpdate, TrailMode
from tantra_strategies.sdk.tick import Tick


class IndicatorRegistry:
    """Per-(instrument, kind, params) indicator store.

    A strategy requests ``self.indicators.sma("NSE:NIFTY50-INDEX", 20)`` once
    in ``on_start``; the same streaming instance is then fed by every bar.
    """

    def __init__(self) -> None:
        self._store: dict[tuple[object, ...], Indicator | BollingerBands] = {}

    def sma(self, instrument: str, period: int) -> SMA:
        return self._get(("sma", instrument, period), SMA(period))  # type: ignore[return-value]

    def ema(self, instrument: str, period: int) -> EMA:
        return self._get(("ema", instrument, period), EMA(period))  # type: ignore[return-value]

    def rsi(self, instrument: str, period: int = 14) -> RSI:
        return self._get(("rsi", instrument, period), RSI(period))  # type: ignore[return-value]

    def atr(self, instrument: str, period: int = 14) -> ATR:
        return self._get(("atr", instrument, period), ATR(period))  # type: ignore[return-value]

    def bollinger(
        self, instrument: str, period: int = 20, deviations: Decimal | int = 2
    ) -> BollingerBands:
        key = ("bollinger", instrument, period, str(deviations))
        if key not in self._store:
            self._store[key] = BollingerBands(period, deviations)
        return self._store[key]  # type: ignore[return-value]

    def _get(
        self, key: tuple[object, ...], indicator: Indicator | BollingerBands
    ) -> Indicator | BollingerBands:
        if key not in self._store:
            self._store[key] = indicator
        return self._store[key]


class Strategy:
    """Base class for Tantra strategies.

    Lifecycle hooks (Jesse-style): ``on_start``, ``on_bar``, ``on_tick``,
    ``on_order_event``, ``on_stop_update``, ``on_stop``. Orders are authored
    through ``self.buy`` / ``self.sell`` or ``self.submit``; indicators are
    declared in ``on_start`` via ``self.indicators``.
    """

    def __init__(self, **overrides: object) -> None:
        self._context: StrategyContext | None = None
        self._indicators = IndicatorRegistry()
        self._logger = logging.getLogger(f"{type(self).__module__}.{type(self).__name__}")
        for name, value in overrides.items():
            setattr(self, name, value)

    # -- lifecycle hooks (overridable) -------------------------------------
    def on_start(self) -> None: ...
    def on_bar(self, bar: Bar) -> None: ...
    def on_tick(self, tick: Tick) -> None: ...
    def on_order_event(self, event: OrderEvent) -> None: ...
    def on_stop_update(self, event: StopUpdate) -> None: ...
    def on_stop(self) -> None: ...

    # -- execution ----------------------------------------------------------
    def buy(
        self, instrument: str, quantity: Decimal | int | str, limit_price: Decimal | None = None
    ) -> OrderEvent:
        return self.submit(
            OrderRequest(
                instrument=instrument,
                side=OrderSide.BUY,
                quantity=self._qty(quantity),
                order_type=OrderType.MARKET if limit_price is None else OrderType.LIMIT,
                limit_price=limit_price,
                tag="strategy.buy",
            )
        )

    def sell(
        self, instrument: str, quantity: Decimal | int | str, limit_price: Decimal | None = None
    ) -> OrderEvent:
        return self.submit(
            OrderRequest(
                instrument=instrument,
                side=OrderSide.SELL,
                quantity=self._qty(quantity),
                order_type=OrderType.MARKET if limit_price is None else OrderType.LIMIT,
                limit_price=limit_price,
                tag="strategy.sell",
            )
        )

    def bracket(
        self,
        instrument: str,
        *,
        position_side: OrderSide,
        quantity: Decimal | int | str,
        stop: Decimal,
        target: Decimal,
        group: str | None = None,
    ) -> tuple[OrderEvent, OrderEvent]:
        """Place OCO exit legs for an open position; returns ``(stop_event, target_event)``.

        Legs are on the side opposite ``position_side``: a ``STOP_MARKET`` at
        ``stop`` (tag ``bracket.stop``) and a ``LIMIT`` at ``target`` (tag
        ``bracket.target``) sharing one ``oco_group``. ``SimulatedContext``
        enforces the OCO natively and fills intrabar; live OCO enforcement is
        delegated to the ``ExecutionGateway`` (runtime synthetic-OCO).
        """
        self._bracket_count = getattr(self, "_bracket_count", 0) + 1
        oco = group if group is not None else f"bracket-{self._bracket_count}"
        exit_side = OrderSide.SELL if position_side is OrderSide.BUY else OrderSide.BUY
        qty = self._qty(quantity)
        stop_event = self.submit(
            OrderRequest(
                instrument=instrument,
                side=exit_side,
                quantity=qty,
                order_type=OrderType.STOP_MARKET,
                stop_price=stop,
                tag="bracket.stop",
                oco_group=oco,
            )
        )
        target_event = self.submit(
            OrderRequest(
                instrument=instrument,
                side=exit_side,
                quantity=qty,
                order_type=OrderType.LIMIT,
                limit_price=target,
                tag="bracket.target",
                oco_group=oco,
            )
        )
        return stop_event, target_event

    def submit(self, request: OrderRequest) -> OrderEvent:
        context = self._require_context()
        event = context.submit(request)
        self.on_order_event(event)
        return event

    def position(self, instrument: str) -> Decimal:
        context = self._require_context()
        return context.position(instrument)

    def current_price(self, instrument: str) -> Decimal:
        return self._require_context().current_price(instrument)

    def stop_loss(
        self,
        side: OrderSide,
        level_band: tuple[Decimal, Decimal],
        buffer_atr: Decimal,
    ) -> StopProtection:
        """Initial SL beyond the level band (long: band_low - buffer; short: band_high + buffer)."""
        band_low, band_high = level_band
        if not isinstance(band_low, Decimal):
            band_low = Decimal(str(band_low))
        if not isinstance(band_high, Decimal):
            band_high = Decimal(str(band_high))
        if not isinstance(buffer_atr, Decimal):
            buffer_atr = Decimal(str(buffer_atr))
        if band_low >= band_high:
            raise ValueError("level band must satisfy band_low < band_high")
        if buffer_atr < 0:
            raise ValueError("buffer_atr must be >= 0")
        sl = band_low - buffer_atr if side is OrderSide.BUY else band_high + buffer_atr
        if band_low < sl < band_high:
            raise ValueError("stop inside level band")
        return StopProtection(sl=sl)

    def trail_stop(
        self,
        side: OrderSide,
        stop: StopProtection,
        *,
        atr: Decimal | None = None,
        extreme: Decimal | None = None,
        swing_level: Decimal | None = None,
    ) -> StopProtection:
        """Return the updated StopProtection after trailing (ATR or SWING)."""
        if stop.trail is TrailMode.OFF:
            return stop
        if stop.trail is TrailMode.ATR:
            if atr is None or extreme is None:
                raise ValueError("ATR trail requires atr and extreme")
            if not isinstance(atr, Decimal):
                atr = Decimal(str(atr))
            if not isinstance(extreme, Decimal):
                extreme = Decimal(str(extreme))
            distance = stop.trail_distance * atr
            if side is OrderSide.BUY:
                new_sl = max(stop.sl, extreme - distance)
            else:
                new_sl = min(stop.sl, extreme + distance)
        else:
            if swing_level is None:
                raise ValueError("SWING trail requires swing_level")
            if not isinstance(swing_level, Decimal):
                swing_level = Decimal(str(swing_level))
            if side is OrderSide.BUY:
                new_sl = max(stop.sl, swing_level)
            else:
                new_sl = min(stop.sl, swing_level)
        return StopProtection(
            sl=new_sl,
            trail=stop.trail,
            trail_distance=stop.trail_distance,
            activation_after_r=stop.activation_after_r,
        )

    def _emit_stop_update(
        self,
        instrument: str,
        side: OrderSide,
        new_stop: Decimal,
        old_stop: Decimal | None = None,
    ) -> None:
        """Build a StopUpdate and dispatch it to on_stop_update."""
        self.on_stop_update(
            StopUpdate(
                instrument=instrument,
                side=side,
                new_stop=new_stop,
                old_stop=old_stop,
            )
        )

    @property
    def indicators(self) -> IndicatorRegistry:
        return self._indicators

    @property
    def logger(self) -> logging.Logger:
        return self._logger

    # -- harness ------------------------------------------------------------
    # gap 0001 (tantra-strategies/docs/gaps/0001-*): tick dispatch entry point.
    # gap 0002 (tantra-strategies/docs/gaps/0002-*): live/feed-backed context seam.
    def run(self, context: StrategyContext, bars: list[Bar]) -> None:
        """Drive the strategy through a bar sequence (sim or live parity)."""
        drive = getattr(context, "run", None)
        if drive is not None:
            drive(self, bars)
        else:
            self._context = context
            self.on_start()
            for bar in bars:
                self.on_bar(bar)
            self.on_stop()

    def run_ticks(self, context: StrategyContext, ticks: list[Tick]) -> None:
        """Drive the strategy through a tick sequence (sim or live parity)."""
        drive = getattr(context, "run_ticks", None)
        if drive is not None:
            drive(self, ticks)
        else:
            self._context = context
            self.on_start()
            for tick in ticks:
                self.on_tick(tick)
            self.on_stop()

    def _require_context(self) -> StrategyContext:
        if self._context is None:
            raise RuntimeError("strategy has no execution context; call run(context, bars)")
        return self._context

    @staticmethod
    def _qty(value: Decimal | int | str) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))
