"""Session zones: Elephant Zones, Opening Range and their sweep/breakout detectors.

Thin streaming wrappers over the T21.2 sdk primitives in
``tantra_strategies.sdk.primitives`` (pure ``Decimal``, no I/O, no clock).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal

from tantra_library.indicators import ATR
from tantra_strategies.sdk.bar import Bar
from tantra_strategies.sdk.levels import LevelMap
from tantra_strategies.sdk.order import OrderSide
from tantra_strategies.sdk.primitives import (
    AssetClass,
    ElephantZonesExtractor,
    HorizonMode,
    Orb15ZoneExtractor,
    OuterBufferStopPolicy,
    SessionClock,
    SlMode,
    ZoneExtractionContext,
)


class SessionTracker:
    """Rolls sessions by ``SessionClock.session_key``; completed sessions are bounded."""

    def __init__(
        self,
        horizon: HorizonMode | str = HorizonMode.INTRADAY,
        asset_class: AssetClass | str = AssetClass.INDEX,
        max_sessions: int = 20,
    ) -> None:
        if max_sessions < 1:
            raise ValueError("max_sessions must be >= 1")
        self.horizon = HorizonMode(horizon)
        self.asset_class = AssetClass(asset_class)
        self.max_sessions = max_sessions
        self.completed: deque[tuple[object, tuple[Bar, ...]]] = deque(maxlen=max_sessions)
        self._key: str | None = None
        self._bars: list[Bar] = []
        self._index = -1

    @property
    def key(self) -> str | None:
        return self._key

    @property
    def bars(self) -> tuple[Bar, ...]:
        return tuple(self._bars)

    @property
    def session_length(self) -> int:
        return len(self._bars)

    @property
    def bar_index(self) -> int:
        return self._index

    def update(self, bar: Bar) -> None:
        key = SessionClock.session_key(bar.ts, self.horizon, self.asset_class)
        if self._key is not None and key != self._key:
            self.completed.append((self._key, tuple(self._bars)))
            self._bars = []
        self._key = key
        self._bars.append(bar)
        self._index += 1

    def context(self, bar: Bar, atr: Decimal | None) -> ZoneExtractionContext:
        return ZoneExtractionContext(
            instrument=bar.instrument,
            bar=bar,
            bar_index=self._index,
            session_open=self._bars[0].open,
            session_bars=tuple(self._bars),
            completed_sessions=tuple(self.completed),
            atr=atr,
        )

    def reset(self) -> None:
        self.completed.clear()
        self._key = None
        self._bars = []
        self._index = -1


@dataclass(frozen=True, slots=True)
class ElephantZonesValue:
    s2: Decimal
    s1: Decimal
    r1: Decimal
    r2: Decimal
    half_width: Decimal
    long_outer_sl: Decimal | None
    short_outer_sl: Decimal | None


def _price(level_map: LevelMap, level_id: str) -> Decimal:
    for lvl in level_map.levels:
        if lvl.level_id == level_id:
            return lvl.price
    raise KeyError(level_id)


class ElephantZones:
    def __init__(
        self,
        horizon: str = "intraday",
        asset_class: str = "index",
        atr_period: int = 14,
        sl_mode: str = "outer_atr_buffer",
        sl_buffer_atr: Decimal = Decimal("0.25"),
        max_sessions: int = 20,
    ) -> None:
        self._tracker = SessionTracker(horizon, asset_class, max_sessions)
        self._atr = ATR(atr_period)
        self._extractor = ElephantZonesExtractor()
        self._policy = OuterBufferStopPolicy(sl_mode=SlMode(sl_mode), buffer_atr=sl_buffer_atr)

    @property
    def tracker(self) -> SessionTracker:
        return self._tracker

    def update(self, bar: Bar) -> ElephantZonesValue:
        atr = self._atr.update(bar)
        self._tracker.update(bar)
        lm = self._extractor.extract(self._tracker.context(bar, atr))
        s1, s2 = _price(lm, "ee:s1"), _price(lm, "ee:s2")
        r1, r2 = _price(lm, "ee:r1"), _price(lm, "ee:r2")
        half = next(lv.band_half_width for lv in lm.levels if lv.level_id == "ee:s1")
        long_sl: Decimal | None = None
        short_sl: Decimal | None = None
        if atr is not None:
            long_sl = self._policy.compute_plan(
                entry=s1, side=OrderSide.BUY, level_band=(s1 - half, s1 + half), atr=atr
            ).sl
            short_sl = self._policy.compute_plan(
                entry=r1, side=OrderSide.SELL, level_band=(r1 - half, r1 + half), atr=atr
            ).sl
        return ElephantZonesValue(s2, s1, r1, r2, half, long_sl, short_sl)

    def reset(self) -> None:
        self._tracker.reset()
        self._atr.reset()


@dataclass(frozen=True, slots=True)
class OpeningRangeValue:
    or_high: Decimal | None
    or_low: Decimal | None
    or_mid: Decimal | None
    session: str | None


class OpeningRange:
    def __init__(
        self,
        opening_bars: int = 3,
        atr_band_mult: Decimal = Decimal("0.25"),
        horizon: str = "intraday",
        asset_class: str = "index",
        atr_period: int = 14,
    ) -> None:
        self.opening_bars = opening_bars
        self._tracker = SessionTracker(horizon, asset_class, 1)
        self._atr = ATR(atr_period)
        self._extractor = Orb15ZoneExtractor(opening_bars=opening_bars, atr_band_mult=atr_band_mult)

    def update(self, bar: Bar) -> OpeningRangeValue:
        atr = self._atr.update(bar)
        self._tracker.update(bar)
        key = self._tracker.key
        if self._tracker.session_length < self.opening_bars:
            return OpeningRangeValue(None, None, None, key)  # window incomplete: no lookahead
        lm = self._extractor.extract(self._tracker.context(bar, atr))
        return OpeningRangeValue(
            _price(lm, "orb:high"), _price(lm, "orb:low"), _price(lm, "orb:mid"), key
        )

    def reset(self) -> None:
        self._tracker.reset()
        self._atr.reset()


@dataclass(frozen=True, slots=True)
class EeSweepValue:
    bull_sweep: bool
    bear_sweep: bool
    level: Decimal | None


class EeSweep:
    """Wick through the S1/R1 band that closes back inside (liquidity sweep)."""

    def __init__(self, zones: ElephantZones) -> None:
        self._zones = zones

    def update(self, bar: Bar) -> EeSweepValue:
        z = self._zones.update(bar)
        bull = bar.low < z.s1 - z.half_width and bar.close > z.s1 - z.half_width
        bear = bar.high > z.r1 + z.half_width and bar.close < z.r1 + z.half_width
        level = z.s1 if bull else (z.r1 if bear else None)
        return EeSweepValue(bull, bear, level)

    def reset(self) -> None:
        self._zones.reset()


@dataclass(frozen=True, slots=True)
class Orb15BreakoutValue:
    break_up: bool
    break_down: bool
    level: Decimal | None


class Orb15Breakout:
    """First close beyond the opening range per session; each side fires at most once."""

    def __init__(self, opening_range: OpeningRange) -> None:
        self._or = opening_range
        self._session: str | None = None
        self._up_done = False
        self._down_done = False

    def update(self, bar: Bar) -> Orb15BreakoutValue:
        v = self._or.update(bar)
        if v.session != self._session:
            self._session = v.session
            self._up_done = self._down_done = False
        if v.or_high is None or v.or_low is None:
            return Orb15BreakoutValue(False, False, None)
        up = not self._up_done and bar.close > v.or_high
        down = not self._down_done and bar.close < v.or_low
        self._up_done = self._up_done or up
        self._down_done = self._down_done or down
        return Orb15BreakoutValue(up, down, v.or_high if up else (v.or_low if down else None))

    def reset(self) -> None:
        self._or.reset()
        self._session = None
        self._up_done = self._down_done = False
