"""Elephant Edge (EE+) signal-generation tests (plan §3).

Covers trigger candles (hammer / engulfing / shooting-star / marubozu), noise
and outlier rejection, the volume participation filter, Plus-Two breakout
confirmation, the ΔOI trap rejection, max-trades-per-day discipline, the entry
window guard, and no-duplicate-level discipline. Every assertion is exact
``Decimal``; zero floats.
"""

from __future__ import annotations

from decimal import Decimal

from ee_helpers import (
    NIFTY,
    bar,
    resistance_map,
    resistance_snapshot,
    support_map,
    support_snapshot,
    warmup,
)

from tantra_strategies import (
    ElephantEdgeStrategy,
    OrderSide,
    SignalKind,
    SimulatedContext,
)

# Standard deterministic support-reversal trigger bar (TR = 2.0 keeps ATR exact).
HAMMER = (9, 22, "100", "101", "99", "100.2", 300_000)


def drive(strategy: ElephantEdgeStrategy, context: SimulatedContext, bars) -> None:
    """Feed bars one at a time exactly as ``SimulatedContext.run`` would."""
    for current in bars:
        context.feed(current)
        for event in context._drain_outbox():
            strategy.on_order_event(event)
        strategy.on_bar(current)


def seeded_support(
    warmup_n: int = 22, **overrides
) -> tuple[ElephantEdgeStrategy, SimulatedContext]:
    strategy = ElephantEdgeStrategy(**overrides)
    context = SimulatedContext()
    context.seed_level_map(support_map())
    context.seed_options(support_snapshot())
    strategy.run(context, warmup(warmup_n))
    return strategy, context


def test_hammer_reversal_emits_signal() -> None:
    strategy, context = seeded_support()
    assert not strategy.signal_log
    drive(strategy, context, [bar(*HAMMER)])

    assert len(strategy.signal_log) == 1
    signal = strategy.signal_log[0]
    assert signal.side is OrderSide.BUY
    assert signal.kind is SignalKind.REVERSAL
    assert signal.ref_levels == ("s1",)
    assert signal.confidence == Decimal("88")  # score 4 x quality 22 (volume surge)
    intent = strategy.position_intent_log[0]
    assert intent.entry == Decimal("100.2")
    assert intent.stop == Decimal("98.5")  # band_low 99 - 0.25 x ATR(2.0)
    assert intent.risk_amount == Decimal("5000")  # 0.5% of 1_000_000 equity
    # risk qty 5000 / 1.7R = 2941.17..., capped by 25% notional: floor(250000 / 100.2)
    assert intent.quantity == Decimal("2495")
    assert context.position(NIFTY) == Decimal("2495")


def test_bullish_engulfing_reversal_emits_signal() -> None:
    strategy, context = seeded_support(21)
    previous = bar(9, 21, "100.3", "100.6", "99.7", "99.9")  # bearish
    engulfing = bar(9, 22, "99.8", "100.8", "99.8", "100.5", 300_000)  # bullish engulfing
    drive(strategy, context, [previous, engulfing])

    assert len(strategy.signal_log) == 1
    signal = strategy.signal_log[0]
    assert signal.side is OrderSide.BUY
    assert signal.kind is SignalKind.REVERSAL
    assert context.position(NIFTY) > 0


def test_shooting_star_reversal_short() -> None:
    strategy = ElephantEdgeStrategy()
    context = SimulatedContext()
    context.seed_level_map(resistance_map(half="1.0"))
    context.seed_options(resistance_snapshot(delta="200"))  # building call wall -> reversal OK
    strategy.run(context, warmup(22, base="104.8", half_range="0.5"))
    drive(strategy, context, [bar(9, 22, "105.1", "105.5", "104.6", "104.9", 300_000)])

    assert len(strategy.signal_log) == 1
    signal = strategy.signal_log[0]
    assert signal.side is OrderSide.SELL
    assert signal.kind is SignalKind.REVERSAL
    assert context.position(NIFTY) < 0


def test_noise_candle_rejected() -> None:
    strategy, context = seeded_support()
    noise = bar(9, 22, "100.05", "100.2", "99.85", "100.1", 300_000)  # range 0.35 < 0.2 x ATR
    drive(strategy, context, [noise])
    assert not strategy.signal_log
    assert context.position(NIFTY) == 0


def test_outlier_candle_rejected() -> None:
    strategy, context = seeded_support()
    outlier = bar(9, 22, "100", "110", "95", "100.2", 300_000)  # range 15 > 4 x ATR
    drive(strategy, context, [outlier])
    assert not strategy.signal_log
    assert context.position(NIFTY) == 0


def test_volume_participation_filter() -> None:
    strategy, context = seeded_support()
    weak = bar(9, 22, "100", "101", "99", "100.2", 100_000)  # 1.0x average
    drive(strategy, context, [weak])
    assert not strategy.signal_log

    strong = bar(9, 23, "100", "101", "99", "100.2", 300_000)  # 3.0x average
    drive(strategy, context, [strong])
    assert len(strategy.signal_log) == 1
    assert context.position(NIFTY) > 0


def test_plus_two_breakout_confirmation() -> None:
    strategy = ElephantEdgeStrategy(confirm_bars_breakout=2)
    context = SimulatedContext()
    context.seed_level_map(resistance_map(price="105", half="0.15"))
    context.seed_options(resistance_snapshot())  # short-covering call wall
    strategy.run(context, warmup(22, base="104.8", half_range="0.5"))

    trigger = bar(9, 22, "104.6", "106.2", "104.5", "105.7", 100_000)  # marubozu through band
    follow_one = bar(
        9, 23, "105.8", "106.1", "105.7", "106.0", 100_000
    )  # sustains, no trigger shape
    follow_two = bar(9, 24, "106.0", "106.4", "105.9", "106.3", 200_000)  # 2nd follow-through

    drive(strategy, context, [trigger])
    assert not strategy.signal_log, "a 1-bar breakout must not emit before Plus-Two"

    drive(strategy, context, [follow_one])
    assert not strategy.signal_log, "one follow-through bar is not enough with confirm=2"

    drive(strategy, context, [follow_two])
    assert len(strategy.signal_log) == 1
    signal = strategy.signal_log[0]
    assert signal.kind is SignalKind.BREAKOUT
    assert signal.side is OrderSide.BUY
    assert signal.ref_levels == ("r1",)
    assert context.position(NIFTY) > 0


def test_delta_oi_trap_rejects_building_breakout() -> None:
    strategy = ElephantEdgeStrategy(confirm_bars_breakout=0)
    context = SimulatedContext()
    context.seed_level_map(resistance_map(price="105", half="0.15"))
    context.seed_options(resistance_snapshot(delta="300"))  # building at the broken strike = trap
    strategy.run(context, warmup(22, base="104.8", half_range="0.5"))
    trigger = bar(9, 22, "104.6", "106.2", "104.5", "105.7", 300_000)

    drive(strategy, context, [trigger])
    assert not strategy.signal_log, "a breakout into building ΔOI must be rejected"
    assert not strategy._pending_breakouts
    assert context.position(NIFTY) == 0


def test_max_trades_per_day_discipline() -> None:
    strategy, context = seeded_support(22, max_trades_per_day=2)
    strategy._trades_today = 2
    drive(strategy, context, [bar(*HAMMER)])
    assert not strategy.signal_log, "trade budget exhausted: no new entries"

    strategy._trades_today = 1
    drive(strategy, context, [bar(9, 23, "100", "101", "99", "100.2", 300_000)])
    assert len(strategy.signal_log) == 1
    assert strategy._trades_today == 2


def test_entry_window_guard() -> None:
    strategy, _context = seeded_support(22)
    assert not strategy._in_entry_window(bar(9, 10, "100", "101", "99", "100"))
    assert strategy._in_entry_window(bar(12, 0, "100", "101", "99", "100"))
    assert not strategy._in_entry_window(bar(14, 35, "100", "101", "99", "100"))
    assert not strategy._near_square_off(bar(12, 0, "100", "101", "99", "100"))
    assert strategy._near_square_off(bar(14, 45, "100", "101", "99", "100"))

    # Full-flow: indicators are warm before the window opens, so the guard alone
    # must block a 09:10 hammer and allow the 09:21 one.
    warm_strategy, warm_context = seeded_support(0)
    pre = warmup(25, hour=8, minute=35)  # 08:35..08:59: ATR + volume warm
    pre += [bar(9, hour, "100", "101", "99", "100") for hour in range(9)]  # 09:00..09:08
    drive(warm_strategy, warm_context, pre)
    early = bar(9, 10, "100", "101", "99", "100.2", 300_000)
    drive(warm_strategy, warm_context, [early])
    assert not warm_strategy.signal_log, "09:10 is before the 09:20 entry window"
    drive(warm_strategy, warm_context, [bar(9, 21, "100", "101", "99", "100.2", 300_000)])
    assert len(warm_strategy.signal_log) == 1


def test_no_duplicate_level() -> None:
    strategy, context = seeded_support(22, target_r1="1.5", target_r2="3.0")
    drive(strategy, context, [bar(*HAMMER)])  # entry at s1
    assert len(strategy.signal_log) == 1
    rally = [
        bar(9, 23, "100.5", "103", "100.5", "102.5", 200_000),  # hits 1.5R: partial + breakeven
        bar(9, 24, "102.5", "104", "102.5", "103.5", 200_000),
        bar(9, 25, "103.5", "106", "103.5", "105.0", 200_000),  # hits 3R runner: flat
    ]
    drive(strategy, context, rally)
    assert context.position(NIFTY) == 0
    drive(strategy, context, [bar(9, 26, "100", "101", "99", "100.2", 300_000)])
    assert len(strategy.signal_log) == 1, "the same level must not be traded twice in a day"
