"""Signal Study: forward-return statistics for detector events (pure, no I/O).

Track T22, root plan 0016. Non-commercial research tooling.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal

from tantra_library.errors import InvalidParam, LimitExceeded
from tantra_library.model import VolumeQuality
from tantra_library.registry import Registry
from tantra_strategies.sdk.bar import Bar

_Q8 = Decimal("0.00000001")
_Q4 = Decimal("0.0001")
_ZERO8 = Decimal(0).quantize(_Q8)
_ZERO4 = Decimal(0).quantize(_Q4)


@dataclass(frozen=True, slots=True)
class EventFilter:
    entry_id: str
    params: Mapping[str, object]
    column: str
    equals: bool | int | str


@dataclass(frozen=True, slots=True)
class HorizonStats:
    horizon: int
    count: int
    hit_rate: Decimal
    mean_return: Decimal
    median_return: Decimal


@dataclass(frozen=True, slots=True)
class StudyEvent:
    ts: datetime
    price: Decimal


@dataclass(frozen=True, slots=True)
class StudyResult:
    entry_id: str
    event_column: str
    direction: int
    bars: int
    event_count: int
    horizons: tuple[HorizonStats, ...]
    mfe_mean: Decimal | None
    mae_mean: Decimal | None
    by_year: dict[int, tuple[int, Decimal]]
    events: tuple[StudyEvent, ...]
    truncated: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "entry_id": self.entry_id,
            "event_column": self.event_column,
            "direction": self.direction,
            "bars": self.bars,
            "event_count": self.event_count,
            "horizons": [
                {
                    "horizon": h.horizon,
                    "count": h.count,
                    "hit_rate": str(h.hit_rate),
                    "mean_return": str(h.mean_return),
                    "median_return": str(h.median_return),
                }
                for h in self.horizons
            ],
            "mfe_mean": None if self.mfe_mean is None else str(self.mfe_mean),
            "mae_mean": None if self.mae_mean is None else str(self.mae_mean),
            "by_year": {
                str(y): {"count": c, "mean_return": str(m)} for y, (c, m) in self.by_year.items()
            },
            "events": [{"ts": e.ts.isoformat(), "price": str(e.price)} for e in self.events],
            "truncated": self.truncated,
        }


def _matches(value: object, expected: bool | int | str) -> bool:
    if value is None:
        return False
    if isinstance(expected, str):
        try:
            return Decimal(str(value)) == Decimal(expected)
        except ArithmeticError:
            return False
    if isinstance(value, bool) or isinstance(expected, bool):
        return bool(value) == bool(expected)
    return bool(value == expected)


def _is_event(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    return False


def _median(values: list[Decimal]) -> Decimal:
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def signal_study(
    registry: Registry,
    entry_id: str,
    params: Mapping[str, object],
    bars: Sequence[Bar],
    *,
    event_column: str,
    direction: int = 1,
    horizons: Sequence[int] = (1, 3, 5, 10, 20),
    event_filter: EventFilter | None = None,
    source_volume_quality: VolumeQuality = VolumeQuality.REAL,
    max_events_listed: int = 500,
    max_horizons: int = 10,
) -> StudyResult:
    if direction not in (1, -1):
        raise InvalidParam("direction must be 1 or -1")
    if not horizons:
        raise InvalidParam("horizons must not be empty")
    if len(horizons) > max_horizons:
        raise LimitExceeded(f"at most {max_horizons} horizons allowed")
    for h in horizons:
        if h <= 0:
            raise InvalidParam(f"horizon must be positive, got {h}")
        if h >= len(bars):
            raise InvalidParam(f"horizon {h} must be < number of bars ({len(bars)})")
    if max_events_listed < 0:
        raise InvalidParam("max_events_listed must be >= 0")

    frame = registry.evaluate(entry_id, params, bars, source_volume_quality=source_volume_quality)
    if event_column not in frame.columns:
        raise InvalidParam(f"unknown column '{event_column}' for '{entry_id}'")
    col = frame.columns[event_column]
    flt_col: list[object] | None = None
    if event_filter is not None:
        ff = registry.evaluate(
            event_filter.entry_id,
            event_filter.params,
            bars,
            source_volume_quality=source_volume_quality,
        )
        if event_filter.column not in ff.columns:
            raise InvalidParam(f"unknown filter column '{event_filter.column}'")
        flt_col = list(ff.columns[event_filter.column])

    idx = [
        i
        for i in range(len(bars))
        if _is_event(col[i])
        and (flt_col is None or event_filter is None or _matches(flt_col[i], event_filter.equals))
    ]
    d = Decimal(direction)
    hs = sorted(set(horizons))
    stats: list[HorizonStats] = []
    for h in hs:
        rets = [
            d * (bars[i + h].close - bars[i].close) / bars[i].close
            for i in idx
            if i + h < len(bars) and bars[i].close != 0
        ]
        if not rets:
            stats.append(HorizonStats(h, 0, _ZERO4, _ZERO8, _ZERO8))
            continue
        hits = sum(1 for r in rets if r > 0)
        stats.append(
            HorizonStats(
                h,
                len(rets),
                (Decimal(hits) / len(rets)).quantize(_Q4, ROUND_HALF_EVEN),
                (sum(rets, Decimal(0)) / len(rets)).quantize(_Q8, ROUND_HALF_EVEN),
                _median(rets).quantize(_Q8, ROUND_HALF_EVEN),
            )
        )

    hmax = hs[-1]
    mfes: list[Decimal] = []
    maes: list[Decimal] = []
    for i in idx:
        if i + hmax >= len(bars) or bars[i].close == 0:
            continue
        window = bars[i + 1 : i + hmax + 1]
        c = bars[i].close
        if direction == 1:
            fav = max(b.high for b in window) - c
            adv = c - min(b.low for b in window)
        else:
            fav = c - min(b.low for b in window)
            adv = max(b.high for b in window) - c
        mfes.append(max(fav, Decimal(0)) / c)
        maes.append(max(adv, Decimal(0)) / c)
    mfe = (sum(mfes, Decimal(0)) / len(mfes)).quantize(_Q8, ROUND_HALF_EVEN) if mfes else None
    mae = (sum(maes, Decimal(0)) / len(maes)).quantize(_Q8, ROUND_HALF_EVEN) if maes else None

    h0 = hs[0]
    years: dict[int, list[int]] = {}
    for i in idx:
        years.setdefault(frame.timestamps[i].year, []).append(i)
    by_year: dict[int, tuple[int, Decimal]] = {}
    for y in sorted(years):
        rs = [
            d * (bars[i + h0].close - bars[i].close) / bars[i].close
            for i in years[y]
            if i + h0 < len(bars) and bars[i].close != 0
        ]
        mean = (sum(rs, Decimal(0)) / len(rs)).quantize(_Q8, ROUND_HALF_EVEN) if rs else _ZERO8
        by_year[y] = (len(years[y]), mean)

    listed = tuple(StudyEvent(frame.timestamps[i], bars[i].close) for i in idx[:max_events_listed])
    return StudyResult(
        entry_id=entry_id,
        event_column=event_column,
        direction=direction,
        bars=len(bars),
        event_count=len(idx),
        horizons=tuple(stats),
        mfe_mean=mfe,
        mae_mean=mae,
        by_year=by_year,
        events=listed,
        truncated=len(idx) > max_events_listed,
    )
