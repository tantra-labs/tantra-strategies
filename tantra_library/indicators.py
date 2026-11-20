"""Streaming indicators built from primitives (all Decimal, no floats)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal

from tantra_library.errors import InvalidParam
from tantra_library.primitives import (
    RMA,
    SMA,
    SOURCES,
    TrueRange,
    UpDownVolume,
    _check_period,
    median_price,
    source_value,
)
from tantra_strategies.sdk.bar import Bar

_ZERO = Decimal(0)
_HUNDRED = Decimal(100)


@dataclass(frozen=True, slots=True)
class BandsValue:
    upper: Decimal
    middle: Decimal
    lower: Decimal


@dataclass(frozen=True, slots=True)
class AlligatorValue:
    jaw: Decimal | None
    teeth: Decimal | None
    lips: Decimal | None


class ATR:
    def __init__(self, period: int) -> None:
        self._tr = TrueRange()
        self._rma = RMA(period)

    @property
    def value(self) -> Decimal | None:
        return self._rma.value

    def update(self, bar: Bar) -> Decimal | None:
        return self._rma.update(self._tr.update(bar))

    def reset(self) -> None:
        self._tr.reset()
        self._rma.reset()


class ATRBands:
    def __init__(self, period: int, multiplier: Decimal, source: str = "close") -> None:
        if not isinstance(multiplier, Decimal) or not multiplier.is_finite() or multiplier < 0:
            raise InvalidParam("multiplier must be a non-negative finite Decimal")
        if source not in SOURCES:
            raise InvalidParam(f"unknown source '{source}'")
        self._atr = ATR(period)
        self.multiplier = multiplier
        self.source = source
        self._value: BandsValue | None = None

    @property
    def value(self) -> BandsValue | None:
        return self._value

    def update(self, bar: Bar) -> BandsValue | None:
        atr = self._atr.update(bar)
        if atr is None:
            self._value = None
            return None
        mid = source_value(bar, self.source)
        off = atr * self.multiplier
        self._value = BandsValue(mid + off, mid, mid - off)
        return self._value

    def reset(self) -> None:
        self._atr.reset()
        self._value = None


class CMO:
    """Chande Momentum Oscillator over input changes."""

    def __init__(self, period: int) -> None:
        _check_period(period)
        self.period = period
        self._prev: Decimal | None = None
        self._changes: deque[tuple[Decimal, Decimal]] = deque()
        self._up = _ZERO
        self._down = _ZERO
        self._value: Decimal | None = None

    @property
    def value(self) -> Decimal | None:
        return self._value

    def update(self, x: Decimal) -> Decimal | None:
        if self._prev is not None:
            d = x - self._prev
            up, down = (d, _ZERO) if d > 0 else (_ZERO, -d)
            self._changes.append((up, down))
            self._up += up
            self._down += down
            if len(self._changes) > self.period:
                ou, od = self._changes.popleft()
                self._up -= ou
                self._down -= od
            if len(self._changes) == self.period:
                total = self._up + self._down
                self._value = _ZERO if total == 0 else _HUNDRED * (self._up - self._down) / total
        self._prev = x
        return self._value

    def reset(self) -> None:
        self._prev = None
        self._changes.clear()
        self._up = _ZERO
        self._down = _ZERO
        self._value = None


class VIDYA:
    def __init__(self, length: int, momentum: int, smoothing: int = 0) -> None:
        _check_period(length, "length")
        _check_period(momentum, "momentum")
        if smoothing < 0:
            raise InvalidParam("smoothing must be >= 0")
        self._alpha = Decimal(2) / (length + 1)
        self._cmo = CMO(momentum)
        self._smooth = SMA(smoothing) if smoothing > 1 else None
        self._smoothing = smoothing
        self._seed: Decimal | None = None
        self._prev: Decimal | None = None
        self._value: Decimal | None = None

    @property
    def value(self) -> Decimal | None:
        return self._value

    def update(self, x: Decimal) -> Decimal | None:
        if self._seed is None:
            self._seed = x
            self._prev = x
        cmo = self._cmo.update(x)
        if cmo is None:
            return None
        k = self._alpha * abs(cmo) / _HUNDRED
        assert self._prev is not None
        vid = k * x + (1 - k) * self._prev
        self._prev = vid
        self._value = vid if self._smooth is None else self._smooth.update(vid)
        return self._value

    def reset(self) -> None:
        self._cmo.reset()
        if self._smooth is not None:
            self._smooth.reset()
        self._seed = None
        self._prev = None
        self._value = None


class VolumeDeltaPct:
    def __init__(self, window: int, normalization: str = "average") -> None:
        _check_period(window, "window")
        if normalization not in ("average", "total"):
            raise InvalidParam("normalization must be 'average' or 'total'")
        self.window = window
        self.normalization = normalization
        self._udv = UpDownVolume()
        self._buf: deque[tuple[int, int]] = deque()
        self._u = 0
        self._d = 0
        self._value: Decimal | None = None

    @property
    def value(self) -> Decimal | None:
        return self._value

    def update(self, bar: Bar) -> Decimal | None:
        u, d = self._udv.update(bar)
        self._buf.append((u, d))
        self._u += u
        self._d += d
        if len(self._buf) > self.window:
            ou, od = self._buf.popleft()
            self._u -= ou
            self._d -= od
        if len(self._buf) < self.window:
            return None
        total = self._u + self._d
        if total == 0:
            self._value = _ZERO
        else:
            denom = Decimal(total) if self.normalization == "total" else Decimal(total) / 2
            self._value = _HUNDRED * (self._u - self._d) / denom
        return self._value

    def reset(self) -> None:
        self._buf.clear()
        self._u = 0
        self._d = 0
        self._value = None


class Alligator:
    def __init__(
        self,
        jaw: int = 13,
        teeth: int = 8,
        lips: int = 5,
        jaw_shift: int = 8,
        teeth_shift: int = 5,
        lips_shift: int = 3,
    ) -> None:
        for s in (jaw_shift, teeth_shift, lips_shift):
            if s < 0:
                raise InvalidParam("shifts must be >= 0")
        self._lines: list[tuple[RMA, int, list[Decimal | None]]] = [
            (RMA(jaw), jaw_shift, []),
            (RMA(teeth), teeth_shift, []),
            (RMA(lips), lips_shift, []),
        ]
        self._hist: list[list[Decimal | None]] = [line[2] for line in self._lines]
        self._value: AlligatorValue | None = None

    @property
    def value(self) -> AlligatorValue | None:
        return self._value

    def update(self, bar: Bar) -> AlligatorValue:
        m = median_price(bar)
        outs: list[Decimal | None] = []
        for rma, shift, hist in self._lines:
            hist.append(rma.update(m))
            idx = len(hist) - 1 - shift
            outs.append(hist[idx] if idx >= 0 else None)
        self._value = AlligatorValue(outs[0], outs[1], outs[2])
        return self._value

    def reset(self) -> None:
        for rma, _, hist in self._lines:
            rma.reset()
            hist.clear()
        self._value = None


class AwesomeOscillator:
    def __init__(self, fast: int = 5, slow: int = 34) -> None:
        if fast >= slow:
            raise InvalidParam("fast must be < slow")
        self._fast = SMA(fast)
        self._slow = SMA(slow)
        self._value: Decimal | None = None

    @property
    def value(self) -> Decimal | None:
        return self._value

    def update(self, bar: Bar) -> Decimal | None:
        m = median_price(bar)
        f = self._fast.update(m)
        s = self._slow.update(m)
        self._value = None if f is None or s is None else f - s
        return self._value

    def reset(self) -> None:
        self._fast.reset()
        self._slow.reset()
        self._value = None
