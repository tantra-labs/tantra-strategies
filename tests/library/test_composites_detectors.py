from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tantra_library import (
    ATR,
    InvalidParam,
    PrCenterStep,
    PredictiveRanges,
    PrTrendRegime,
    PrZoneCloseBreak,
    PrZoneTouch,
    ReversalBars,
    ReversalBarSignal,
    VidyaTrend,
    VidyaTrendFlip,
)
from tantra_strategies.sdk.bar import Bar

D = Decimal
T0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
EPS = D("1e-18")


def mk(i: int, o: str, h: str, low: str, c: str, v: int = 100) -> Bar:
    return Bar(
        instrument="X",
        ts=T0 + timedelta(minutes=5 * i),
        open=D(o),
        high=D(h),
        low=D(low),
        close=D(c),
        volume=v,
        interval="5m",
    )


def cb(i: int, c: int) -> Bar:
    return mk(i, str(c), str(c + 1), str(c - 1), str(c))


def flat(n: int) -> list[Bar]:
    return [cb(i, 100) for i in range(n)]


def test_pr_no_step_before_atr_ready() -> None:
    pr = PredictiveRanges(length=3, factor=D(1))
    vals = [pr.update(b) for b in [cb(0, 100), cb(1, 150), cb(2, 100)]]
    assert vals[0].center is None and vals[1].center is None
    assert all(v.center_step == 0 for v in vals)
    assert vals[2].center == D(100)  # initialised from first bar
    assert vals[2].r1 is None  # no step yet


def test_pr_single_step_moves_center_by_atr() -> None:
    pr = PredictiveRanges(length=3, factor=D(1))
    ref = ATR(3)
    for b in flat(3):
        pr.update(b)
        ref.update(b)
    b = cb(3, 103)
    atr = ref.update(b)
    assert atr is not None
    v = pr.update(b)
    assert v.center_step == 1
    assert v.center == D(100) + atr
    assert v.r1 is not None and abs((v.r1 - v.center) - atr / 2) < EPS


def test_pr_step_down_and_single_step_on_gap() -> None:
    pr = PredictiveRanges(length=3, factor=D(1))
    ref = ATR(3)
    for b in flat(3):
        pr.update(b)
        ref.update(b)
    b = cb(3, 200)  # huge gap, still only one step
    atr = ref.update(b)
    assert atr is not None
    v = pr.update(b)
    assert v.center_step == 1 and v.center == D(100) + atr
    pr2 = PredictiveRanges(length=3, factor=D(1))
    ref2 = ATR(3)
    for b2 in flat(3):
        pr2.update(b2)
        ref2.update(b2)
    b3 = cb(3, 50)
    atr2 = ref2.update(b3)
    assert atr2 is not None
    v2 = pr2.update(b3)
    assert v2.center_step == -1 and v2.center == D(100) - atr2
    assert v2.s1 is not None and abs((v2.center - v2.s1) - atr2 / 2) < EPS


def test_pr_hold_frozen_across_non_step_bars() -> None:
    pr = PredictiveRanges(length=3, factor=D(1))
    for b in flat(3):
        pr.update(b)
    first = pr.update(cb(3, 103))
    assert first.center_step == 1
    assert first.r1 is not None and first.center is not None
    hold = first.r1 - first.center
    for i, c in enumerate([104, 105, 104, 106], start=4):
        v = pr.update(mk(i, str(c), str(c + 3), str(c - 3), str(c)))
        if v.center_step == 0:
            assert v.r1 is not None and v.center is not None
            assert abs((v.r1 - v.center) - hold) < EPS


def test_pr_property_random_walk() -> None:
    pr = PredictiveRanges(length=5, factor=D(1))
    ref = ATR(5)
    state = 12345
    price = 1000
    prev_center: D | None = None
    steps = 0
    for i in range(300):
        state = (state * 1103515245 + 12345) % (2**31)
        price += (state >> 8) % 21 - 10
        b = mk(i, str(price), str(price + 2), str(price - 2), str(price))
        atr = ref.update(b)
        v = pr.update(b)
        if v.center is not None and prev_center is not None and atr is not None:
            diff = abs(v.center - prev_center)
            assert diff == 0 or abs(diff - atr) < EPS
            assert (diff != 0) == (v.center_step != 0)
        if v.center is not None:
            prev_center = v.center
        if v.r1 is not None:
            assert v.r2 is not None and v.s1 is not None and v.s2 is not None
            assert v.center is not None
            hold = v.r1 - v.center
            assert abs((v.r2 - v.r1) - hold) < EPS
            assert abs((v.center - v.s1) - hold) < EPS
            assert abs((v.s1 - v.s2) - hold) < EPS
            steps += 1 if v.center_step else 0
    assert steps > 0


def test_pr_invalid_params_and_reset() -> None:
    with pytest.raises(InvalidParam):
        PredictiveRanges(length=0)
    with pytest.raises(InvalidParam):
        PredictiveRanges(factor=D(0))
    with pytest.raises(InvalidParam):
        PredictiveRanges(source="nope")
    pr = PredictiveRanges(length=3, factor=D(1))
    for b in flat(4):
        pr.update(b)
    pr.reset()
    assert pr.update(cb(0, 100)).center is None


def vt() -> VidyaTrend:
    return VidyaTrend(
        length=2, momentum=2, smoothing=0, atr_length=2, band_multiplier=D(0), normalization="total"
    )


def vt_bars() -> list[Bar]:
    return [
        *flat(3),
        mk(3, "100", "111", "99", "110", 500),
        mk(4, "110", "110", "107", "108", 100),
    ]


def test_vidya_trend_flip_up_and_volume_reset() -> None:
    t = vt()
    out = [t.update(b) for b in vt_bars()]
    assert all(o.trend == 0 and o.trend_line is None for o in out[:3])
    assert out[3].flipped == 1 and out[3].trend == 1
    assert out[3].trend_line == out[3].lower
    assert (out[3].up_volume, out[3].down_volume) == (500, 0)
    assert out[3].delta_pct == D(100)
    assert out[4].flipped == 0 and out[4].trend == 1
    assert (out[4].up_volume, out[4].down_volume) == (500, 100)
    assert out[4].delta_pct == D(100) * 400 / D(600)


def test_vidya_trend_delta_average_vs_total() -> None:
    a = VidyaTrend(2, 2, 0, 2, D(0), "average")
    last = None
    for b in vt_bars():
        last = a.update(b)
    assert last is not None
    assert last.delta_pct == D(100) * 400 / (D(600) / 2)
    with pytest.raises(InvalidParam):
        VidyaTrend(normalization="bad")
    with pytest.raises(InvalidParam):
        VidyaTrend(band_multiplier=D(-1))


def test_vidya_trend_flip_detector_and_reset() -> None:
    f = VidyaTrendFlip(2, 2, 0, 2, D(0), "total")
    evs = [f.update(b) for b in vt_bars()]
    assert [e.flip_up for e in evs] == [False, False, False, True, False]
    assert not any(e.flip_down for e in evs)
    f.reset()
    assert f.update(cb(0, 100)).delta_pct is None


def rb_bars(
    *, h0: str = "10", h1: str = "9", low: str = "6", close: str = "8", high: str = "9"
) -> list[Bar]:
    return [
        mk(0, "9", h0, "8", "9"),
        mk(1, "8", h1, "7", "8"),
        mk(2, "8", high, low, close),
    ]


def run_rb(rb: ReversalBars, bars: list[Bar]) -> object:
    out = None
    for b in bars:
        out = rb.update(b)
    return out


def test_reversal_bars_bullish_and_failures() -> None:
    rb = ReversalBars(lookback=2, require_alligator=False)
    v = rb.update(rb_bars()[0])
    assert not v.bullish and v.bull_trigger is None  # not enough history
    ok = run_rb(ReversalBars(2, False), rb_bars())
    assert ok.bullish and not ok.bearish and ok.bull_trigger == D(9)  # type: ignore[attr-defined]
    for bars in (
        rb_bars(close="7"),  # close in lower half (mid 7.5)
        rb_bars(low="7"),  # no new low
        rb_bars(h0="9", h1="10", high="10"),  # highs not descending
    ):
        res = run_rb(ReversalBars(2, False), bars)
        assert not res.bullish and res.bull_trigger is None  # type: ignore[attr-defined]


def test_reversal_bars_bearish_mirror() -> None:
    bars = [
        mk(0, "8", "10", "6", "8"),
        mk(1, "9", "11", "7", "9"),
        mk(2, "10", "12", "8", "9"),
    ]
    res = run_rb(ReversalBars(2, False), bars)
    assert res.bearish and not res.bullish and res.bear_trigger == D(8)  # type: ignore[attr-defined]
    bad = [bars[0], bars[1], mk(2, "10", "12", "8", "11")]  # close in upper half
    assert not run_rb(ReversalBars(2, False), bad).bearish  # type: ignore[attr-defined]
    bad2 = [bars[0], mk(1, "9", "11", "6", "9"), bars[2]]  # lows not ascending
    assert not run_rb(ReversalBars(2, False), bad2).bearish  # type: ignore[attr-defined]


def test_reversal_bars_ao_and_alligator_filters() -> None:
    # Short history: AO undefined, so the filter blocks the signal.
    assert not run_rb(ReversalBars(2, False, True), rb_bars()).bullish  # type: ignore[attr-defined]
    assert not run_rb(ReversalBars(2, True, False), rb_bars()).bullish  # type: ignore[attr-defined]
    # Long steady decline: AO falling, then a reversal-shaped bar.
    bars = [
        mk(i, str(299 - 3 * i), str(300 - 3 * i), str(298 - 3 * i), str(299 - 3 * i))
        for i in range(39)
    ]
    bars.append(mk(39, "182", "183", "173", "182"))
    with_ao = run_rb(ReversalBars(3, False, True), bars)
    assert with_ao.bullish  # type: ignore[attr-defined]
    # Alligator lines lag far above price, so high > min(lines) fails.
    assert not run_rb(ReversalBars(3, True, False), bars).bullish  # type: ignore[attr-defined]
    sig = ReversalBarSignal(3, False, True)
    last = None
    for b in bars:
        last = sig.update(b)
    assert last is not None and last.bullish
    sig.reset()
    assert not sig.update(bars[0]).bullish
    with pytest.raises(InvalidParam):
        ReversalBars(lookback=0)


def pr_args() -> tuple[int, D]:
    return (3, D(1))


def test_detectors_center_step_and_regime() -> None:
    cs = PrCenterStep(3, D(1))
    rg = PrTrendRegime(3, D(1), steps=2)
    bars = [*flat(3), cb(3, 103), cb(4, 110)]
    ce = [cs.update(b) for b in bars]
    re_ = [rg.update(b).regime for b in bars]
    assert [e.step_up for e in ce] == [False, False, False, True, True]
    assert not any(e.step_down for e in ce)
    assert ce[0].center is None and ce[3].center is not None
    assert re_ == [0, 0, 0, 0, 1]
    # Two down steps flip the regime negative.
    rg2 = PrTrendRegime(3, D(1), steps=2)
    out = [rg2.update(b).regime for b in [*flat(3), cb(3, 97), cb(4, 90)]]
    assert out[-1] == -1
    rg2.reset()
    assert rg2.update(cb(0, 100)).regime == 0


def pinned_s1_r1() -> tuple[D, D]:
    pr = PredictiveRanges(*pr_args())
    last = None
    for b in [*flat(3), cb(3, 103)]:
        last = pr.update(b)
    assert last is not None and last.s1 is not None and last.r1 is not None
    return last.s1, last.r1


def test_zone_touch_uses_previous_bar_levels() -> None:
    s1, r1 = pinned_s1_r1()
    zt = PrZoneTouch(*pr_args())
    for b in [*flat(3), cb(3, 103)]:
        ev = zt.update(b)
        assert not ev.support_touch  # no prior levels yet
    # Bar re-centers the range upward but its low touches the OLD s1.
    ev = zt.update(mk(4, "103", "112", "101", "110"))
    assert ev.support_touch and ev.resistance_touch
    assert ev.s1 == s1 and ev.r1 == r1
    zt.reset()
    assert not zt.update(cb(0, 100)).support_touch


def test_zone_close_break_excluded_on_step() -> None:
    s1, r1 = pinned_s1_r1()
    # Step bar closing above old r1: excluded.
    zb = PrZoneCloseBreak(*pr_args())
    evs = [zb.update(b) for b in [*flat(3), cb(3, 103), mk(4, "103", "112", "101", "110")]]
    assert not any(e.break_up for e in evs)
    # Non-step close above r1: break_up at the pinned level.
    zb2 = PrZoneCloseBreak(*pr_args())
    evs2 = [zb2.update(b) for b in [*flat(3), cb(3, 103), mk(4, "104", "106", "104", "105")]]
    assert evs2[-1].break_up and evs2[-1].level == r1 and not evs2[-1].break_down
    # Non-step close below s1: break_down.
    zb3 = PrZoneCloseBreak(*pr_args())
    evs3 = [zb3.update(b) for b in [*flat(3), cb(3, 103), mk(4, "102", "102", "100", "101")]]
    assert evs3[-1].break_down and evs3[-1].level == s1
    zb3.reset()
    assert not zb3.update(cb(0, 100)).break_down
