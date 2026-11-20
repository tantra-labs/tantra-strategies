"""Predictive Ranges VIDYA Breakout runnable catalog step (root plan 0016).

Bridges ``tantra.base.Strategy`` to
:class:`tantra_strategies.strategies.predictive_ranges.PrVidyaBreakoutStrategy` via
:class:`tantra_strategies.sdk.WheelSdkBridge`; SDK fills are replayed on the wheel ledger.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from tantra.bar import Bar as WheelBar
from tantra.base import Parameter, Strategy

from tantra_strategies.sdk import OverlayScene, WheelSdkBridge
from tantra_strategies.strategies.predictive_ranges import PrVidyaBreakoutStrategy


def _as_bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


class PrVidyaBreakout(Strategy):
    """Runnable wheel-API wrapper around :class:`PrVidyaBreakoutStrategy`."""

    name = "pr_vidya_breakout"

    length = Parameter(default=200, min=2, max=2000, step=1)
    factor = Parameter(default="6")
    vidya_length = Parameter(default=10, min=1, max=500, step=1)
    vidya_momentum = Parameter(default=20, min=1, max=500, step=1)
    vidya_smoothing = Parameter(default=15, min=1, max=500, step=1)
    vidya_atr_length = Parameter(default=200, min=1, max=2000, step=1)
    band_multiplier = Parameter(default="2")
    delta_threshold = Parameter(default="30")
    reward_risk = Parameter(default="1.5")
    pivot_left = Parameter(default=5, min=1, max=100, step=1)
    pivot_right = Parameter(default=5, min=1, max=100, step=1)
    stop_buffer_atr = Parameter(default="0.25")
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
            empty_scene_id="recipe.pr-vidya-breakout",
        )

    def _build_sdk(self, instrument: str) -> PrVidyaBreakoutStrategy:
        del instrument  # recipes read the instrument from each bar
        return PrVidyaBreakoutStrategy(
            length=int(self.length),
            factor=Decimal(str(self.factor)),
            vidya_length=int(self.vidya_length),
            vidya_momentum=int(self.vidya_momentum),
            vidya_smoothing=int(self.vidya_smoothing),
            vidya_atr_length=int(self.vidya_atr_length),
            band_multiplier=Decimal(str(self.band_multiplier)),
            delta_threshold=Decimal(str(self.delta_threshold)),
            reward_risk=Decimal(str(self.reward_risk)),
            pivot_left=int(self.pivot_left),
            pivot_right=int(self.pivot_right),
            stop_buffer_atr=Decimal(str(self.stop_buffer_atr)),
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
