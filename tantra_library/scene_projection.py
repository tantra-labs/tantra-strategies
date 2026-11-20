"""Generic projection of a computed ``Frame`` / ``StudyResult`` onto an ``OverlayScene``.

Pure, Decimal-only, no I/O: any library entry can be plotted without per-indicator UI code.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from tantra_library.model import Entry, Frame, OutputUnit, Value
from tantra_library.study import StudyResult
from tantra_strategies.sdk.bar import Bar
from tantra_strategies.sdk.scene import (
    HintMetricSpec,
    HintSeverity,
    MarkerKind,
    MarkerSide,
    OverlayScene,
    OverlaySceneEmitter,
)

MAX_POINTS = 5000
MAX_BAND_SEGMENTS = 200
MAX_HINT_EVENTS = 50
MAX_EVENT_MARKERS = 2000  # per EVENT output (latest kept)
MAX_STUDY_MARKERS = 500

_FIXED_BAND_PAIRS = (("s2", "s1"), ("r1", "r2"), ("lower", "upper"))
_SELL_WORDS = ("down", "bear", "short", "resist")
_HALF = Decimal("0.5")


def _num(v: Value) -> Decimal | None:
    if v is None:
        return None
    return Decimal(int(v)) if isinstance(v, bool) else Decimal(v)


def _band_pairs(price_names: Sequence[str]) -> list[tuple[str, str]]:
    have = set(price_names)
    pairs = [(a, b) for a, b in _FIXED_BAND_PAIRS if a in have and b in have]
    for n in price_names:
        if n.endswith("_lower") and n != "_lower":
            up = n[: -len("_lower")] + "_upper"
            if up in have and (n, up) not in pairs:
                pairs.append((n, up))
    return pairs


def _side(name: str) -> MarkerSide:
    low = name.lower()
    return MarkerSide.SELL if any(w in low for w in _SELL_WORDS) else MarkerSide.BUY


def _kind(name: str) -> MarkerKind:
    low = name.lower()
    if "sweep" in low:
        return MarkerKind.SWEEP
    if "rev" in low:
        return MarkerKind.REVERSAL
    if "touch" in low or "retest" in low:
        return MarkerKind.RETEST
    return MarkerKind.BREAKOUT


def frame_to_scene(
    entry: Entry,
    frame: Frame,
    bars: Sequence[Bar],
    *,
    symbol: str,
    timeframe: str,
    tail: int | None = None,
) -> OverlayScene:
    """Project ``frame`` onto the 6-layer scene (see module rules in the plan)."""
    n = len(frame.timestamps)
    window = n if tail is None else min(n, max(tail, 0))
    window = min(window, MAX_POINTS)
    start = n - window
    em = OverlaySceneEmitter(entry.id, symbol, timeframe)

    cols = frame.columns
    price_names = [o.name for o in entry.outputs if o.unit == OutputUnit.PRICE and o.name in cols]
    pairs = _band_pairs(price_names)
    banded = {x for p in pairs for x in p}

    for lo_name, hi_name in pairs:
        lo_col, hi_col = cols[lo_name], cols[hi_name]
        segs: list[tuple[Decimal, Decimal, int, int]] = []
        for i in range(window):
            lo, hi = _num(lo_col[start + i]), _num(hi_col[start + i])
            if lo is None or hi is None:
                continue
            lo, hi = min(lo, hi), max(lo, hi)
            if segs and segs[-1][3] == i - 1 and segs[-1][0] == lo and segs[-1][1] == hi:
                segs[-1] = (lo, hi, segs[-1][2], i)
            else:
                segs.append((lo, hi, i, i))
        for lo, hi, x0, x1 in segs[-MAX_BAND_SEGMENTS:]:
            em.upsert_band(f"{entry.id}:{lo_name}-{hi_name}@{x0}", lo, hi, x0, x1)

    for out in entry.outputs:
        if out.name not in cols or out.name in banded:
            continue
        if out.unit == OutputUnit.EVENT:
            continue
        label = out.name if out.unit == OutputUnit.PRICE else f"pane:{out.name}"
        col = cols[out.name]
        for i in range(window):
            v = _num(col[start + i])
            if v is not None:
                em.record_indicator_point(label, i, v)

    for out in entry.outputs:
        if out.unit != OutputUnit.EVENT or out.name not in cols:
            continue
        col = cols[out.name]
        side, kind = _side(out.name), _kind(out.name)
        hits = [i for i in range(window) if col[start + i] is not None and bool(col[start + i])]
        for i in hits[-MAX_EVENT_MARKERS:]:
            em.add_signal(bars[start + i].close, i, side, kind)
        for i in hits[-MAX_HINT_EVENTS:]:
            em.add_hint(i, bars[start + i].close, HintSeverity.INFO, out.name, entry.title)
    return em.emit()


def study_to_scene(
    result: StudyResult,
    bars: Sequence[Bar],
    *,
    symbol: str,
    timeframe: str,
) -> OverlayScene:
    """One marker per listed study event (at most 500) plus a summary hint at the last one.

    ``result.events`` holds only the events the study listed (``max_events_listed``,
    chronological), so the hint says how many of ``event_count`` are drawn.
    """
    em = OverlaySceneEmitter(result.entry_id, symbol, timeframe)
    index = {b.ts: i for i, b in enumerate(bars)}
    side = MarkerSide.BUY if result.direction == 1 else MarkerSide.SELL
    placed: list[tuple[int, Decimal]] = []
    for ev in result.events[-MAX_STUDY_MARKERS:]:
        i = index.get(ev.ts)
        if i is None:
            continue
        em.add_signal(ev.price, i, side, MarkerKind.BREAKOUT)
        placed.append((i, ev.price))
    if placed and result.horizons:
        metrics: list[HintMetricSpec] = []
        for h in result.horizons:
            metrics.append(HintMetricSpec(f"h{h.horizon} hit rate", str(h.hit_rate)))
            metrics.append(HintMetricSpec(f"h{h.horizon} mean return", str(h.mean_return)))
        longest = max(result.horizons, key=lambda h: h.horizon)
        sev = HintSeverity.POSITIVE if longest.hit_rate > _HALF else HintSeverity.WARNING
        i, price = placed[-1]
        em.add_hint(
            i,
            price,
            sev,
            f"{result.event_column} study",
            f"{len(placed)} of {result.event_count} events shown",
            tuple(metrics),
        )
    return em.emit()
