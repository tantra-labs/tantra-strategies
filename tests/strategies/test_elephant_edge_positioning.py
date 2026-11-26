"""Elephant Edge (EE+) positioning tests (plan §5).

Covers risk-based quantity, whole-lot rounding down, the `max_position_fraction`
notional cap, alternate-mode opposite-side switching, and end-of-window
square-off. Every quantity is an exact ``Decimal``.
"""

from __future__ import annotations

from decimal import Decimal

from ee_helpers import bar, support_map, support_snapshot, warmup

from tantra_strategies import (
    ElephantEdgeStrategy,
    OrderSide,
    SignalKind,
    SimulatedContext,
)

NIFTY = "NSE:NIFTY50-INDEX"
HAMMER = (9, 22, "100", "101", "99", "100.2", 300_000)


def test_risk_based_quantity() -> None:
    strategy = ElephantEdgeStrategy(
        account_equity="1000000",
        risk_per_trade_pct="0.5",
        max_position_fraction="0.25",
        lot_size="1",
    )
    # risk budget = 0.5% of 1_000_000 = 5000; 5000 / 50R = 100 units
    assert strategy._position_size(Decimal("100"), Decimal("50")) == Decimal("100")


def test_lot_rounding_down() -> None:
    strategy = ElephantEdgeStrategy(
        account_equity="1000000",
        risk_per_trade_pct="0.5",
        max_position_fraction="0.25",
        lot_size="25",
    )
    # 5000 / 20.8 = 240.38... -> floor(240.38 / 25) = 9 lots -> 225 units
    assert strategy._position_size(Decimal("100"), Decimal("20.8")) == Decimal("225")


def test_max_position_fraction_cap() -> None:
    strategy = ElephantEdgeStrategy(
        account_equity="1000000",
        risk_per_trade_pct="0.5",
        max_position_fraction="0.25",
        lot_size="1",
    )
    # risk-based 5000/1 = 5000 -> notional 500000 > 250000 cap -> floor(250000/100) = 2500
    assert strategy._position_size(Decimal("100"), Decimal("1")) == Decimal("2500")


def test_cap_rounds_down_to_whole_lots() -> None:
    strategy = ElephantEdgeStrategy(
        account_equity="1000000",
        risk_per_trade_pct="0.5",
        max_position_fraction="0.25",
        lot_size="25",
    )
    # capped at floor(250000/100) = 2500, rounded down to 25-lot: floor(2500/25) x 25 = 2500
    assert strategy._position_size(Decimal("100"), Decimal("1")) == Decimal("2500")


def test_alternate_mode_side_switching() -> None:
    strategy = ElephantEdgeStrategy(alternate_mode=True)
    context = SimulatedContext()
    context.seed_level_map(support_map())
    context.seed_options(support_snapshot())
    strategy.run(context, warmup(22))  # ATR 2.0 exactly, volume average ready

    assert strategy._level_map is not None
    level = next(level for level in strategy._level_map.levels if level.level_id == "s1")
    trigger = bar(*HAMMER)
    context.feed(trigger)

    # last trade long -> the next long setup is blocked by alternate mode
    strategy._last_trade_side = OrderSide.BUY
    assert strategy._emit_signal(trigger, level, SignalKind.REVERSAL, OrderSide.BUY) is None
    assert not strategy.signal_log

    # last trade short -> long is the required opposite side and goes through
    strategy._last_trade_side = OrderSide.SELL
    signal = strategy._emit_signal(trigger, level, SignalKind.REVERSAL, OrderSide.BUY)
    assert signal is not None
    assert signal.side is OrderSide.BUY
    assert len(strategy.signal_log) == 1
    assert strategy._last_trade_side is OrderSide.BUY


def test_square_off_at_window_end() -> None:
    strategy = ElephantEdgeStrategy(
        square_off_time="10:00",
        entry_window=("09:20", "09:45"),
        max_stagnant_bars=15,
    )
    context = SimulatedContext()
    context.seed_level_map(support_map())
    context.seed_options(support_snapshot())

    bars = warmup(22)  # 09:00..09:21 warm-up
    bars.append(bar(*HAMMER))  # 09:22 entry
    # drift above 0.5R (no time-stop) but below 3R (no partial) until square-off
    bars.extend(
        bar(9, minute, "100.8", "101.4", "100.6", "101.2", 100_000) for minute in range(23, 60)
    )
    bars.append(bar(10, 0, "100.8", "101.4", "100.6", "101.2", 100_000))  # 10:00 square-off
    strategy.run(context, bars)

    assert len(strategy.signal_log) == 1
    assert context.position(NIFTY) == 0, "position must square off at the window end"
    assert any(request.tag == "ee.squareoff" for request in context.orders)
