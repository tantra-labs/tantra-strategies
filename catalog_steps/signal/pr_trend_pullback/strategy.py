"""Predictive Ranges Trend Pullback runnable catalog step (root plan 0016).

Bridges ``tantra.base.Strategy`` to
:class:`tantra_strategies.strategies.predictive_ranges.PrTrendPullbackStrategy` via
:class:`tantra_strategies.sdk.WheelSdkBridge`; SDK fills are replayed on the wheel ledger.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from tantra.bar import Bar as WheelBar
from tantra.base import Parameter, Strategy

from tantra_strategies.sdk import OverlayScene, WheelSdkBridge
from tantra_strategies.strategies.predictive_ranges import PrTrendPullbackStrategy


def _as_bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


class PrTrendPullback(Strategy):
    """Runnable wheel-API wrapper around :class:`PrTrendPullbackStrategy`."""

    name = "pr_trend_pullback"

    length = Parameter(default=200, min=2, max=2000, step=1)
    factor = Parameter(default="6")
    regime_steps = Parameter(default=2, min=1, max=20, step=1)
    lookback = Parameter(default=3, min=1, max=50, step=1)
    stop_buffer_atr = Parameter(default="0.25")
    require_alligator = Parameter(default=True)
    qty = Parameter(default="1")
    allow_short = Parameter(default=True)
    stop_policy = Parameter(default="recipe")

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
            empty_scene_id="recipe.pr-trend-pullback",
        )

    def _build_sdk(self, instrument: str) -> PrTrendPullbackStrategy:
        del instrument  # recipes read the instrument from each bar
        return PrTrendPullbackStrategy(
            length=int(self.length),
            factor=Decimal(str(self.factor)),
            regime_steps=int(self.regime_steps),
            lookback=int(self.lookback),
            stop_buffer_atr=Decimal(str(self.stop_buffer_atr)),
            require_alligator=_as_bool(self.require_alligator),
            qty=Decimal(str(self.qty)),
            allow_short=_as_bool(self.allow_short),
            stop_policy=str(self.stop_policy),
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
