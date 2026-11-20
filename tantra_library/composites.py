"""Composites: clean-room multi-indicator constructs (all Decimal, no floats)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise

from tantra_library.errors import InvalidParam
from tantra_library.indicators import ATR, VIDYA, Alligator, AwesomeOscillator
from tantra_library.primitives import SOURCES, UpDownVolume, _check_period, source_value
from tantra_strategies.sdk.bar import Bar

_ZERO = Decimal(0)
_HUNDRED = Decimal(100)


def _check_decimal(value: Decimal, name: str, *, positive: bool) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvalidParam(f"{name} must be a finite Decimal")
    if (positive and value <= 0) or (not positive and value < 0):
        raise InvalidParam(f"{name} must be {'> 0' if positive else '>= 0'}, got {value}")


@dataclass(frozen=True, slots=True)
class PredictiveRangesValue:
    r2: Decimal | None
    r1: Decimal | None
    center: Decimal | None
    s1: Decimal | None
    s2: Decimal | None
    center_step: int


class PredictiveRanges:
    """ATR-stepped center line with frozen half-ATR bands (at most one step per bar)."""

    def __init__(
        self, length: int = 200, factor: Decimal = Decimal(6), source: str = "close"
    ) -> None:
        _check_period(length, "length")
        _check_decimal(factor, "factor", positive=True)
        if source not in SOURCES:
            raise InvalidParam(f"unknown source '{source}'")
        self.source = source
        self.factor = factor
        self._atr = ATR(length)
        self._center: Decimal | None = None
        self._hold: Decimal | None = None

    def update(self, bar: Bar) -> PredictiveRangesValue:
        raw = self._atr.update(bar)
        atr = _ZERO if raw is None else raw * self.factor
        src = source_value(bar, self.source)
        if self._center is None:
            self._center = src
        step = 0
        if atr > 0:
            if src - self._center > atr:
                self._center += atr
                step = 1
            elif self._center - src > atr:
                self._center -= atr
                step = -1
        if step != 0:
            self._hold = atr / 2
        center = self._center
        if raw is None:
            return PredictiveRangesValue(None, None, None, None, None, step)
        hold = self._hold
        if hold is None:
            return PredictiveRangesValue(None, None, center, None, None, step)
        return PredictiveRangesValue(
            center + 2 * hold, center + hold, center, center - hold, center - 2 * hold, step
        )

    def reset(self) -> None:
        self._atr.reset()
        self._center = None
        self._hold = None


@dataclass(frozen=True, slots=True)
class VidyaTrendValue:
    vidya: Decimal | None
    upper: Decimal | None
    lower: Decimal | None
    trend_line: Decimal | None
    trend: int
    flipped: int
    up_volume: int
    down_volume: int
    delta_pct: Decimal | None


class VidyaTrend:
    """VIDYA with ATR bands, trend flips on band cross and volume delta since the flip."""

    def __init__(
        self,
        length: int = 10,
        momentum: int = 20,
        smoothing: int = 15,
        atr_length: int = 200,
        band_multiplier: Decimal = Decimal(2),
        normalization: str = "average",
    ) -> None:
        _check_decimal(band_multiplier, "band_multiplier", positive=False)
        if normalization not in ("average", "total"):
            raise InvalidParam("normalization must be 'average' or 'total'")
        _check_period(atr_length, "atr_length")
        self._vidya = VIDYA(length, momentum, smoothing)
        self._atr = ATR(atr_length)
        self._mult = band_multiplier
        self._norm = normalization
        self._udv = UpDownVolume()
        self._init_state()

    def _init_state(self) -> None:
        self._prev_close: Decimal | None = None
        self._prev_upper: Decimal | None = None
        self._prev_lower: Decimal | None = None
        self._trend = 0
        self._up = 0
        self._down = 0

    def update(self, bar: Bar) -> VidyaTrendValue:
        vid = self._vidya.update(bar.close)
        atr = self._atr.update(bar)
        upper = lower = None
        if vid is not None and atr is not None:
            upper = vid + atr * self._mult
            lower = vid - atr * self._mult
        u, d = self._udv.update(bar)
        flipped = 0
        if (
            upper is not None
            and lower is not None
            and self._prev_close is not None
            and self._prev_upper is not None
            and self._prev_lower is not None
        ):
            if bar.close > upper and self._prev_close <= self._prev_upper:
                flipped = 1 if self._trend != 1 else 0
                self._trend = 1
            elif bar.close < lower and self._prev_close >= self._prev_lower:
                flipped = -1 if self._trend != -1 else 0
                self._trend = -1
        if flipped != 0:
            self._up, self._down = u, d
        else:
            self._up += u
            self._down += d
        self._prev_close = bar.close
        self._prev_upper = upper
        self._prev_lower = lower
        trend_line: Decimal | None = None
        delta: Decimal | None = None
        if self._trend != 0:
            trend_line = lower if self._trend == 1 else upper
            total = self._up + self._down
            if total == 0:
                delta = _ZERO
            else:
                denom = Decimal(total) if self._norm == "total" else Decimal(total) / 2
                delta = _HUNDRED * (self._up - self._down) / denom
        return VidyaTrendValue(
            vid, upper, lower, trend_line, self._trend, flipped, self._up, self._down, delta
        )

    def reset(self) -> None:
        self._vidya.reset()
        self._atr.reset()
        self._init_state()


@dataclass(frozen=True, slots=True)
class ReversalBarsValue:
    bullish: bool
    bearish: bool
    bull_trigger: Decimal | None
    bear_trigger: Decimal | None


class ReversalBars:
    """Bill-Williams-style reversal bars after a run of lower highs / higher lows."""

    def __init__(
        self, lookback: int = 3, require_alligator: bool = True, ao_filter: bool = False
    ) -> None:
        _check_period(lookback, "lookback")
        self.lookback = lookback
        self.require_alligator = require_alligator
        self.ao_filter = ao_filter
        self._alligator = Alligator()
        self._ao = AwesomeOscillator()
        self._prev: deque[Bar] = deque(maxlen=lookback)
        self._prev_ao: Decimal | None = None

    def update(self, bar: Bar) -> ReversalBarsValue:
        lines = self._alligator.update(bar)
        ao = self._ao.update(bar)
        prev = list(self._prev)
        prev_ao = self._prev_ao
        self._prev.append(bar)
        self._prev_ao = ao
        if len(prev) < self.lookback:
            return ReversalBarsValue(False, False, None, None)
        mid = (bar.high + bar.low) / 2
        highs = [b.high for b in prev]
        lows = [b.low for b in prev]
        desc = all(a > b for a, b in pairwise(highs))
        asc = all(a < b for a, b in pairwise(lows))
        lv = (lines.jaw, lines.teeth, lines.lips)
        defined = [x for x in lv if x is not None]
        lines_ok = len(defined) == 3
        ao_ok = ao is not None and prev_ao is not None
        bull = bar.close > mid and bar.low < min(lows) and desc
        bear = bar.close < mid and bar.high > max(highs) and asc
        if self.require_alligator:
            bull = bull and lines_ok and bar.high > min(defined)
            bear = bear and lines_ok and bar.low < max(defined)
        if self.ao_filter:
            bull = bull and ao_ok and ao < prev_ao  # type: ignore[operator]
            bear = bear and ao_ok and ao > prev_ao  # type: ignore[operator]
        return ReversalBarsValue(bull, bear, bar.high if bull else None, bar.low if bear else None)

    def reset(self) -> None:
        self._alligator.reset()
        self._ao.reset()
        self._prev.clear()
        self._prev_ao = None
