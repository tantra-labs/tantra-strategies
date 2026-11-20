from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tantra_library.composites import PredictiveRangesValue, ReversalBarsValue, VidyaTrendValue
from tantra_library.detectors import (
    CenterStepEvent,
    TrendRegimeEvent,
    ZoneBreakEvent,
    ZoneTouchEvent,
)
from tantra_strategies.sdk import Bar, MarkerKind, SimulatedContext, StopKind
from tantra_strategies.strategies import PrTrendPullbackStrategy, PrVidyaBreakoutStrategy

D = Decimal
T0 = datetime(2026, 1, 1, tzinfo=UTC)
INST = "X"


def bar(i: int, high: int, low: int, close: int) -> Bar:
    return Bar(INST, T0 + timedelta(days=i), D(close), D(high), D(low), D(close), 100, "1d")


class Const:
    def __init__(self, value: object) -> None:
        self.value = value

    def update(self, _bar: Bar) -> object:
        return self.value


class Pullback(PrTrendPullbackStrategy):
    """Pullback strategy with scripted detectors (long or short setup on bar 0)."""

    def __init__(self, regime: int = 1, short: bool = False, **kw: object) -> None:
        super().__init__(**kw)
        self.regime_value = regime
        self.short = short
        self.n = 0

    def on_start(self) -> None:
        super().on_start()
        long_ = not self.short
        self._regime = Const(TrendRegimeEvent(self.regime_value))
        self._atr = Const(D(1))
        self._pr = Const(PredictiveRangesValue(D(120), D(110), D(100), D(90), D(80), 0))
        outer = self

        class First:
            def __init__(self, first: object, rest: object) -> None:
                self.first, self.rest = first, rest

            def update(self, _bar: Bar) -> object:
                v = self.first if outer.n == 0 else self.rest
                outer.n += 1
                return v

        # touch and rev share the bar counter, so advance it in one place only
        self._touch = Const(ZoneTouchEvent(long_, not long_, D(90), D(110)))
        self._rev = First(
            ReversalBarsValue(
                long_, not long_, D(95) if long_ else None, None if long_ else D(105)
            ),
            ReversalBarsValue(False, False, None, None),
        )


class Breakout(PrVidyaBreakoutStrategy):
    def __init__(self, trend: int = 1, delta: str = "40", **kw: object) -> None:
        super().__init__(**kw)
        self.trend_value, self.delta_value = trend, D(delta)
        self.n = 0

    def on_start(self) -> None:
        super().on_start()
        v = VidyaTrendValue(
            D(100), D(110), D(90), D(90), self.trend_value, 0, 0, 0, self.delta_value
        )
        self._vidya = Const(v)
        self._atr = Const(D(1))
        self._step = Const(CenterStepEvent(False, False, D(99)))
        long_ = self.trend_value >= 0
        self._break = Const(ZoneBreakEvent(long_, not long_, D(99)))

        class Piv:
            def update(self, _b: Bar) -> tuple[Decimal | None, Decimal | None]:
                return (D(105), D(95))

        self._pivot = Piv()


def run(strategy: object, bars: list[Bar]) -> SimulatedContext:
    ctx = SimulatedContext()
    strategy.run(ctx, bars)  # type: ignore[attr-defined]
    return ctx


PULL = [bar(0, 95, 91, 94), bar(1, 96, 92, 95)]


def obar(i: int, o: str, high: str, low: str, close: str) -> Bar:
    return Bar(INST, T0 + timedelta(days=i), D(o), D(high), D(low), D(close), 100, "1d")


TARGET_BARS = [*PULL, obar(2, "105", "112", "100", "108")]
STOP_BARS = [*PULL, obar(2, "95", "96", "78", "85")]


def scene_dict(strategy: object) -> dict:
    return json.loads(json.dumps(strategy.emit_scene().to_dict()))  # type: ignore[attr-defined]


def test_scene_empty_before_run() -> None:
    scene = PrTrendPullbackStrategy().emit_scene()
    assert scene.strategy_id == "recipe.pr-trend-pullback"
    d = scene.to_dict()
    assert json.dumps(d)


def test_scene_after_target_exit() -> None:
    s = Pullback()
    run(s, TARGET_BARS)
    d = s.emit_scene().to_dict()
    bands = {(b["low"], b["high"], b["x0"], b["x1"]) for b in d["bands"]}
    assert bands == {("80", "90", 0, 2), ("110", "120", 0, 2)}
    assert [lv["price"] for lv in d["levels"]] == ["100"]
    scene = s.emit_scene()
    assert scene.strategy_id == "recipe.pr-trend-pullback"
    assert scene.symbol == "X"


def test_scene_records_signal_stops_connector() -> None:
    s = Pullback()
    run(s, TARGET_BARS)
    names = {k.value for k in StopKind} | {k.value for k in MarkerKind}
    text = json.dumps(s.emit_scene().to_dict())
    assert StopKind.INITIAL.value in names and StopKind.TARGET.value in names
    assert MarkerKind.RETEST.value in text
    assert MarkerKind.TARGET_HIT.value in text
    rec = s._record
    assert rec is not None
    conns = [e for e in rec.events if e[0] == "add_connector"]
    assert len(conns) == 1
    _, args, _ = conns[0]
    assert args[0] == 1 and args[2] == 2  # entry idx, exit idx
    assert args[4].name == "BUY" and args[6] is False
    assert isinstance(args[5], Decimal) and args[5] == D(1)  # (110-95)/(95-80)
    kinds = [e[1][1] for e in rec.events if e[0] == "add_stop"]
    assert kinds == [1, 1]


def test_scene_stopped_out_connector() -> None:
    s = Pullback()
    run(s, STOP_BARS)
    rec = s._record
    assert rec is not None
    ((_, args, _),) = [e for e in rec.events if e[0] == "add_connector"]
    assert args[6] is True and args[5] == D(-1)


def test_outer_buffer_stop_beyond_band_and_previous() -> None:
    s = Pullback(stop_policy="outer_atr_buffer")
    ctx = run(s, PULL)
    assert ctx.position("X") == D(1)
    rec = s._record
    assert rec is not None
    ((_, args, kw),) = [e for e in rec.events if e[0] == "add_stop" and e[1][3] == StopKind.INITIAL]
    assert args[0] < D(80)
    assert kw["previous"] is not None


def test_recipe_policy_unchanged() -> None:
    s = Pullback()
    ctx = run(s, PULL)
    assert ctx.position("X") == D(1)
    assert run(Pullback(), TARGET_BARS).position("X") == D(0)
    rec = s._record
    assert rec is not None
    ((_, args, kw),) = [e for e in rec.events if e[0] == "add_stop" and e[1][3] == StopKind.INITIAL]
    assert args[0] == D(80) and kw["previous"] is None


def test_invalid_policy_raises() -> None:
    with pytest.raises(ValueError):
        run(Pullback(stop_policy="nope"), PULL)


def test_breakout_scene_and_policy() -> None:
    s = Breakout(stop_policy="outer_atr_buffer")
    ctx = run(s, [bar(0, 101, 99, 100), bar(1, 106, 99, 105)])
    # Target R:R follows the policy stop (97.75 -> 100 + 1.5 * 2.25), not the recipe stop.
    assert ctx.orders[1].stop_price == D("97.75")
    assert ctx.orders[2].limit_price == D("103.375")
    exits = [e for e in ctx.events if e.side.value == "sell" and e.status.value == "complete"]
    assert [e.price for e in exits] == [D(105)]  # bar 1 opens at 105: gap-through fill at the open
    assert ctx.position("X") == D(0)
    assert MarkerKind.BREAKOUT.value in json.dumps(s.emit_scene().to_dict())
    assert s.emit_scene().strategy_id == "recipe.pr-vidya-breakout"


def test_bounded_history() -> None:
    class Walk(Pullback):
        def on_start(self) -> None:
            super().on_start()
            self._n = 0

            outer = self

            class Moving:
                def update(self, _b: object) -> PredictiveRangesValue:
                    outer._n += 1
                    c = D(outer._n)
                    return PredictiveRangesValue(c + 20, c + 10, c, c - 10, c - 20, 0)

            self._pr = Moving()

    s = Walk(regime=0)
    run(s, [bar(i, 101, 99, 100) for i in range(3000)])
    rec = s._record
    assert rec is not None
    assert len(rec.points["pr_center"]) <= 2000
    assert all(len(v) <= 50 for v in rec.segments.values())
    assert json.dumps(s.emit_scene().to_dict())


@pytest.mark.parametrize("cls", [PrTrendPullbackStrategy, PrVidyaBreakoutStrategy])
def test_policy_stop_on_wrong_side_of_entry_skips_entry(cls: type) -> None:
    strategy = cls(stop_policy="outer_edge")
    b = bar(0, 111, 109, 110)  # entry (close) 110, far above the band
    short = strategy._resolve_stop(b, -1, D(120), (D(100), D(101)), D(1), D("0.25"))
    assert short is None  # outer-edge stop ~101 sits below a short entry at 110
    long_ok = strategy._resolve_stop(b, 1, D(90), (D(100), D(101)), D(1), D("0.25"))
    assert long_ok is not None and long_ok[0] < D(110)
