"""Streaming technical indicators with exact ``Decimal`` arithmetic.

Indicators are fed one value (or one ``Bar`` for range-based indicators) at a
time, exactly as a live or backtest event loop delivers data. These are thin
stateful wrappers over the Decimal kernel in ``tantra_library``; the library
modules are imported lazily inside constructors to avoid an import cycle
(``tantra_library.primitives`` imports ``tantra_strategies.sdk.bar``).
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from tantra_strategies.sdk.bar import Bar

if TYPE_CHECKING:
    from tantra_library.indicators import BandsValue


class Indicator:
    """Base class for streaming indicators."""

    def __init__(self, period: int) -> None:
        if period <= 0:
            raise ValueError("period must be positive")
        self.period = period

    @property
    def ready(self) -> bool:
        raise NotImplementedError

    @property
    def value(self) -> Decimal:
        raise NotImplementedError


class SMA(Indicator):
    """Simple moving average over the trailing ``period`` values."""

    def __init__(self, period: int) -> None:
        super().__init__(period)
        from tantra_library.primitives import SMA as _SMA

        self._inner = _SMA(period)
        self._seen = 0
        self._warmup: list[Decimal] = []
        self._current: Decimal | None = None
        self._previous: Decimal | None = None

    def update(self, value: Decimal) -> None:
        self._seen += 1
        if self._seen <= self.period:
            self._warmup.append(value)
        self._previous = self._current
        self._current = self._inner.update(value)

    @property
    def ready(self) -> bool:
        return self._seen >= self.period

    @property
    def value(self) -> Decimal:
        if self._current is not None:
            return self._current
        return sum(self._warmup, Decimal(0)) / Decimal(len(self._warmup))

    @property
    def previous_value(self) -> Decimal | None:
        """SMA over the window one step ago (used for cross detection)."""
        if self._seen < self.period + 1:
            return None
        return self._previous


class EMA(Indicator):
    """Exponential moving average."""

    def __init__(self, period: int) -> None:
        super().__init__(period)
        from tantra_library.indicators import EMA as _EMA

        self._inner = _EMA(period)

    def update(self, value: Decimal) -> None:
        self._inner.update(value)

    @property
    def ready(self) -> bool:
        return self._inner.value is not None

    @property
    def value(self) -> Decimal:
        v = self._inner.value
        if v is None:
            raise ValueError("EMA is not ready")
        return v


class RSI(Indicator):
    """Wilder's Relative Strength Index."""

    def __init__(self, period: int = 14) -> None:
        super().__init__(period)
        from tantra_library.indicators import RSI as _RSI

        self._inner = _RSI(period)

    def update(self, value: Decimal) -> None:
        self._inner.update(value)

    @property
    def ready(self) -> bool:
        return self._inner.value is not None

    @property
    def value(self) -> Decimal:
        v = self._inner.value
        if v is None:
            raise ValueError("RSI is not ready")
        return v


class ATR(Indicator):
    """Wilder's Average True Range, fed one ``Bar`` at a time."""

    def __init__(self, period: int = 14) -> None:
        super().__init__(period)
        from tantra_library.indicators import ATR as _ATR

        self._inner = _ATR(period)

    def update(self, bar: Bar) -> None:
        self._inner.update(bar)

    @property
    def ready(self) -> bool:
        return self._inner.value is not None

    @property
    def value(self) -> Decimal:
        v = self._inner.value
        if v is None:
            raise ValueError("ATR is not ready")
        return v


class BollingerBands:
    """Bollinger Bands around a simple moving average."""

    def __init__(self, period: int = 20, deviations: Decimal | int = 2) -> None:
        if period <= 0:
            raise ValueError("period must be positive")
        from tantra_library.indicators import BollingerBands as _BB

        self.period = period
        self.deviations = (
            deviations if isinstance(deviations, Decimal) else Decimal(str(deviations))
        )
        if not self.deviations.is_finite() or self.deviations < 0:
            raise ValueError("deviations must be a finite, non-negative Decimal")
        self._inner = _BB(period, self.deviations)
        self._partial: list[Decimal] = []

    def update(self, value: Decimal) -> None:
        if len(self._partial) < self.period:
            self._partial.append(value)
        self._inner.update(value)

    @property
    def ready(self) -> bool:
        return self._inner.value is not None

    def _bands(self) -> BandsValue:
        v = self._inner.value
        if v is not None:
            return v
        if not self._partial:
            raise ValueError("BollingerBands has no values")
        # Not yet full: bands over the values seen so far (legacy behaviour).
        from tantra_library.indicators import BollingerBands as _BB

        partial = _BB(len(self._partial), self.deviations)
        out = None
        for x in self._partial:
            out = partial.update(x)
        assert out is not None
        return out

    @property
    def middle(self) -> Decimal:
        return self._bands().middle

    @property
    def upper(self) -> Decimal:
        return self._bands().upper

    @property
    def lower(self) -> Decimal:
        return self._bands().lower


def crosses_above(fast: Indicator, slow: Indicator) -> bool:
    """True when ``fast`` crossed above ``slow`` on the latest update."""
    return _cross(fast, slow, above=True)


def crosses_below(fast: Indicator, slow: Indicator) -> bool:
    """True when ``fast`` crossed below ``slow`` on the latest update."""
    return _cross(fast, slow, above=False)


def _cross(fast: Indicator, slow: Indicator, *, above: bool) -> bool:
    if not (fast.ready and slow.ready):
        return False
    fast_prev = getattr(fast, "previous_value", None)
    slow_prev = getattr(slow, "previous_value", None)
    if fast_prev is None or slow_prev is None:
        return False
    if above:
        return fast_prev <= slow_prev and fast.value > slow.value
    return fast_prev >= slow_prev and fast.value < slow.value
