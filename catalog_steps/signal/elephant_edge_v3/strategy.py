"""Elephant Edge v3 (EE+ Outer-Buffer) runnable catalog step (Track T21.2).

Bridges ``tantra.base.Strategy`` (the ``tantra-examples`` harness loader API) to
:class:`tantra_strategies.strategies.elephant_edge.ElephantEdgeStrategy`,
reusing the exact same composable :class:`ZoneExtractor`,
:class:`OuterBufferStopPolicy`, :class:`HedgeOverlayPolicy`, and
:class:`OverlaySceneEmitter` primitives while submitting real ``OrderIntent``s
to the wheel ``LedgerContext``.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from tantra.bar import Bar as WheelBar
from tantra.base import Parameter, Strategy
from tantra.instrument import InstrumentId

from tantra_strategies.sdk import (
    Bar as SdkBar,
)
from tantra_strategies.sdk import (
    OrderSide,
    OverlayScene,
    SimulatedContext,
)
from tantra_strategies.strategies.elephant_edge import ElephantEdgeStrategy


def _as_sdk_instrument(symbol: str, exchange: str) -> str:
    return symbol if ":" in symbol else f"{exchange}:{symbol}"


def _coerce_datetime(ts: object) -> dt.datetime:
    if isinstance(ts, dt.datetime):
        return ts
    return dt.datetime.fromisoformat(str(ts))


class ElephantEdgeV3(Strategy):
    """Runnable wheel-API wrapper around the generalized :class:`ElephantEdgeStrategy`."""

    name = "elephant_edge_v3"

    horizon_mode = Parameter(default="intraday")
    entry_trigger_mode = Parameter(default="all")
    sl_mode = Parameter(default="outer_atr_buffer")
    sl_buffer_atr = Parameter(default="0.25")
    hedge_mode = Parameter(default="auto")
    asset_class = Parameter(default="index")
    min_level_score = Parameter(default=0, min=0, max=4, step=1)
    capital = Parameter(default=1_000_000, min=1, max=10_000_000_000, step=1)
    lot_size = Parameter(default=1, min=1, max=100_000, step=1)

    def __init__(self, config: object | None = None) -> None:
        if config is not None:
            self._params = dict(getattr(config, "params", {}))
            self._config_symbol = str(getattr(config, "symbol", "NSE:NIFTY50-INDEX"))
            self._config_exchange = str(getattr(config, "exchange", "NSE"))
        else:
            self._config_symbol = "NSE:NIFTY50-INDEX"
            self._config_exchange = "NSE"

        self._sdk_instrument = _as_sdk_instrument(self._config_symbol, self._config_exchange)
        self._sdk_sim = SimulatedContext()
        self._sdk_strategy: ElephantEdgeStrategy | None = None
        self._forwarded_orders = 0

    def on_start(self) -> None:
        self._sdk_sim = SimulatedContext()
        self._forwarded_orders = 0
        self._sdk_strategy = ElephantEdgeStrategy(
            instrument=self._sdk_instrument,
            horizon_mode=str(self.horizon_mode),
            entry_trigger_mode=str(self.entry_trigger_mode),
            sl_mode=str(self.sl_mode),
            sl_buffer_atr=str(self.sl_buffer_atr),
            hedge_mode=str(self.hedge_mode),
            asset_class=str(self.asset_class),
            min_level_score=int(self.min_level_score),
            account_equity=str(self.capital),
            lot_size=str(self.lot_size),
        )
        self._sdk_strategy._context = self._sdk_sim
        self._sdk_strategy.on_start()

    def on_bar(self, bar: WheelBar, ctx: Any = None) -> None:
        del ctx
        if self._sdk_strategy is None:
            self.on_start()
        assert self._sdk_strategy is not None

        iid: InstrumentId = bar.instrument_id
        bar_instrument = f"{iid.exchange}:{iid.symbol}"
        if bar_instrument != self._sdk_instrument and iid.symbol != self._config_symbol:
            if not self._sdk_strategy._bars:
                self._sdk_instrument = bar_instrument
                self._sdk_strategy.instrument = bar_instrument
                self._sdk_strategy._instrument = bar_instrument
            else:
                return

        sdk_bar = SdkBar(
            instrument=self._sdk_instrument,
            ts=_coerce_datetime(bar.ts),
            open=Decimal(str(bar.open)),
            high=Decimal(str(bar.high)),
            low=Decimal(str(bar.low)),
            close=Decimal(str(bar.close)),
            volume=int(getattr(bar, "volume", 0)),
        )
        self._sdk_sim.feed(sdk_bar)
        for event in self._sdk_sim._drain_outbox():
            self._sdk_strategy.on_order_event(event)
        self._sdk_strategy.on_bar(sdk_bar)

        while self._forwarded_orders < len(self._sdk_sim.orders):
            req = self._sdk_sim.orders[self._forwarded_orders]
            self._forwarded_orders += 1
            if hasattr(self, "ctx") and not self.ctx.busy(iid):
                qty = req.quantity
                if req.side is OrderSide.BUY:
                    self.buy(iid, qty)
                else:
                    avail = self.position(iid)
                    sell_qty = min(qty, avail) if avail > 0 else qty
                    if sell_qty > 0:
                        self.sell(iid, sell_qty)

    def emit_scene(self) -> OverlayScene:
        if self._sdk_strategy is None:
            return OverlayScene(
                strategy_id="elephant_edge_v3",
                symbol=self._sdk_instrument,
                timeframe="1m",
            )
        return self._sdk_strategy.emit_scene()

    def on_stop(self) -> None:
        if self._sdk_strategy is not None:
            self._sdk_strategy.on_stop()
