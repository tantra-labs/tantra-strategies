"""EqualWeight: declarative parameters, equal-weight targets, deterministic streams."""

from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import basket_bars, make_bars

from tantra_strategies import EqualWeight, OrderSide, Parameter, SimulatedContext

MEMBERS = ["NSE:AAA", "NSE:BBB", "NSE:CCC"]


def _rising_basket() -> list:
    """Three members drifting higher session by session (~1 point/day)."""
    return basket_bars(MEMBERS, [[Decimal(100 + day + i) for i in range(3)] for day in range(12)])


def _run(
    *, capital: int = 300_000, rebalance_period: int = 3, bars: list | None = None
) -> SimulatedContext:
    context = SimulatedContext()
    strategy = EqualWeight(
        instruments=", ".join(MEMBERS),
        capital=capital,
        rebalance_period=rebalance_period,
    )
    strategy.run(context, bars or _rising_basket())
    return context


def _trace(context: SimulatedContext) -> list[tuple[object, ...]]:
    return [
        (event.instrument, event.side.value, str(event.quantity), str(event.price))
        for event in context.events
    ]


def test_parameters_are_declarative_and_round_trip() -> None:
    strategy = EqualWeight()
    declared = vars(type(strategy))
    for name in ("instruments", "rebalance_period", "capital"):
        assert isinstance(declared[name], Parameter)
    assert strategy.rebalance_period == 5
    assert strategy.capital == 1_000_000

    overridden = EqualWeight(instruments="NSE:X", rebalance_period=10, capital=50_000)
    assert overridden.rebalance_period == 10
    assert overridden.capital == 50_000
    assert overridden.instruments == "NSE:X"


def test_parameter_bounds_are_enforced() -> None:
    with pytest.raises(ValueError, match="below minimum"):
        EqualWeight(rebalance_period=0)
    with pytest.raises(ValueError, match="above maximum"):
        EqualWeight(capital=10**11)


def test_empty_basket_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty 'instruments'"):
        EqualWeight(instruments=" , ").run(SimulatedContext(), [])


def test_deterministic_order_streams() -> None:
    first = _run()
    second = _run()
    assert _trace(first) == _trace(second)
    assert len(first.events) > 0


def test_rebalances_to_equal_weight_targets() -> None:
    context = _run(capital=300_000)
    positions = {member: context.position(member) for member in MEMBERS}
    assert all(position > 0 for position in positions.values())
    # Equal weight: positions differ only by floor-to-whole-share price ticks.
    spread = max(positions.values()) - min(positions.values())
    assert spread < 100


def test_sells_when_a_member_rallies() -> None:
    # Member AAA doubles; later rebalances trim it back towards the target.
    closes = [
        [Decimal(100 + day * 2) if i == 0 else Decimal(100 + day) for i in range(3)]
        for day in range(12)
    ]
    context = _run(capital=300_000, rebalance_period=2, bars=basket_bars(MEMBERS, closes))
    sells = [e for e in context.events if e.side is OrderSide.SELL]
    assert sells, "a rallying member should be trimmed by a later rebalance"


def test_flat_market_buys_once_then_holds() -> None:
    flat = basket_bars(MEMBERS, [[Decimal(100)] * 3 for _ in range(6)])
    context = _run(capital=300_000, rebalance_period=3, bars=flat)
    # Two rebalances on flat prices: the first buys every member, the second has zero deltas.
    assert len(context.orders) == len(MEMBERS)
    assert all(context.position(member) == Decimal(1000) for member in MEMBERS)


def test_single_instrument_default_trades() -> None:
    context = SimulatedContext()
    strategy = EqualWeight(capital=10_000)
    strategy.run(context, make_bars([Decimal(100)] * 6))
    assert context.position("NSE:NIFTY50-INDEX") == Decimal(100)
