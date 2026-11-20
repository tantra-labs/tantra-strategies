"""Elephant Edge v3 (EE+ Outer-Buffer) runnable catalog step (Track T21.2).

Bridges ``tantra.base.Strategy`` (the ``tantra-examples`` harness loader API) to
:class:`tantra_strategies.strategies.elephant_edge.ElephantEdgeStrategy`,
reusing the exact same composable :class:`ZoneExtractor`,
:class:`OuterBufferStopPolicy`, :class:`HedgeOverlayPolicy`, and
:class:`OverlaySceneEmitter` primitives while submitting real ``OrderIntent``s
to the wheel ``LedgerContext``.
"""

from __future__ import annotations

from typing import Any

from tantra.bar import Bar as WheelBar
from tantra.base import Parameter, Strategy

from tantra_strategies.sdk import OverlayScene, WheelSdkBridge
from tantra_strategies.strategies.elephant_edge import ElephantEdgeStrategy


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
            symbol = str(getattr(config, "symbol", "NSE:NIFTY50-INDEX"))
            exchange = str(getattr(config, "exchange", "NSE"))
        else:
            symbol, exchange = "NSE:NIFTY50-INDEX", "NSE"
        self._bridge = WheelSdkBridge(
            self._build_sdk,
            symbol=symbol,
            exchange=exchange,
            empty_scene_id="elephant_edge_v3",
        )

    def _build_sdk(self, instrument: str) -> ElephantEdgeStrategy:
        return ElephantEdgeStrategy(
            instrument=instrument,
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

    def on_start(self) -> None:
        self._bridge.start()

    def on_bar(self, bar: WheelBar, ctx: Any = None) -> None:
        del ctx
        self._bridge.on_wheel_bar(self, bar)

    def emit_scene(self) -> OverlayScene:
        return self._bridge.emit_scene()

    def on_stop(self) -> None:
        self._bridge.stop()
