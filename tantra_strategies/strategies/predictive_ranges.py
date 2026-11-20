"""Predictive Ranges recipe strategies (root plan 0016: recipe.pr-trend-pullback,
recipe.pr-vidya-breakout).

Non-commercial research; ideas from LuxAlgo/Skyrexio/BigBeluga, clean-room.
Entries are market orders; the stop/target are resting OCO bracket orders
(``Strategy.bracket``) filled intrabar at their level (gap-through at the open;
the stop wins when both are hit on one bar). One position at a time.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from tantra_library.composites import PredictiveRanges, PredictiveRangesValue, VidyaTrend
from tantra_library.detectors import (
    PrCenterStep,
    PrTrendRegime,
    PrZoneCloseBreak,
    PrZoneTouch,
    ReversalBarSignal,
)
from tantra_library.indicators import ATR
from tantra_library.primitives import SwingPivot
from tantra_strategies.sdk import (
    Bar,
    HintSeverity,
    MarkerKind,
    MarkerSide,
    OuterBufferStopPolicy,
    OverlayScene,
    OverlaySceneEmitter,
    Parameter,
    SlMode,
    StopKind,
    Strategy,
)
from tantra_strategies.sdk.order import OrderEvent, OrderSide, OrderStatus

_ZERO = Decimal(0)
_MAX_SEGMENTS = 50  # retained PR band/level steps per kind
_MAX_POINTS = 2000  # retained points per indicator series
_MAX_EVENTS = 2000  # retained signal/stop/connector/hint records


def _dec(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(slots=True)
class _Trade:
    side: int  # +1 long, -1 short
    stop: Decimal
    target: Decimal
    entry_index: int = 0
    entry_price: Decimal = Decimal(0)
    stop_leg: str = ""


@dataclass(slots=True)
class _Pending:
    side: int
    trigger: Decimal
    stop: Decimal
    target: Decimal
    band: tuple[Decimal, Decimal]


class _SceneRecord:
    """Bounded history replayed into a fresh ``OverlaySceneEmitter`` on demand."""

    def __init__(self, strategy_id: str, symbol: str, timeframe: str = "1m") -> None:
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.timeframe = timeframe
        self.segments: dict[str, deque[list[Decimal | int]]] = {
            "s": deque(maxlen=_MAX_SEGMENTS),
            "r": deque(maxlen=_MAX_SEGMENTS),
            "c": deque(maxlen=_MAX_SEGMENTS),
        }
        self.points: dict[str, deque[tuple[int, Decimal]]] = {}
        self.events: deque[tuple[str, tuple[Any, ...], dict[str, Any]]] = deque(maxlen=_MAX_EVENTS)

    def segment(self, kind: str, low: Decimal, high: Decimal, index: int) -> None:
        segs = self.segments[kind]
        if segs and segs[-1][0] == low and segs[-1][1] == high and segs[-1][3] == index - 1:
            segs[-1][3] = index
        else:
            segs.append([low, high, index, index])

    def point(self, name: str, index: int, value: Decimal) -> None:
        self.points.setdefault(name, deque(maxlen=_MAX_POINTS)).append((index, value))

    def event(self, method: str, *args: Any, **kwargs: Any) -> None:
        self.events.append((method, args, kwargs))

    def build(self) -> OverlayScene:
        em = OverlaySceneEmitter(self.strategy_id, self.symbol, self.timeframe)
        for kind, key in (("s", "pr:s2-s1"), ("r", "pr:r1-r2")):
            for low, high, x0, x1 in self.segments[kind]:
                em.upsert_band(f"{key}@{x0}", low, high, x0, x1)  # type: ignore[arg-type]
        for low, _high, x0, x1 in self.segments["c"]:
            em.upsert_level(f"pr:center@{x0}", low, x0, x1)  # type: ignore[arg-type]
        for name, pts in self.points.items():
            for idx, value in pts:
                em.record_indicator_point(name, idx, value)
        for method, args, kwargs in self.events:
            getattr(em, method)(*args, **kwargs)
        return em.emit()


class _BracketStrategy(Strategy):
    """Shared single-position bracket (stop/target) management."""

    qty = Parameter(default=Decimal(1))
    allow_short = Parameter(default=True)
    stop_policy = Parameter(default="recipe")

    _scene_id: str = ""
    _entry_kind: MarkerKind = MarkerKind.BREAKOUT
    _record: _SceneRecord | None = None
    _bar_index: int = -1
    _trade: _Trade | None = None
    _leg_ids: frozenset[str] = frozenset()
    _exited: bool = False
    _exit_event: OrderEvent | None = None

    def _init_scene(self) -> None:
        policy = str(self.stop_policy)
        if policy != "recipe":
            try:
                SlMode(policy)
            except ValueError:
                raise ValueError(f"unknown stop_policy '{policy}'") from None
        self._record = _SceneRecord(self._scene_id, "")
        self._bar_index = -1
        self._exit_event = None

    def emit_scene(self) -> OverlayScene:
        record = self._record or _SceneRecord(self._scene_id, "")
        return record.build()

    def _tick(self, bar: Bar, pr: PredictiveRangesValue | None = None) -> None:
        """Advance the bar counter, finalize a pending exit and record PR bands."""
        record = self._record
        if record is None:
            self._init_scene()
            record = self._record
            assert record is not None
        self._bar_index += 1
        if not record.symbol:
            record.symbol = str(bar.instrument)
        if self._exit_event is not None:
            self._record_exit(self._exit_event)
            self._exit_event = None
        if pr is not None:
            idx = self._bar_index
            if pr.s2 is not None and pr.s1 is not None:
                record.segment("s", pr.s2, pr.s1, idx)
            if pr.r1 is not None and pr.r2 is not None:
                record.segment("r", pr.r1, pr.r2, idx)
            if pr.center is not None:
                record.segment("c", pr.center, pr.center, idx)

    def _point(self, name: str, value: Decimal | None) -> None:
        if value is not None and self._record is not None:
            self._record.point(name, self._bar_index, value)

    def _resolve_stop(
        self,
        bar: Bar,
        side: int,
        recipe_stop: Decimal,
        band: tuple[Decimal, Decimal],
        atr: Decimal,
        buffer_atr: Decimal,
    ) -> tuple[Decimal, Decimal | None] | None:
        """Return (stop, tight_stop), or None to skip the entry (ATR not ready, or the
        policy stop is not on the protective side of the entry)."""
        policy = str(self.stop_policy)
        if policy == "recipe":
            return recipe_stop, None
        if atr == _ZERO:
            return None
        plan = OuterBufferStopPolicy(
            sl_mode=SlMode(policy), buffer_atr=str(buffer_atr)
        ).compute_plan(
            entry=bar.close,
            side=OrderSide.BUY if side > 0 else OrderSide.SELL,
            level_band=band,
            atr=atr,
        )
        entry = bar.close
        if (side > 0 and plan.sl >= entry) or (side < 0 and plan.sl <= entry):
            return None
        return plan.sl, plan.tight_sl

    def _record_exit(self, event: OrderEvent) -> None:
        trade, record = self._last_trade, self._record
        if trade is None or record is None:
            return
        exit_price = event.price if event.price is not None else trade.entry_price
        stopped = event.order_id == trade.stop_leg
        risk = abs(trade.entry_price - trade.stop)
        r = trade.side * (exit_price - trade.entry_price) / risk if risk else _ZERO
        side = MarkerSide.BUY if trade.side > 0 else MarkerSide.SELL
        idx = self._bar_index
        record.event(
            "add_connector",
            trade.entry_index,
            trade.entry_price,
            idx,
            exit_price,
            side,
            r,
            stopped,
        )
        record.event(
            "add_signal",
            exit_price,
            idx,
            side,
            MarkerKind.STOP_LINE if stopped else MarkerKind.TARGET_HIT,
        )
        self._last_trade = None

    _last_trade: _Trade | None = None

    def _reset_trade(self) -> None:
        self._trade = None
        self._leg_ids = frozenset()
        self._exited = False

    def _enter(
        self,
        bar: Bar,
        side: int,
        stop: Decimal,
        target: Decimal,
        tight: Decimal | None = None,
        hint: tuple[str, str] = ("Entry", ""),
    ) -> None:
        """Market entry, then resting OCO stop/target legs filled intrabar."""
        quantity = _dec(self.qty)
        if side > 0:
            self.buy(bar.instrument, quantity)
            position_side = OrderSide.BUY
        else:
            self.sell(bar.instrument, quantity)
            position_side = OrderSide.SELL
        self._trade = _Trade(side, stop, target, self._bar_index, bar.close)
        stop_event, target_event = self.bracket(
            bar.instrument,
            position_side=position_side,
            quantity=quantity,
            stop=stop,
            target=target,
        )
        self._trade.stop_leg = stop_event.order_id
        self._leg_ids = frozenset({stop_event.order_id, target_event.order_id})
        self._record_entry(bar, side, stop, target, tight, hint)
        if OrderStatus.COMPLETE in (stop_event.status, target_event.status):
            done = stop_event if stop_event.status is OrderStatus.COMPLETE else target_event
            self._last_trade = self._trade
            self._record_exit(done)
            self._exited = False
            self._trade = None
            self._leg_ids = frozenset()

    def _record_entry(
        self,
        bar: Bar,
        side: int,
        stop: Decimal,
        target: Decimal,
        tight: Decimal | None,
        hint: tuple[str, str],
    ) -> None:
        record = self._record
        if record is None:
            return
        idx = self._bar_index
        mside = MarkerSide.BUY if side > 0 else MarkerSide.SELL
        record.event("add_signal", bar.close, idx, mside, self._entry_kind)
        previous = tight if tight is not None and tight != stop else None
        record.event("add_stop", stop, idx, idx, StopKind.INITIAL, previous=previous)
        record.event("add_stop", target, idx, idx, StopKind.TARGET)
        record.event("add_hint", idx, bar.close, HintSeverity.INFO, hint[0], hint[1])

    def on_order_event(self, event: OrderEvent) -> None:
        if event.status is OrderStatus.COMPLETE and event.order_id in self._leg_ids:
            self._exit_event = event
            self._last_trade = self._trade
            self._trade = None
            self._leg_ids = frozenset()
            self._exited = True

    def _manage_exit(self, _bar: Bar) -> bool:
        """True if a bracket leg filled intrabar since the previous bar (consumes the flag)."""
        exited, self._exited = self._exited, False
        return exited


class PrTrendPullbackStrategy(_BracketStrategy):
    """recipe.pr-trend-pullback: trade pullbacks to S1/R1 inside a PR trend regime."""

    length = Parameter(default=200, min=2, max=2000, step=1)
    factor = Parameter(default=Decimal(6))
    regime_steps = Parameter(default=2, min=1, max=20, step=1)
    lookback = Parameter(default=3, min=1, max=50, step=1)
    stop_buffer_atr = Parameter(default=Decimal("0.25"))
    require_alligator = Parameter(default=True)

    _scene_id = "recipe.pr-trend-pullback"
    _entry_kind = MarkerKind.RETEST

    def on_start(self) -> None:
        self._init_scene()
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
        self._tick(bar, pr)
        self._point("pr_center", pr.center)

        if self._manage_exit(bar):
            self._pending = None
            return
        pending, self._pending = self._pending, None
        if self._trade is not None:
            return
        if pending is not None and (
            (pending.side > 0 and bar.high > pending.trigger)
            or (pending.side < 0 and bar.low < pending.trigger)
        ):
            resolved = self._resolve_stop(
                bar, pending.side, pending.stop, pending.band, atr, _dec(self.stop_buffer_atr)
            )
            if resolved is not None:
                stop, tight = resolved
                title = "PR pullback long" if pending.side > 0 else "PR pullback short"
                detail = f"regime {regime}, zone touch, reversal trigger {pending.trigger}"
                self._enter(bar, pending.side, stop, pending.target, tight, (title, detail))
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
                self._pending = _Pending(
                    1, rev.bull_trigger, stop, pr.r1, (pr.s2, pr.s1 if pr.s1 is not None else pr.s2)
                )
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
                self._pending = _Pending(
                    -1,
                    rev.bear_trigger,
                    stop,
                    pr.s1,
                    (pr.r1 if pr.r1 is not None else pr.r2, pr.r2),
                )


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
    # ATR buffer for non-"recipe" stop policies (OuterBufferStopPolicy).
    stop_buffer_atr = Parameter(default=Decimal("0.25"))

    _scene_id = "recipe.pr-vidya-breakout"
    _entry_kind = MarkerKind.BREAKOUT

    def on_start(self) -> None:
        self._init_scene()
        factor = _dec(self.factor)
        self._pr = PredictiveRanges(self.length, factor)
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
        self._tick(bar, self._pr.update(bar))
        self._point("vidya", v.vidya)
        self._point("vidya_upper", v.upper)
        self._point("vidya_lower", v.lower)
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
                resolved = self._resolve_stop(
                    bar, 1, stop, (level - atr, level), atr, _dec(self.stop_buffer_atr)
                )
                if resolved is None or resolved[0] >= entry:
                    return
                target = entry + rr * (entry - resolved[0])
                hint = ("PR/VIDYA breakout long", f"VIDYA delta {delta}%, level {level}")
                self._enter(bar, 1, resolved[0], target, resolved[1], hint)
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
                resolved = self._resolve_stop(
                    bar, -1, stop, (level, level + atr), atr, _dec(self.stop_buffer_atr)
                )
                if resolved is None or resolved[0] <= entry:
                    return
                target = entry - rr * (resolved[0] - entry)
                hint = ("PR/VIDYA breakout short", f"VIDYA delta {delta}%, level {level}")
                self._enter(bar, -1, resolved[0], target, resolved[1], hint)
