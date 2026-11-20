from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

import pytest

from tantra_library import (
    EventFilter,
    InvalidParam,
    LimitExceeded,
    default_registry,
    signal_study,
)
from tantra_strategies.sdk.bar import Bar

D = Decimal
Q8 = D("0.00000001")
CLOSES = [100] * 5 + [104, 108, 112, 116, 120, 118, 116, 114, 112, 110, 108]
# step_up fires at bars 5..9 (closes 104..120); high = close + 1, low = close - 1.
UP = [5, 6, 7, 8, 9]
PARAMS = {"length": 3, "factor": 1}


def make_bars() -> list[Bar]:
    start = datetime(2025, 12, 25, tzinfo=UTC)  # bars 5,6 -> 2025; bars 7.. -> 2026
    return [
        Bar("X", start + timedelta(days=i), D(c), D(c) + 1, D(c) - 1, D(c), 100, "1d")
        for i, c in enumerate(CLOSES)
    ]


def q(x: Decimal) -> Decimal:
    return x.quantize(Q8, ROUND_HALF_EVEN)


def fwd(i: int, h: int, d: int = 1) -> Decimal:
    return D(d) * (D(CLOSES[i + h]) - D(CLOSES[i])) / D(CLOSES[i])


def study(**kw: object):  # type: ignore[no-untyped-def]
    kw.setdefault("event_column", "step_up")
    return signal_study(default_registry(), "det.pr-center-step", PARAMS, make_bars(), **kw)  # type: ignore[arg-type]


def test_counts_returns_hit_rate_median() -> None:
    r = study(horizons=(1, 3))
    assert r.event_count == 5
    assert r.bars == 16
    h1, h3 = r.horizons
    rets = sorted(fwd(i, 1) for i in UP)
    assert h1.horizon == 1 and h1.count == 5
    assert h1.hit_rate == D("0.8000")
    assert h1.mean_return == q(sum(rets, D(0)) / 5)
    assert h1.median_return == q(rets[2])
    rets3 = [fwd(i, 3) for i in UP]
    assert h3.hit_rate == D("0.6000")  # 3 of 5 positive, one zero, one negative
    assert h3.mean_return == q(sum(rets3, D(0)) / 5)


def test_mfe_mae_by_hand() -> None:
    r = study(horizons=(1, 3))
    # windows (bars i+1..i+3): favourable via high, adverse via low (high=c+1, low=c-1)
    fav = [D(13) / 104, D(13) / 108, D(9) / 112, D(5) / 116, D(0)]
    adv = [D(0), D(0), D(0), D(1) / 116, D(7) / 120]
    assert r.mfe_mean == q(sum(fav, D(0)) / 5)
    assert r.mae_mean == q(sum(adv, D(0)) / 5)


def test_direction_flips_sign() -> None:
    r = study(horizons=(1,), direction=-1)
    assert r.horizons[0].hit_rate == D("0.2000")
    assert r.horizons[0].mean_return == q(sum((fwd(i, 1, -1) for i in UP), D(0)) / 5)
    # short MFE uses lows: bar 9 (c=120) window low 117 -> fav 3 + ... computed via adverse side
    assert r.mfe_mean is not None and r.mae_mean is not None


def test_filter_excludes_events() -> None:
    flt = EventFilter("det.pr-center-step", PARAMS, "center", "119.7901234567901234567901235")
    r = study(horizons=(1,), event_filter=flt)
    assert r.event_count == 1
    assert r.events[0].price == D(120)


def test_truncated_listing_and_dict() -> None:
    r = study(horizons=(1,), max_events_listed=2)
    assert r.truncated and len(r.events) == 2 and r.event_count == 5
    d = r.to_dict()
    assert d["truncated"] is True
    assert d["events"][0]["price"] == "104"  # type: ignore[index]
    assert isinstance(d["mfe_mean"], str) or d["mfe_mean"] is None


def test_by_year_split() -> None:
    r = study(horizons=(1, 3))
    assert sorted(r.by_year) == [2025, 2026]
    c25, m25 = r.by_year[2025]
    c26, m26 = r.by_year[2026]
    assert (c25, c26) == (2, 3)
    assert m25 == q((fwd(5, 1) + fwd(6, 1)) / 2)
    assert m26 == q((fwd(7, 1) + fwd(8, 1) + fwd(9, 1)) / 3)


def test_events_without_horizon_excluded_per_horizon() -> None:
    r = study(event_column="step_down", horizons=(1, 5))
    # step_down at bars 11, 13, 15: horizon 1 has bars 11, 13; horizon 5 has none
    assert r.event_count == 3
    assert r.horizons[0].count == 2
    assert r.horizons[1].count == 0 and r.horizons[1].mean_return == D(0)
    assert r.mfe_mean is None and r.mae_mean is None


@pytest.mark.parametrize(
    ("kw", "exc"),
    [
        ({"event_column": "nope"}, InvalidParam),
        ({"direction": 0}, InvalidParam),
        ({"horizons": (0,)}, InvalidParam),
        ({"horizons": (16,)}, InvalidParam),
        ({"horizons": ()}, InvalidParam),
        ({"horizons": (1, 2, 3), "max_horizons": 2}, LimitExceeded),
    ],
)
def test_invalid_inputs(kw: dict[str, object], exc: type[Exception]) -> None:
    with pytest.raises(exc):
        study(**kw)
