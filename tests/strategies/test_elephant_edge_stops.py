"""Elephant Edge (EE+) stop-management tests (plan §4).

Covers SL placement beyond the level band + buffer, the `min_sl_atr` minimum
stop-distance skip, the 3R partial booking with breakeven trail, the 5R runner
target, the 6-candle stagnation time-stop, ATR trailing arithmetic (exact
``Decimal`` golden stops), and activation-after-R. Zero floats.
"""

from __future__ import annotations

from decimal import Decimal

from ee_helpers import (
    NIFTY,
    bar,
    drive,
    support_map,
    support_snapshot,
    warmup,
)

from tantra_strategies import (
    ElephantEdgeStrategy,
    OrderSide,
    SimulatedContext,
    StopProtection,
    TrailMode,
)
from tantra_strategies.strategies.elephant_edge import _PositionState

HAMMER = (9, 22, "100", "101", "99", "100.2", 300_000)


def crafted_long(
    strategy: ElephantEdgeStrategy,
    quantity: str = "10",
    r1: str = "105.3",
    r2: str = "108.7",
) -> _PositionState:
    """A deterministic open long: entry 100.2, initial SL 98.5, 1R = 1.7."""
    stop = StopProtection(
        sl=Decimal("98.5"),
        trail=TrailMode.ATR,
        trail_distance=Decimal("2.0"),
        activation_after_r=Decimal("1.0"),
    )
    state = _PositionState(
        instrument=NIFTY,
        side=OrderSide.BUY,
        entry=Decimal("100.2"),
        quantity=Decimal(quantity),
        remaining=Decimal(quantity),
        sl=Decimal("98.5"),
        initial_sl=Decimal("98.5"),
        stop=stop,
        atr_at_entry=Decimal("2.0"),
        r1_price=Decimal(r1),
        r2_price=Decimal(r2),
        highest_close=Decimal("100.2"),
        lowest_close=Decimal("99.0"),
    )
    strategy._position_state[NIFTY] = state
    return state


def warm_atr(strategy: ElephantEdgeStrategy) -> None:
    """Feed 14 constant-TR bars so ``atr`` is exactly 2.0."""
    for warmed in warmup(14):
        strategy.indicators.atr(NIFTY, 14).update(warmed)


def test_sl_placed_beyond_band_plus_buffer() -> None:
    strategy = ElephantEdgeStrategy()
    context = SimulatedContext()
    context.seed_level_map(support_map())
    context.seed_options(support_snapshot())
    strategy.run(context, warmup(22))
    drive(strategy, context, [bar(*HAMMER)])

    assert len(strategy.signal_log) == 1
    state = strategy._position_state[NIFTY]
    assert state.sl == Decimal("98.5")  # band_low 99 - 0.25 x ATR(2.0)
    assert state.initial_sl == Decimal("98.5")
    assert state.sl < Decimal("99")  # strictly beyond the support band
    assert state.stop.trail is TrailMode.ATR
    assert state.stop.trail_distance == Decimal("2.0")
    assert state.stop.activation_after_r == Decimal("1.0")
    # the stop must never rest inside the level band
    assert strategy._level_map is not None
    band_low, band_high = next(
        level for level in strategy._level_map.levels if level.level_id == "s1"
    ).band()
    assert not band_low < state.sl < band_high


def test_min_sl_atr_skip() -> None:
    """A too-tight stop (|entry - sl| < min_sl_atr x ATR) rejects the setup."""
    strategy = ElephantEdgeStrategy(use_oi_walls=False, use_gamma=False, use_max_pain=False)
    context = SimulatedContext()
    context.seed_level_map(support_map(half="0.05"))  # band [99.95, 100.05]
    context.seed_options(support_snapshot())
    strategy.run(context, warmup(22))
    drive(strategy, context, [bar(*HAMMER)])
    # sl = 99.95 - 0.5 = 99.45 -> 1R = 0.75 < min_sl_atr(0.5) x ATR(2.0) = 1.0
    assert not strategy.signal_log
    assert not strategy.position_intent_log


def test_partial_booking_and_breakeven() -> None:
    strategy = ElephantEdgeStrategy()
    warm_atr(strategy)
    context = SimulatedContext()
    strategy._context = context
    state = crafted_long(strategy)

    r1_bar = bar(9, 23, "103", "105.5", "103", "104", 300_000)  # high >= 3R target
    context.feed(r1_bar)
    strategy._manage_open_position(r1_bar)

    assert state.partial_done is True
    assert state.remaining == Decimal("5")  # 50% booked
    assert state.sl == Decimal("100.2")  # breakeven trail on 3R hit
    assert len(strategy.trail_log) >= 1
    assert strategy.trail_log[0].new_stop == Decimal("100.2")
    assert strategy.trail_log[0].old_stop == Decimal("98.5")


def test_runner_target_r2() -> None:
    strategy = ElephantEdgeStrategy()
    warm_atr(strategy)
    context = SimulatedContext()
    strategy._context = context
    state = crafted_long(strategy)
    state.partial_done = True
    state.remaining = Decimal("5")

    r2_bar = bar(9, 24, "107", "109", "107", "108.5", 300_000)  # high >= 5R runner
    context.feed(r2_bar)
    strategy._manage_open_position(r2_bar)

    assert strategy._position_state.get(NIFTY) is None  # runner fully exited
    assert context.position(NIFTY) == Decimal("-5")  # the runner leg was sold


def test_time_stop_scratch_after_six_stagnant_bars() -> None:
    strategy = ElephantEdgeStrategy()
    warm_atr(strategy)
    context = SimulatedContext()
    strategy._context = context
    crafted_long(strategy)

    choppy = [bar(9, 23 + i, "100", "100.4", "99.8", "100", 100_000) for i in range(5)]
    for current in choppy:
        context.feed(current)
        strategy._manage_open_position(current)
    assert strategy._position_state.get(NIFTY) is not None, "no scratch before the limit"

    sixth = bar(9, 28, "100", "100.4", "99.8", "100", 100_000)
    context.feed(sixth)
    strategy._manage_open_position(sixth)
    assert strategy._position_state.get(NIFTY) is None, "6 stagnant bars -> market scratch"


def test_atr_trail_arithmetic_golden() -> None:
    """ATR trail: stop = max(sl, highest_close - 2.0 x ATR) for longs, exact Decimal."""
    strategy = ElephantEdgeStrategy()
    warm_atr(strategy)
    state = crafted_long(strategy, r1="150", r2="200")  # no target interference

    first = bar(9, 23, "102.5", "104", "102.5", "103.5", 300_000)
    strategy._manage_open_position(first)
    # highest_close 103.5 - 2.0 x 2.0 = 99.5 > 98.5
    assert state.sl == Decimal("99.5")
    assert strategy.trail_log[-1].new_stop == Decimal("99.5")
    assert strategy.trail_log[-1].old_stop == Decimal("98.5")

    second = bar(9, 24, "105", "106", "104.5", "105.5", 300_000)
    strategy._manage_open_position(second)
    # highest_close 105.5 - 2.0 x 2.0 = 101.5 > 99.5
    assert state.sl == Decimal("101.5")
    assert strategy.trail_log[-1].new_stop == Decimal("101.5")
    assert strategy.trail_log[-1].old_stop == Decimal("99.5")
    # every journaled stop stays above the initial SL (monotonic trail for longs)
    assert all(update.new_stop >= Decimal("98.5") for update in strategy.trail_log)


def test_activation_after_r() -> None:
    """The TSL stays parked until the trade reaches activation_after_r (1R)."""
    strategy = ElephantEdgeStrategy()
    warm_atr(strategy)
    state = crafted_long(strategy)

    weak = bar(9, 23, "100.5", "101.5", "100.5", "101.3", 300_000)  # excursion 1.1 < 1R
    strategy._manage_open_position(weak)
    assert not strategy.trail_log
    assert state.sl == Decimal("98.5")

    strong = bar(9, 24, "102", "103", "102", "102.6", 300_000)  # excursion 2.4 >= 1R
    strategy._manage_open_position(strong)
    assert len(strategy.trail_log) == 1
    # highest_close 102.6 - 2.0 x 2.0 = 98.6 > 98.5 -> the stop trails one notch
    assert strategy.trail_log[0].new_stop == Decimal("98.6")
