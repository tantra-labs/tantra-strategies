"""Elephant Edge (EE+) full mini-session integration (plan §0 / §8).

Runs the complete strategy against ``SimulatedContext`` with a seeded level
map and option-chain snapshot: warm-up bars, a confirmed hammer reversal at the
support level, fills, the 3R partial + breakeven trail, the 5R runner exit, and
end-of-session square-off — plus SL-breach and 6-candle time-stop exits. Asserts
at least one ``StopUpdate`` journaled on the winning run. Zero floats.
"""

from __future__ import annotations

from decimal import Decimal

from strategies.ee_helpers import bar, support_map, support_snapshot, warmup

from tantra_strategies import (
    ElephantEdgeStrategy,
    OrderStatus,
    SimulatedContext,
)

NIFTY = "NSE:NIFTY50-INDEX"
HAMMER = (9, 22, "100", "101", "99", "100.2", 300_000)


def seeded_context() -> tuple[SimulatedContext, ElephantEdgeStrategy]:
    context = SimulatedContext()
    context.seed_level_map(support_map())
    context.seed_options(support_snapshot())
    return context, ElephantEdgeStrategy()


def test_winning_run_emits_fills_trails_and_squares_off() -> None:
    context, strategy = seeded_context()
    bars = warmup(22)  # 09:00..09:21, ATR exactly 2.0
    bars.append(bar(*HAMMER))  # 09:22: hammer reversal at support
    rally = [
        bar(9, 23, "100.5", "102", "100.5", "101.5", 200_000),
        bar(9, 24, "101.5", "103", "101.5", "102.5", 200_000),
        bar(9, 25, "102.5", "104.5", "102.5", "103.5", 200_000),
        bar(9, 26, "103.5", "105.5", "103.5", "104.5", 200_000),  # 3R partial + breakeven
        bar(9, 27, "104.5", "106.5", "104.5", "105.5", 200_000),
        bar(9, 28, "105.5", "107.5", "105.5", "106.5", 200_000),
        bar(9, 29, "106.5", "108.7", "106.5", "107.5", 200_000),  # 5R runner exit
        bar(9, 30, "107.5", "108", "107", "107.5", 100_000),
    ]
    strategy.run(context, bars + rally)

    # a single confirmed signal at the seeded support level
    assert len(strategy.signal_log) == 1
    signal = strategy.signal_log[0]
    assert signal.ref_levels == ("s1",)
    assert signal.confidence == Decimal("88")  # score 4 x trigger quality 22

    # fills: entry, partial, runner -> position flat at the end of the run
    assert context.position(NIFTY) == 0
    fills = [event for event in context.events if event.status is OrderStatus.COMPLETE]
    assert len(fills) >= 3

    # plan §5 positioning: risk 5000 / 1.7R, capped at 25% of equity notional
    intent = strategy.position_intent_log[0]
    assert intent.quantity == Decimal("2495")
    assert intent.stop == Decimal("98.5")
    assert intent.target == Decimal("108.7")  # entry + 5R
    assert intent.risk_amount == Decimal("5000")
    assert intent.entry == Decimal("100.2")

    # 3R partial books half, runner exits the rest
    partial = next(request for request in context.orders if request.tag == "ee.partial")
    assert partial.quantity == Decimal("1247")  # floor(2495 / 2)
    runner = next(request for request in context.orders if request.tag == "ee.target_r2")
    assert runner.quantity == Decimal("1248")

    # trailing behavior: ATR trail activates on the way up, breakeven on the 3R
    # hit, then the runner leg trails above breakeven
    assert len(strategy.trail_log) >= 2
    assert any(update.new_stop == Decimal("100.2") for update in strategy.trail_log)  # breakeven
    breakeven_index = next(
        index
        for index, update in enumerate(strategy.trail_log)
        if update.new_stop == Decimal("100.2")
    )
    assert all(
        update.new_stop > Decimal("100.2") for update in strategy.trail_log[breakeven_index + 1 :]
    )
    assert strategy._position_state.get(NIFTY) is None


def test_stop_loss_exits_on_breach() -> None:
    context, strategy = seeded_context()
    bars = warmup(22)
    bars.append(bar(*HAMMER))  # entry long, SL 98.5
    bars.append(bar(9, 23, "99.5", "100", "98", "98.8", 100_000))  # low 98 breaches 98.5
    strategy.run(context, bars)

    assert context.position(NIFTY) == 0
    assert any(request.tag == "ee.stop" for request in context.orders)


def test_time_stop_exits_stagnant_position() -> None:
    context, strategy = seeded_context()
    bars = warmup(22)
    bars.append(bar(*HAMMER))  # entry long, SL 98.5
    for i in range(6):
        bars.append(bar(9, 23 + i, "100", "100.4", "99.8", "100", 100_000))
    strategy.run(context, bars)

    assert context.position(NIFTY) == 0
    assert any(request.tag == "ee.scratch" for request in context.orders)


def test_square_off_at_end_of_window() -> None:
    context = SimulatedContext()
    context.seed_level_map(support_map())
    context.seed_options(support_snapshot())
    strategy = ElephantEdgeStrategy(
        square_off_time="10:00",
        entry_window=("09:20", "09:45"),
        max_stagnant_bars=15,
    )
    bars = warmup(22)
    bars.append(bar(*HAMMER))
    bars.extend(
        bar(9, minute, "100.8", "101.4", "100.6", "101.2", 100_000) for minute in range(23, 60)
    )
    bars.append(bar(10, 0, "100.8", "101.4", "100.6", "101.2", 100_000))
    strategy.run(context, bars)

    assert context.position(NIFTY) == 0
    assert any(request.tag == "ee.squareoff" for request in context.orders)
