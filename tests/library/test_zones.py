from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tantra_library import default_registry
from tantra_library.zones import (
    EeSweep,
    ElephantZones,
    OpeningRange,
    Orb15Breakout,
    SessionTracker,
)
from tantra_strategies.sdk.bar import Bar
from tantra_strategies.sdk.primitives import (
    AssetClass,
    ElephantZonesExtractor,
    HorizonMode,
    ZoneExtractionContext,
)

D = Decimal
# 03:45 UTC == 09:15 IST
DAY0 = datetime(2026, 3, 2, 3, 45, tzinfo=UTC)


def _bar(day: int, i: int, o: int, h: int, lo: int, c: int) -> Bar:
    ts = DAY0 + timedelta(days=day, minutes=5 * i)
    return Bar("X", ts, D(o), D(h), D(lo), D(c), 100)


def _series(days: int = 4, per_day: int = 25) -> list[Bar]:
    out: list[Bar] = []
    for d in range(days):
        base = 1000 + 7 * d
        for i in range(per_day):
            wave = (i * 5) % 17 - 8
            o = base + wave
            c = base + ((i + 1) * 5) % 17 - 8
            out.append(_bar(d, i, o, max(o, c) + 3, min(o, c) - 3, c))
    return out


def test_zones_none_vs_ready() -> None:
    ez = ElephantZones()
    vals = [ez.update(b) for b in _series()[:20]]
    assert vals[0].long_outer_sl is None and vals[0].short_outer_sl is None
    assert vals[-1].long_outer_sl is not None
    assert vals[-1].s2 < vals[-1].s1 < vals[-1].r1 < vals[-1].r2


def test_percentile_parity_with_extractor() -> None:
    bars = _series()
    ez = ElephantZones()
    tr = SessionTracker(HorizonMode.INTRADAY, AssetClass.INDEX)
    last = None
    for b in bars:
        last = ez.update(b)
        tr.update(b)
    assert len(tr.completed) == 3
    assert last is not None
    # Percentile mode (>=2 completed sessions): s1 = open - P25(drawdowns), differs from phi mode.
    ctx = ZoneExtractionContext(
        "X",
        bars[-1],
        tr.bar_index,
        tr.bars[0].open,
        tr.bars,
        tuple(tr.completed),
        last.half_width * 2,
    )
    lm = ElephantZonesExtractor().extract(ctx)
    prices = {lv.level_id: lv.price for lv in lm.levels}
    assert (last.s1, last.s2, last.r1, last.r2) == (
        prices["ee:s1"],
        prices["ee:s2"],
        prices["ee:r1"],
        prices["ee:r2"],
    )
    first = tr.bars[0]
    rng = first.high - first.low
    assert last.s1 != first.close - D("1.618") * rng


def test_outer_stop_beyond_band() -> None:
    ez = ElephantZones()
    v = None
    for b in _series()[:30]:
        v = ez.update(b)
    assert v is not None and v.long_outer_sl is not None and v.short_outer_sl is not None
    assert v.long_outer_sl < v.s1 - v.half_width
    assert v.short_outer_sl > v.r1 + v.half_width


def test_completed_sessions_bounded() -> None:
    ez = ElephantZones(max_sessions=2)
    for b in _series(days=6, per_day=5):
        ez.update(b)
    assert len(ez.tracker.completed) == 2


def test_opening_range_not_exposed_early() -> None:
    orng = OpeningRange(opening_bars=3)
    vals = [orng.update(b) for b in _series(days=2)]
    assert vals[0].or_high is None and vals[1].or_low is None
    assert vals[2].or_high is not None
    assert vals[25].or_high is None  # new session restarts the window
    assert vals[27].or_mid is not None
    first3 = _series(days=1)[:3]
    assert vals[2].or_high == max(b.high for b in first3)
    assert vals[2].or_low == min(b.low for b in first3)


def test_orb_breakout_fires_once_per_session() -> None:
    bars = [
        _bar(0, 0, 100, 102, 99, 101),
        _bar(0, 1, 101, 103, 98, 100),
        _bar(0, 2, 100, 102, 99, 101),
        _bar(0, 3, 101, 106, 101, 105),  # close > 103 -> break_up
        _bar(0, 4, 105, 108, 104, 107),  # again above: no refire
        _bar(0, 5, 107, 107, 95, 96),  # close < 98 -> break_down
        _bar(0, 6, 96, 97, 90, 91),  # no refire
        _bar(1, 0, 100, 102, 99, 101),
        _bar(1, 1, 101, 103, 98, 100),
        _bar(1, 2, 100, 102, 99, 101),
        _bar(1, 3, 101, 106, 101, 105),  # fires again in new session
    ]
    det = Orb15Breakout(OpeningRange())
    out = [det.update(b) for b in bars]
    assert [o.break_up for o in out] == [False] * 3 + [True] + [False] * 6 + [True]
    assert [o.break_down for o in out] == [False] * 5 + [True] + [False] * 5
    assert out[3].level == D("103")
    assert out[5].level == D("98")


def test_ee_sweep_exact_semantics() -> None:
    # Single-bar session: golden-ratio warm-up from the first bar, deterministic levels.
    zones = ElephantZones()
    first = _bar(0, 0, 1000, 1010, 990, 1000)
    z0 = zones.update(first)
    lo_edge = z0.s1 - z0.half_width
    det = EeSweep(ElephantZones())
    det.update(first)
    # Same session: first bar anchors the levels; ATR is not ready yet.
    nxt = Bar("X", first.ts + timedelta(minutes=5), D(1000), D(1000), lo_edge - 1, lo_edge + 1, 1)
    v = det.update(nxt)
    assert v.bull_sweep is True and v.bear_sweep is False
    assert v.level == z0.s1


@pytest.mark.parametrize("entry_id", ["det.ee-sweep", "det.orb15-breakout"])
def test_registry_frames_full_length(entry_id: str) -> None:
    bars = _series()
    frame = default_registry().evaluate(entry_id, {}, bars)
    assert all(len(col) == len(bars) for col in frame.columns.values())


def test_search_finds_new_entries() -> None:
    reg = default_registry()
    assert "ind.elephant-zones" in [e.id for e in reg.search("elephant")]
    assert "det.orb15-breakout" in [e.id for e in reg.search("orb")]
