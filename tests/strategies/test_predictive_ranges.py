from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tantra_library.composites import PredictiveRangesValue, ReversalBarsValue, VidyaTrendValue
from tantra_library.detectors import (
    CenterStepEvent,
    TrendRegimeEvent,
    ZoneBreakEvent,
    ZoneTouchEvent,
)
from tantra_strategies.sdk import Bar, SimulatedContext
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


def test_pullback_long_entry_then_target_exit() -> None:
    bars = [bar(0, 95, 91, 94), bar(1, 96, 92, 95), bar(2, 111, 100, 110)]
    assert run(Pullback(), bars[:2]).position(INST) == D(1)
    assert run(Pullback(), bars).position(INST) == D(0)


def test_pullback_stop_exit_and_stop_priority() -> None:
    stop_bars = [bar(0, 95, 91, 94), bar(1, 96, 92, 95), bar(2, 100, 79, 85)]
    both = [bar(0, 95, 91, 94), bar(1, 96, 92, 95), bar(2, 111, 79, 100)]
    assert run(Pullback(), stop_bars).position(INST) == D(0)
    assert run(Pullback(), both).position(INST) == D(0)


def test_pullback_cancelled_when_not_triggered() -> None:
    bars = [bar(0, 95, 91, 94), bar(1, 94, 92, 93), bar(2, 97, 93, 96)]
    assert run(Pullback(), bars).position(INST) == D(0)


def test_pullback_no_entry_when_regime_fails() -> None:
    bars = [bar(0, 95, 91, 94), bar(1, 96, 92, 95), bar(2, 97, 93, 96)]
    assert run(Pullback(regime=0), bars).position(INST) == D(0)
    assert run(Pullback(regime=-1), bars).position(INST) == D(0)


def test_pullback_short_mirror() -> None:
    bars = [bar(0, 109, 104, 106), bar(1, 108, 104, 105), bar(2, 100, 89, 90)]
    assert run(Pullback(regime=-1, short=True), bars[:2]).position(INST) == D(-1)
    assert run(Pullback(regime=-1, short=True), bars).position(INST) == D(0)
    assert run(Pullback(regime=-1, short=True, allow_short=False), bars[:2]).position(INST) == 0


def test_breakout_long_enters_and_hits_target() -> None:
    # entry 100, stop = pivot low 95, target = 100 + 1.5 * 5 = 107.5
    bars = [bar(0, 101, 99, 100), bar(1, 106, 99, 105), bar(2, 108, 100, 107)]
    assert run(Breakout(), bars[:2]).position(INST) == D(1)
    assert run(Breakout(), bars).position(INST) == D(0)


def test_breakout_stop_exit_and_filters() -> None:
    bars = [bar(0, 101, 99, 100), bar(1, 102, 94, 96)]
    assert run(Breakout(), bars).position(INST) == D(0)
    flat = [bar(0, 101, 99, 100), bar(1, 102, 99, 101)]
    assert run(Breakout(delta="10"), flat).position(INST) == D(0)
    assert run(Breakout(trend=-1, delta="-40", allow_short=False), flat).position(INST) == D(0)


def test_breakout_short_mirror() -> None:
    # entry 100, stop = pivot high 105, target = 100 - 7.5
    bars = [bar(0, 101, 99, 100), bar(1, 103, 98, 99)]
    assert run(Breakout(trend=-1, delta="-40"), bars).position(INST) == D(-1)


def test_real_indicators_smoke() -> None:
    bars = [bar(i, 101 + i, 99 + i, 100 + i) for i in range(30)]
    for s in (
        PrTrendPullbackStrategy(length=3, factor=D(1), require_alligator=False),
        PrVidyaBreakoutStrategy(length=3, factor=D(1), vidya_atr_length=3),
    ):
        run(s, bars)


def obar(i: int, o: str, high: str, low: str, close: str) -> Bar:
    return Bar(INST, T0 + timedelta(days=i), D(o), D(high), D(low), D(close), 100, "1d")


def exit_fill(ctx: SimulatedContext) -> D:
    """Price of the last COMPLETE event (the bracket exit)."""
    complete = [e for e in ctx.events if e.status.value == "complete"]
    assert len(complete) == 2  # entry + exit
    assert complete[-1].price is not None
    return complete[-1].price


PULL = [bar(0, 95, 91, 94), bar(1, 96, 92, 95)]  # entry at 95, stop 80, target 110


def test_pullback_target_fills_at_level_not_close() -> None:
    ctx = run(Pullback(), [*PULL, obar(2, "105", "112", "100", "108")])
    assert ctx.position(INST) == D(0)
    assert exit_fill(ctx) == D(110)


def test_pullback_stop_fills_at_level_and_gap_at_open() -> None:
    ctx = run(Pullback(), [*PULL, obar(2, "95", "96", "78", "85")])
    assert exit_fill(ctx) == D(80)
    ctx = run(Pullback(), [*PULL, obar(2, "70", "72", "68", "71")])
    assert exit_fill(ctx) == D(70)


def test_pullback_stop_wins_when_both_hit() -> None:
    ctx = run(Pullback(), [*PULL, obar(2, "100", "111", "79", "100")])
    assert exit_fill(ctx) == D(80)


def test_pullback_short_target_fills_at_level() -> None:
    bars = [bar(0, 109, 104, 106), bar(1, 108, 104, 105), obar(2, "100", "101", "89", "92")]
    ctx = run(Pullback(regime=-1, short=True), bars)
    assert ctx.position(INST) == D(0)
    assert exit_fill(ctx) == D(90)


def test_breakout_exits_fill_at_levels() -> None:
    entry = bar(0, 101, 99, 100)
    ctx = run(Breakout(), [entry, bar(1, 106, 99, 105), obar(2, "101", "108", "100", "105")])
    assert exit_fill(ctx) == D("107.5")
    ctx = run(Breakout(), [entry, obar(1, "100", "102", "94", "96")])
    assert exit_fill(ctx) == D(95)
    ctx = run(Breakout(trend=-1, delta="-40"), [entry, obar(1, "100", "106", "99", "103")])
    assert exit_fill(ctx) == D(105)
