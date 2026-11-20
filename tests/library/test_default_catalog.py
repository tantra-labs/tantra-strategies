from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tantra_library import (
    EntryKind,
    InputQualityError,
    NotComputable,
    PredictiveRanges,
    VolumeQuality,
    build_default_registry,
    default_registry,
)
from tantra_strategies.sdk.bar import Bar

D = Decimal
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _bars(n: int = 300) -> list[Bar]:
    out: list[Bar] = []
    state = 12345
    close = 1000
    for i in range(n):
        state = (state * 1103515245 + 12345) % 2**31
        step = state % 41 - 20
        open_ = close
        close = max(100, close + step)
        high = max(open_, close) + state % 7
        low = min(open_, close) - (state // 7) % 7
        out.append(
            Bar("X", T0 + timedelta(days=i), D(open_), D(high), D(low), D(close), 100 + state % 50)
        )
    return out


def test_registry_validates_and_counts() -> None:
    reg = build_default_registry()
    reg.validate()
    expected = {
        EntryKind.FAMILY: 6,
        EntryKind.CONCEPT: 12,
        EntryKind.PRIMITIVE: 8,
        EntryKind.INDICATOR: 10,
        EntryKind.COMPOSITE: 3,
        EntryKind.DETECTOR: 6,
        EntryKind.RECIPE: 2,
    }
    for kind, count in expected.items():
        assert len(reg.entries(kind)) == count, kind
    assert default_registry() is default_registry()


def test_every_concept_has_implementation() -> None:
    reg = default_registry()
    for concept in reg.entries(EntryKind.CONCEPT):
        assert any(concept.id in e.concepts for e in reg.entries()), concept.id


def test_every_computable_entry_evaluates() -> None:
    reg = default_registry()
    bars = _bars()
    computable = [e for e in reg.entries() if e.factory is not None]
    assert len(computable) == 27
    for entry in computable:
        frame = reg.evaluate(entry.id, {}, bars)
        assert set(frame.columns) == {o.name for o in entry.outputs}, entry.id
        assert all(len(col) == 300 for col in frame.columns.values()), entry.id


def test_recipes_not_computable() -> None:
    reg = default_registry()
    for recipe in reg.entries(EntryKind.RECIPE):
        with pytest.raises(NotComputable):
            reg.build(recipe.id, {})


def test_describe_and_search() -> None:
    reg = default_registry()
    md = reg.describe_markdown("concept.volatility-range")
    assert "## How it's calculated" in md
    assert "## Implementations" in md
    assert "`ind.predictive-ranges`" in md.split("## Implementations")[1]
    assert reg.search("predictive")[0].id == "ind.predictive-ranges"


def test_real_volume_entries_reject_tick_source() -> None:
    reg = default_registry()
    real = [e for e in reg.entries() if e.volume_quality is VolumeQuality.REAL and e.factory]
    assert real
    for entry in real:
        with pytest.raises(InputQualityError):
            reg.evaluate(entry.id, {}, _bars(5), source_volume_quality=VolumeQuality.TICK)


def test_predictive_ranges_matches_direct() -> None:
    reg = default_registry()
    bars = _bars()
    params = {"length": 14, "factor": "3"}
    frame = reg.evaluate("ind.predictive-ranges", params, bars)
    direct = PredictiveRanges(14, D(3), "close")
    rows = [direct.update(b) for b in bars]
    for name in ("r2", "r1", "center", "s1", "s2", "center_step"):
        assert frame.columns[name] == [getattr(r, name) for r in rows]


def test_search_exact_name_ranks_basic_entry_first() -> None:
    from tantra_library import default_registry

    ids = [e.id for e in default_registry().search("vidya")]
    assert ids[0] == "ind.vidya"
    assert default_registry().search("predictive ranges")[0].id == "ind.predictive-ranges"
