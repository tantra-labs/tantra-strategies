"""Predictive Ranges recipe strategies (root plan 0016: recipe.pr-trend-pullback,
recipe.pr-vidya-breakout).

Non-commercial research; ideas from LuxAlgo/Skyrexio/BigBeluga, clean-room.
Stops/targets are evaluated on each bar's range (stop first when both are hit);
orders are market orders via ``buy``/``sell``. One position at a time.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from tantra_library.composites import PredictiveRanges, VidyaTrend
from tantra_library.detectors import (
    PrCenterStep,
    PrTrendRegime,
    PrZoneCloseBreak,
    PrZoneTouch,
    ReversalBarSignal,
)
from tantra_library.indicators import ATR
from tantra_library.primitives import SwingPivot
from tantra_strategies.sdk import Bar, Parameter, Strategy

_ZERO = Decimal(0)


def _dec(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(slots=True)
class _Trade:
    side: int  # +1 long, -1 short
    stop: Decimal
    target: Decimal


@dataclass(slots=True)
class _Pending:
    side: int
    trigger: Decimal
    stop: Decimal
    target: Decimal


class _BracketStrategy(Strategy):
    """Shared single-position bracket (stop/target) management."""

    qty = Parameter(default=Decimal(1))
    allow_short = Parameter(default=True)

    _trade: _Trade | None = None

    def _reset_trade(self) -> None:
        self._trade = None

    def _enter(self, bar: Bar, side: int, stop: Decimal, target: Decimal) -> None:
        quantity = _dec(self.qty)
        if side > 0:
            self.buy(bar.instrument, quantity)
        else:
            self.sell(bar.instrument, quantity)
        self._trade = _Trade(side, stop, target)

    def _manage_exit(self, bar: Bar) -> bool:
        """Close the open trade if stop or target was reached on this bar."""
        trade = self._trade
        if trade is None:
            return False
        if trade.side > 0:
            hit = bar.low <= trade.stop or bar.high >= trade.target
        else:
            hit = bar.high >= trade.stop or bar.low <= trade.target
        if not hit:
            return False
        held = self.position(bar.instrument)
        if held > 0:
            self.sell(bar.instrument, held)
        elif held < 0:
            self.buy(bar.instrument, -held)
        self._trade = None
        return True


class PrTrendPullbackStrategy(_BracketStrategy):
    """recipe.pr-trend-pullback: trade pullbacks to S1/R1 inside a PR trend regime."""

    length = Parameter(default=200, min=2, max=2000, step=1)
    factor = Parameter(default=Decimal(6))
    regime_steps = Parameter(default=2, min=1, max=20, step=1)
    lookback = Parameter(default=3, min=1, max=50, step=1)
    stop_buffer_atr = Parameter(default=Decimal("0.25"))
    require_alligator = Parameter(default=True)

    def on_start(self) -> None:
        factor = _dec(self.factor)
        self._regime = PrTrendRegime(self.length, factor, "close", self.regime_steps)
        self._touch = PrZoneTouch(self.length, factor)
        self._rev = ReversalBarSignal(self.lookback, bool(self.require_alligator))
        self._pr = PredictiveRanges(self.length, factor)
        self._atr = ATR(14)
        self._trade = None
        self._pending: _Pending | None = None

    def on_bar(self, bar: Bar) -> None:
        regime = self._regime.update(bar).regime
        touch = self._touch.update(bar)
        rev = self._rev.update(bar)
        pr = self._pr.update(bar)
        atr = self._atr.update(bar) or _ZERO
        buffer = _dec(self.stop_buffer_atr) * atr

        if self._manage_exit(bar):
            self._pending = None
            return
        pending, self._pending = self._pending, None
        if self._trade is not None:
            return
        if pending is not None:
            if pending.side > 0 and bar.high > pending.trigger:
                self._enter(bar, 1, pending.stop, pending.target)
                return
            if pending.side < 0 and bar.low < pending.trigger:
                self._enter(bar, -1, pending.stop, pending.target)
                return
        if (
            regime == 1
            and touch.support_touch
            and rev.bullish
            and rev.bull_trigger is not None
            and pr.s2 is not None
            and pr.r1 is not None
        ):
            stop = min(pr.s2, bar.low - buffer)
            if stop < rev.bull_trigger < pr.r1:
                self._pending = _Pending(1, rev.bull_trigger, stop, pr.r1)
        elif (
            self.allow_short
            and regime == -1
            and touch.resistance_touch
            and rev.bearish
            and rev.bear_trigger is not None
            and pr.r2 is not None
            and pr.s1 is not None
        ):
            stop = max(pr.r2, bar.high + buffer)
            if pr.s1 < rev.bear_trigger < stop:
                self._pending = _Pending(-1, rev.bear_trigger, stop, pr.s1)


class PrVidyaBreakoutStrategy(_BracketStrategy):
    """recipe.pr-vidya-breakout: PR zone break / center step aligned with VIDYA trend."""

    length = Parameter(default=200, min=2, max=2000, step=1)
    factor = Parameter(default=Decimal(6))
    vidya_length = Parameter(default=10, min=1, max=500, step=1)
    vidya_momentum = Parameter(default=20, min=1, max=500, step=1)
    vidya_smoothing = Parameter(default=15, min=1, max=500, step=1)
    vidya_atr_length = Parameter(default=200, min=1, max=2000, step=1)
    band_multiplier = Parameter(default=Decimal(2))
    delta_threshold = Parameter(default=Decimal(30))
    reward_risk = Parameter(default=Decimal("1.5"))
    pivot_left = Parameter(default=5, min=1, max=100, step=1)
    pivot_right = Parameter(default=5, min=1, max=100, step=1)

    def on_start(self) -> None:
        factor = _dec(self.factor)
        self._vidya = VidyaTrend(
            self.vidya_length,
            self.vidya_momentum,
            self.vidya_smoothing,
            self.vidya_atr_length,
            _dec(self.band_multiplier),
        )
        self._break = PrZoneCloseBreak(self.length, factor)
        self._step = PrCenterStep(self.length, factor)
        self._pivot = SwingPivot(self.pivot_left, self.pivot_right)
        self._atr = ATR(14)
        self._trade = None
        self._last_pivot_high: Decimal | None = None
        self._last_pivot_low: Decimal | None = None

    def on_bar(self, bar: Bar) -> None:
        v = self._vidya.update(bar)
        brk = self._break.update(bar)
        step = self._step.update(bar)
        atr = self._atr.update(bar) or _ZERO
        ph, pl = self._pivot.update(bar)
        if ph is not None:
            self._last_pivot_high = ph
        if pl is not None:
            self._last_pivot_low = pl

        if self._manage_exit(bar) or self._trade is not None:
            return
        delta = v.delta_pct
        if delta is None:
            return
        threshold = _dec(self.delta_threshold)
        rr = _dec(self.reward_risk)
        entry = bar.close
        if v.trend == 1 and delta >= threshold and (brk.break_up or step.step_up):
            level = brk.level if brk.break_up and brk.level is not None else step.center
            if level is None:
                return
            pivot = self._last_pivot_low
            stop = pivot if pivot is not None and pivot < entry else level - atr
            if stop < entry:
                self._enter(bar, 1, stop, entry + rr * (entry - stop))
        elif (
            self.allow_short
            and v.trend == -1
            and delta <= -threshold
            and (brk.break_down or step.step_down)
        ):
            level = brk.level if brk.break_down and brk.level is not None else step.center
            if level is None:
                return
            pivot = self._last_pivot_high
            stop = pivot if pivot is not None and pivot > entry else level + atr
            if stop > entry:
                self._enter(bar, -1, stop, entry - rr * (stop - entry))
