from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tantra_library import (
    ATR,
    CMO,
    RMA,
    SMA,
    VIDYA,
    Alligator,
    ATRBands,
    AwesomeOscillator,
    Highest,
    InvalidParam,
    LinReg,
    Lowest,
    SwingPivot,
    TrueRange,
    UpDownVolume,
    VolumeDeltaPct,
    median_price,
    source_value,
    typical_price,
)
from tantra_strategies.sdk.bar import Bar
from tantra_strategies.sdk.indicators import ATR as SdkATR

D = Decimal
T0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)


def mk(i: int, o: str, h: str, low: str, c: str, v: int = 0) -> Bar:
    return Bar("X", T0 + timedelta(minutes=5 * i), D(o), D(h), D(low), D(c), v)


def test_true_range() -> None:
    tr = TrueRange()
    assert tr.update(mk(0, "10", "12", "9", "11")) == D(3)
    # prev close 11: h-l=2, |15-11|=4, |13-11|=2
    assert tr.update(mk(1, "13", "15", "13", "14")) == D(4)
    # gap down: |l - prevC| = |8-14| = 6
    assert tr.update(mk(2, "9", "10", "8", "9")) == D(6)


def test_rma() -> None:
    r = RMA(3)
    assert r.update(D(3)) is None
    assert r.update(D(6)) is None
    assert r.update(D(9)) == D(6)
    assert r.update(D(12)) == (D(6) * 2 + D(12)) / 3
    assert r.value == D(8)
    r.reset()
    assert r.value is None
    with pytest.raises(InvalidParam):
        RMA(0)


def test_sma() -> None:
    s = SMA(3)
    assert [s.update(D(x)) for x in (1, 2, 3, 4)] == [None, None, D(2), D(3)]


def test_highest_lowest() -> None:
    hi, lo = Highest(3), Lowest(3)
    xs = [5, 1, 4, 2, 3, 0]
    assert [hi.update(D(x)) for x in xs] == [None, None, D(5), D(4), D(4), D(3)]
    assert [lo.update(D(x)) for x in xs] == [None, None, D(1), D(1), D(2), D(0)]


def test_price_helpers() -> None:
    b = mk(0, "10", "14", "8", "12")
    assert median_price(b) == D(11)
    assert typical_price(b) == D(34) / 3
    assert source_value(b, "ohlc4") == D(11)
    assert source_value(b, "close") == D(12)
    with pytest.raises(InvalidParam):
        source_value(b, "vwap")


def test_swing_pivot() -> None:
    p = SwingPivot(2, 2)
    series = [("11", "10"), ("12", "11"), ("15", "14"), ("12", "11"), ("11", "10")]
    outs = [p.update(mk(i, h, h, low, h)) for i, (h, low) in enumerate(series)]
    assert outs[:4] == [(None, None)] * 4
    assert outs[4] == (D(15), None)
    p2 = SwingPivot(2, 2)
    series2 = [("20", "19"), ("19", "18"), ("15", "14"), ("19", "18"), ("20", "19")]
    outs2 = [p2.update(mk(i, h, h, low, h)) for i, (h, low) in enumerate(series2)]
    assert outs2[4] == (None, D(14))


def test_up_down_volume() -> None:
    u = UpDownVolume()
    assert u.update(mk(0, "10", "12", "9", "11", 100)) == (100, 0)
    assert u.update(mk(1, "11", "12", "9", "10", 70)) == (0, 70)
    assert u.update(mk(2, "10", "12", "9", "10", 50)) == (0, 0)


def test_linreg_perfect_line() -> None:
    lr = LinReg(5)
    outs = [lr.update(D(2 + 2 * i)) for i in range(5)]
    assert outs[:4] == [None] * 4
    assert outs[4] == (D(2), D(10))


def _series(n: int) -> list[Bar]:
    bars = []
    for i in range(n):
        base = 100 + (i * 7) % 11 - (i % 3)
        bars.append(
            mk(
                i,
                str(base),
                str(base + 3 + i % 4),
                str(base - 2 - i % 2),
                str(base + 1 - i % 3),
                100 + i,
            )
        )
    return bars


def test_atr_matches_sdk() -> None:
    mine, sdk = ATR(14), SdkATR(14)
    for b in _series(40):
        got = mine.update(b)
        sdk.update(b)
        if sdk.ready:
            assert got == sdk.value
        else:
            assert got is None


def test_atr_bands() -> None:
    ab = ATRBands(2, D("2"), "close")
    assert ab.update(mk(0, "10", "12", "9", "11")) is None
    v = ab.update(mk(1, "11", "13", "10", "12"))
    assert v is not None
    # TR0=3, TR1=max(3,|13-11|,|10-11|)=3 -> ATR=3, offset 6
    assert (v.upper, v.middle, v.lower) == (D(18), D(12), D(6))
    with pytest.raises(InvalidParam):
        ATRBands(2, D(1), "nope")


def _closes(xs: list[int]) -> list[Decimal]:
    return [D(x) for x in xs]


def test_cmo() -> None:
    up, down, flat = CMO(3), CMO(3), CMO(3)
    assert [up.update(x) for x in _closes([1, 2, 3, 4])] == [None, None, None, D(100)]
    assert [down.update(x) for x in _closes([4, 3, 2, 1])][-1] == D(-100)
    assert [flat.update(x) for x in _closes([5, 5, 5, 5])][-1] == D(0)


def test_vidya_three_steps() -> None:
    v = VIDYA(3, 2)  # alpha = 1/2
    outs = [v.update(x) for x in _closes([10, 12, 14, 12, 10])]
    assert outs[:2] == [None, None]
    # cmo=100 -> k=.5, prev seed 10 -> 12 ; cmo=0 -> k=0 -> 12 ; cmo=-100 -> k=.5 -> 11
    assert outs[2:] == [D(12), D(12), D(11)]


def test_vidya_smoothing() -> None:
    v = VIDYA(3, 2, smoothing=2)
    outs = [v.update(x) for x in _closes([10, 12, 14, 12, 10])]
    assert outs == [None, None, None, D(12), D("11.5")]


def test_volume_delta_pct() -> None:
    bars = [mk(0, "10", "12", "9", "11", 300), mk(1, "11", "12", "9", "10", 100)]
    tot, avg = VolumeDeltaPct(2, "total"), VolumeDeltaPct(2, "average")
    assert [tot.update(b) for b in bars] == [None, D(50)]
    assert [avg.update(b) for b in bars] == [None, D(100)]
    with pytest.raises(InvalidParam):
        VolumeDeltaPct(2, "bogus")


def test_alligator_shift() -> None:
    bars = _series(30)
    al = Alligator()
    ref = RMA(5)
    lips_hist: list[Decimal | None] = []
    for t, b in enumerate(bars):
        out = al.update(b)
        lips_hist.append(ref.update(median_price(b)))
        expected = lips_hist[t - 3] if t - 3 >= 0 else None
        assert out.lips == expected
    assert al.value is not None and al.value.jaw is not None
    assert al.value.teeth is not None


def test_awesome_oscillator() -> None:
    ao = AwesomeOscillator(2, 3)
    bars = [mk(i, "1", str(h), str(h), "1") for i, h in enumerate([2, 4, 6, 8])]
    outs = [ao.update(b) for b in bars]
    assert outs[:2] == [None, None]
    # t=2: fast=(4+6)/2=5, slow=(2+4+6)/3=4 -> 1 ; t=3: 7 - 6 = 1
    assert outs[2:] == [D(1), D(1)]
