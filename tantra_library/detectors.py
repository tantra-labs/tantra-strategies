"""Event detectors built on composites (all Decimal, no floats)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal

from tantra_library.composites import (
    PredictiveRanges,
    ReversalBars,
    ReversalBarsValue,
    VidyaTrend,
)
from tantra_library.errors import InvalidParam
from tantra_library.primitives import _check_period
from tantra_strategies.sdk.bar import Bar


@dataclass(frozen=True, slots=True)
class CenterStepEvent:
    step_up: bool
    step_down: bool
    center: Decimal | None


@dataclass(frozen=True, slots=True)
class TrendRegimeEvent:
    regime: int


@dataclass(frozen=True, slots=True)
class ZoneTouchEvent:
    support_touch: bool
    resistance_touch: bool
    s1: Decimal | None
    r1: Decimal | None


@dataclass(frozen=True, slots=True)
class ZoneBreakEvent:
    break_up: bool
    break_down: bool
    level: Decimal | None


@dataclass(frozen=True, slots=True)
class TrendFlipEvent:
    flip_up: bool
    flip_down: bool
    delta_pct: Decimal | None


class PrCenterStep:
    def __init__(
        self, length: int = 200, factor: Decimal = Decimal(6), source: str = "close"
    ) -> None:
        self._pr = PredictiveRanges(length, factor, source)

    def update(self, bar: Bar) -> CenterStepEvent:
        v = self._pr.update(bar)
        return CenterStepEvent(v.center_step > 0, v.center_step < 0, v.center)

    def reset(self) -> None:
        self._pr.reset()


class PrTrendRegime:
    def __init__(
        self,
        length: int = 200,
        factor: Decimal = Decimal(6),
        source: str = "close",
        steps: int = 2,
    ) -> None:
        _check_period(steps, "steps")
        self._pr = PredictiveRanges(length, factor, source)
        self._steps = steps
        self._hist: deque[int] = deque(maxlen=steps)

    def update(self, bar: Bar) -> TrendRegimeEvent:
        step = self._pr.update(bar).center_step
        if step != 0:
            self._hist.append(step)
        regime = 0
        if len(self._hist) == self._steps:
            if all(s > 0 for s in self._hist):
                regime = 1
            elif all(s < 0 for s in self._hist):
                regime = -1
        return TrendRegimeEvent(regime)

    def reset(self) -> None:
        self._pr.reset()
        self._hist.clear()


class _PinnedLevels:
    """Predictive Ranges that remembers the previous bar's s1/r1."""

    def __init__(self, length: int, factor: Decimal, source: str) -> None:
        self._pr = PredictiveRanges(length, factor, source)
        self._s1: Decimal | None = None
        self._r1: Decimal | None = None

    def step(self, bar: Bar) -> tuple[Decimal | None, Decimal | None, int]:
        pinned = (self._s1, self._r1)
        v = self._pr.update(bar)
        self._s1, self._r1 = v.s1, v.r1
        return (pinned[0], pinned[1], v.center_step)

    def reset(self) -> None:
        self._pr.reset()
        self._s1 = None
        self._r1 = None


class PrZoneTouch:
    def __init__(
        self, length: int = 200, factor: Decimal = Decimal(6), source: str = "close"
    ) -> None:
        self._lv = _PinnedLevels(length, factor, source)

    def update(self, bar: Bar) -> ZoneTouchEvent:
        s1, r1, _ = self._lv.step(bar)
        return ZoneTouchEvent(
            s1 is not None and bar.low <= s1,
            r1 is not None and bar.high >= r1,
            s1,
            r1,
        )

    def reset(self) -> None:
        self._lv.reset()


class PrZoneCloseBreak:
    def __init__(
        self, length: int = 200, factor: Decimal = Decimal(6), source: str = "close"
    ) -> None:
        self._lv = _PinnedLevels(length, factor, source)

    def update(self, bar: Bar) -> ZoneBreakEvent:
        s1, r1, step = self._lv.step(bar)
        if step == 0:
            if r1 is not None and bar.close > r1:
                return ZoneBreakEvent(True, False, r1)
            if s1 is not None and bar.close < s1:
                return ZoneBreakEvent(False, True, s1)
        return ZoneBreakEvent(False, False, None)

    def reset(self) -> None:
        self._lv.reset()


class ReversalBarSignal:
    def __init__(
        self, lookback: int = 3, require_alligator: bool = True, ao_filter: bool = False
    ) -> None:
        self._rb = ReversalBars(lookback, require_alligator, ao_filter)

    def update(self, bar: Bar) -> ReversalBarsValue:
        return self._rb.update(bar)

    def reset(self) -> None:
        self._rb.reset()


class VidyaTrendFlip:
    def __init__(
        self,
        length: int = 10,
        momentum: int = 20,
        smoothing: int = 15,
        atr_length: int = 200,
        band_multiplier: Decimal = Decimal(2),
        normalization: str = "average",
    ) -> None:
        if normalization not in ("average", "total"):
            raise InvalidParam("normalization must be 'average' or 'total'")
        self._vt = VidyaTrend(
            length, momentum, smoothing, atr_length, band_multiplier, normalization
        )

    def update(self, bar: Bar) -> TrendFlipEvent:
        v = self._vt.update(bar)
        return TrendFlipEvent(v.flipped > 0, v.flipped < 0, v.delta_pct)

    def reset(self) -> None:
        self._vt.reset()
