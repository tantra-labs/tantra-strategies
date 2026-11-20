"""Streaming primitives: small stateful building blocks (all Decimal, no floats)."""

from __future__ import annotations

from collections import deque
from decimal import Decimal

from tantra_library.errors import InvalidParam
from tantra_strategies.sdk.bar import Bar

_ZERO = Decimal(0)
SOURCES = ("close", "open", "high", "low", "hl2", "hlc3", "ohlc4")


def _check_period(period: int, name: str = "period") -> None:
    if isinstance(period, bool) or not isinstance(period, int) or period < 1:
        raise InvalidParam(f"{name} must be an integer >= 1, got {period!r}")


def median_price(bar: Bar) -> Decimal:
    return (bar.high + bar.low) / 2


def typical_price(bar: Bar) -> Decimal:
    return (bar.high + bar.low + bar.close) / 3


def source_value(bar: Bar, source: str) -> Decimal:
    if source == "close":
        return bar.close
    if source == "open":
        return bar.open
    if source == "high":
        return bar.high
    if source == "low":
        return bar.low
    if source == "hl2":
        return median_price(bar)
    if source == "hlc3":
        return typical_price(bar)
    if source == "ohlc4":
        return (bar.open + bar.high + bar.low + bar.close) / 4
    raise InvalidParam(f"unknown source '{source}'; expected one of {list(SOURCES)}")


class TrueRange:
    def __init__(self) -> None:
        self._prev_close: Decimal | None = None
        self.value: Decimal | None = None

    def update(self, bar: Bar) -> Decimal:
        hl = bar.high - bar.low
        if self._prev_close is None:
            tr = hl
        else:
            tr = max(hl, abs(bar.high - self._prev_close), abs(bar.low - self._prev_close))
        self._prev_close = bar.close
        self.value = tr
        return tr

    def reset(self) -> None:
        self._prev_close = None
        self.value = None


class RMA:
    """Wilder smoothing: seed = SMA of first `period` inputs."""

    def __init__(self, period: int) -> None:
        _check_period(period)
        self.period = period
        self._count = 0
        self._sum = _ZERO
        self._value: Decimal | None = None

    @property
    def value(self) -> Decimal | None:
        return self._value

    def update(self, x: Decimal) -> Decimal | None:
        if self._value is None:
            self._count += 1
            self._sum += x
            if self._count == self.period:
                self._value = self._sum / self.period
        else:
            self._value = (self._value * (self.period - 1) + x) / self.period
        return self._value

    def reset(self) -> None:
        self._count = 0
        self._sum = _ZERO
        self._value = None


class SMA:
    def __init__(self, period: int) -> None:
        _check_period(period)
        self.period = period
        self._buf: deque[Decimal] = deque()
        self._sum = _ZERO

    @property
    def value(self) -> Decimal | None:
        if len(self._buf) < self.period:
            return None
        return self._sum / self.period

    def update(self, x: Decimal) -> Decimal | None:
        self._buf.append(x)
        self._sum += x
        if len(self._buf) > self.period:
            self._sum -= self._buf.popleft()
        return self.value

    def reset(self) -> None:
        self._buf.clear()
        self._sum = _ZERO


class _Extreme:
    _is_max = True

    def __init__(self, period: int) -> None:
        _check_period(period)
        self.period = period
        self._n = 0
        self._dq: deque[tuple[int, Decimal]] = deque()

    @property
    def value(self) -> Decimal | None:
        if self._n < self.period:
            return None
        return self._dq[0][1]

    def update(self, x: Decimal) -> Decimal | None:
        idx = self._n
        self._n += 1
        while self._dq and (self._dq[-1][1] <= x if self._is_max else self._dq[-1][1] >= x):
            self._dq.pop()
        self._dq.append((idx, x))
        if self._dq[0][0] <= idx - self.period:
            self._dq.popleft()
        return self.value

    def reset(self) -> None:
        self._n = 0
        self._dq.clear()


class Highest(_Extreme):
    _is_max = True


class Lowest(_Extreme):
    _is_max = False


class SwingPivot:
    """Pivot high/low confirmed `right` bars after the candidate bar."""

    def __init__(self, left: int, right: int) -> None:
        _check_period(left, "left")
        _check_period(right, "right")
        self.left = left
        self.right = right
        self._buf: deque[Bar] = deque(maxlen=left + right + 1)

    def update(self, bar: Bar) -> tuple[Decimal | None, Decimal | None]:
        self._buf.append(bar)
        if len(self._buf) < self._buf.maxlen:  # type: ignore[operator]
            return (None, None)
        bars = list(self._buf)
        cand = bars[self.left]
        others = bars[: self.left] + bars[self.left + 1 :]
        high = cand.high if all(cand.high > b.high for b in others) else None
        low = cand.low if all(cand.low < b.low for b in others) else None
        return (high, low)

    def reset(self) -> None:
        self._buf.clear()


class UpDownVolume:
    def update(self, bar: Bar) -> tuple[int, int]:
        if bar.close > bar.open:
            return (bar.volume, 0)
        if bar.close < bar.open:
            return (0, bar.volume)
        return (0, 0)

    def reset(self) -> None:
        return None


class LinReg:
    """Least-squares line over the last `period` values, x = 0..period-1."""

    def __init__(self, period: int) -> None:
        if isinstance(period, bool) or not isinstance(period, int) or period < 2:
            raise InvalidParam(f"period must be an integer >= 2, got {period!r}")
        self.period = period
        self._buf: deque[Decimal] = deque(maxlen=period)

    def update(self, value: Decimal) -> tuple[Decimal, Decimal] | None:
        self._buf.append(value)
        n = self.period
        if len(self._buf) < n:
            return None
        sx = Decimal(n * (n - 1) // 2)
        sxx = Decimal((n - 1) * n * (2 * n - 1) // 6)
        sy = sum(self._buf, _ZERO)
        sxy = sum((Decimal(i) * y for i, y in enumerate(self._buf)), _ZERO)
        slope = (n * sxy - sx * sy) / (n * sxx - sx * sx)
        fitted = (sy - slope * sx) / n + slope * (n - 1)
        return (slope, fitted)

    def reset(self) -> None:
        self._buf.clear()
