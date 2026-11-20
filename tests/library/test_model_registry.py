from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tantra_library import (
    DependencyError,
    DuplicateEntry,
    Entry,
    EntryKind,
    InputKind,
    InputQualityError,
    InvalidParam,
    LimitExceeded,
    NotComputable,
    OutputSpec,
    OutputUnit,
    ParamSpec,
    ParamType,
    ParamValue,
    Registry,
    StreamingComputation,
    UnknownEntry,
    UnknownParam,
    Value,
    VolumeQuality,
)
from tantra_strategies.sdk.bar import Bar

D = Decimal
T0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)


def mkbar(i: int, close: str = "10", inst: str = "X", ts: datetime | None = None) -> Bar:
    c = D(close)
    return Bar(inst, ts or T0 + timedelta(minutes=5 * i), c, c + 1, c - 1, c, 100)


class Echo:
    def __init__(self, params: Mapping[str, ParamValue]) -> None:
        self.mult = params["mult"]

    def update(self, bar: Bar) -> Mapping[str, Value]:
        assert isinstance(self.mult, Decimal)
        return {"out": bar.close * self.mult}

    def reset(self) -> None:
        return None


def echo_factory(params: Mapping[str, ParamValue]) -> StreamingComputation:
    return Echo(params)


def ind(eid: str = "ind.echo", **kw: object) -> Entry:
    base: dict[str, object] = {
        "id": eid,
        "kind": EntryKind.INDICATOR,
        "title": "Echo Indicator",
        "summary": "Echoes close times a multiplier",
        "params": (
            ParamSpec("mult", ParamType.DECIMAL, D(1), "multiplier", D(0), D(10)),
            ParamSpec("n", ParamType.INT, 3, "count", D(1), D(50)),
        ),
        "outputs": (OutputSpec("out", OutputUnit.PRICE, "echo"),),
        "inputs": InputKind.OHLC,
        "factory": echo_factory,
    }
    base.update(kw)
    return Entry(**base)  # type: ignore[arg-type]


def test_param_coerce() -> None:
    p = ParamSpec("n", ParamType.INT, 3, "d", D(1), D(10))
    assert p.coerce("5") == 5
    assert p.coerce(7) == 7
    with pytest.raises(InvalidParam, match="floats"):
        p.coerce(1.5)
    with pytest.raises(InvalidParam, match="minimum"):
        p.coerce(0)
    with pytest.raises(InvalidParam, match=r"'n'.*maximum"):
        p.coerce(11)
    with pytest.raises(InvalidParam):
        p.coerce(True)
    d = ParamSpec("m", ParamType.DECIMAL, D(1), "d")
    assert d.coerce("1.25") == D("1.25")
    assert d.coerce(2) == D(2)
    with pytest.raises(InvalidParam):
        d.coerce("abc")
    with pytest.raises(InvalidParam):
        d.coerce("NaN")
    e = ParamSpec("s", ParamType.ENUM, "a", "d", choices=("a", "b"))
    assert e.coerce("b") == "b"
    with pytest.raises(InvalidParam):
        e.coerce("c")
    b = ParamSpec("f", ParamType.BOOL, False, "d")
    assert b.coerce(True) is True
    with pytest.raises(InvalidParam):
        b.coerce("true")
    assert d.to_dict()["default"] == "1"


def test_register_get_dup_entries() -> None:
    r = Registry()
    r.register(ind("b.x"))
    r.register(ind("a.y", family=None))
    with pytest.raises(DuplicateEntry):
        r.register(ind("a.y"))
    with pytest.raises(UnknownEntry):
        r.get("nope")
    assert [e.id for e in r.entries()] == ["a.y", "b.x"]
    assert r.entries(kind=EntryKind.CONCEPT) == []


def test_search_ranking() -> None:
    r = Registry()
    r.register(ind("ind.vidya", title="VIDYA", summary="variable moving average"))
    r.register(ind("ind.sma", title="SMA", summary="a vidya-like average mention"))
    r.register(ind("ind.other", title="Other", summary="nothing"))
    res = r.search("vidya")
    assert [e.id for e in res] == ["ind.vidya", "ind.sma"]
    assert len(r.search("")) == 3
    assert r.search("vidya", limit=1)[0].id == "ind.vidya"
    assert r.search("vidya", kind=EntryKind.CONCEPT) == []


def test_validate() -> None:
    r = Registry()
    r.register(ind("a", depends_on=("missing",)))
    with pytest.raises(DependencyError, match=r"'a'.*'missing'"):
        r.validate()
    r2 = Registry()
    r2.register(ind("a", depends_on=("b",)))
    r2.register(ind("b", depends_on=("c",)))
    r2.register(ind("c", depends_on=("a",)))
    with pytest.raises(DependencyError, match="cycle"):
        r2.validate()
    r3 = Registry()
    r3.register(ind("a", concepts=("b",)))
    r3.register(ind("b"))
    with pytest.raises(DependencyError, match="not a concept"):
        r3.validate()


def test_validate_ok() -> None:
    r = Registry()
    r.register(Entry("fam", EntryKind.FAMILY, "Fam", "f"))
    r.register(Entry("con", EntryKind.CONCEPT, "Con", "c", family="fam"))
    r.register(ind("a", family="fam", concepts=("con",)))
    r.validate()


def test_resolve_params() -> None:
    r = Registry()
    r.register(ind())
    assert r.resolve_params("ind.echo", {}) == {"mult": D(1), "n": 3}
    assert r.resolve_params("ind.echo", {"mult": "2.5"})["mult"] == D("2.5")
    with pytest.raises(UnknownParam):
        r.resolve_params("ind.echo", {"zzz": 1})


def test_build_not_computable() -> None:
    r = Registry()
    r.register(ind(factory=None))
    with pytest.raises(NotComputable):
        r.build("ind.echo", {})


def test_evaluate() -> None:
    r = Registry()
    r.register(ind())
    bars = [mkbar(i, str(10 + i)) for i in range(3)]
    f = r.evaluate("ind.echo", {"mult": "2"}, bars)
    assert f.columns["out"] == [D(20), D(22), D(24)]
    assert f.to_dict()["params"] == {"mult": "2", "n": 3}
    assert len(f.timestamps) == 3
    with pytest.raises(LimitExceeded):
        r.evaluate("ind.echo", {}, bars, max_bars=2)
    with pytest.raises(InvalidParam, match="increasing"):
        r.evaluate("ind.echo", {}, [bars[1], bars[0]])
    with pytest.raises(InvalidParam, match="instrument"):
        r.evaluate("ind.echo", {}, [bars[0], mkbar(1, inst="Y")])


def test_evaluate_volume_quality() -> None:
    r = Registry()
    r.register(ind(volume_quality=VolumeQuality.REAL))
    with pytest.raises(InputQualityError):
        r.evaluate("ind.echo", {}, [mkbar(0)], source_volume_quality=VolumeQuality.TICK)
    assert r.evaluate("ind.echo", {}, [mkbar(0)]).columns["out"] == [D(10)]


def test_describe_markdown() -> None:
    r = Registry()
    r.register(Entry("fam", EntryKind.FAMILY, "Fam", "f"))
    r.register(Entry("con", EntryKind.CONCEPT, "Trend Concept", "about trend", family="fam"))
    r.register(ind("ind.echo", family="fam", concepts=("con",), depends_on=("con",)))
    md = r.describe_markdown("ind.echo")
    assert md.startswith("# Echo Indicator")
    assert "`ind.echo` · indicator · family `fam`" in md
    assert "## Parameters" in md and "| mult | decimal | 1 | 0..10 | multiplier |" in md
    assert "## Outputs" in md and "## Builds on" in md
    assert "## Provenance" not in md
    cmd = r.describe_markdown("con")
    assert "## Implementations" in cmd and "`ind.echo`" in cmd
