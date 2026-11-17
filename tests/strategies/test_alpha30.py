"""Alpha30Factor: ROC ranking, top-N selection, deterministic order streams."""

from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import basket_bars

from tantra_strategies import Alpha30Factor, OrderSide, Parameter, SimulatedContext

MEMBERS = ["NSE:AAA", "NSE:BBB", "NSE:CCC"]


def _momentum_basket() -> list:
    """AAA rallies, BBB is flat, CCC falls: rank AAA > BBB > CCC by 3-day ROC."""
    return basket_bars(
        MEMBERS,
        [
            [
                Decimal(100 + day * 5 if i == 0 else 100 if i == 1 else 100 - day * 5)
                for i in range(3)
            ]
            for day in range(10)
        ],
    )


def _run(**overrides: object) -> SimulatedContext:
    context = SimulatedContext()
    params = {
        "instruments": ", ".join(MEMBERS),
        "lookback": 3,
        "top_n": 2,
        "rebalance_period": 2,
        "capital": 300_000,
    }
    strategy = Alpha30Factor(**{**params, **overrides})
    strategy.run(context, _momentum_basket())
    return context


def _trace(context: SimulatedContext) -> list[tuple[object, ...]]:
    return [
        (event.instrument, event.side.value, str(event.quantity), str(event.price))
        for event in context.events
    ]


def test_parameters_are_declarative_and_round_trip() -> None:
    strategy = Alpha30Factor()
    declared = vars(type(strategy))
    for name in ("instruments", "lookback", "top_n", "rebalance_period", "capital"):
        assert isinstance(declared[name], Parameter)
    assert strategy.lookback == 30
    assert strategy.top_n == 10

    overridden = Alpha30Factor(lookback=10, top_n=3, capital=100_000)
    assert overridden.lookback == 10
    assert overridden.top_n == 3
    assert overridden.capital == 100_000


def test_parameter_bounds_are_enforced() -> None:
    with pytest.raises(ValueError, match="below minimum"):
        Alpha30Factor(lookback=1)
    with pytest.raises(ValueError, match="above maximum"):
        Alpha30Factor(top_n=100)


def test_deterministic_order_streams() -> None:
    first = _run()
    second = _run()
    assert _trace(first) == _trace(second)
    assert len(first.events) > 0


def test_longs_top_n_and_exits_the_rest() -> None:
    context = _run()
    # AAA and BBB (top two by ROC) are held; the falling CCC is left flat.
    assert context.position("NSE:AAA") > 0
    assert context.position("NSE:BBB") > 0
    assert context.position("NSE:CCC") == 0


def test_trims_overweight_selection_on_rebalance() -> None:
    context = _run()
    sells = [e for e in context.events if e.side is OrderSide.SELL]
    assert sells, "a member whose target share shrank should be trimmed"


def test_holds_the_whole_basket_when_top_n_covers_everyone() -> None:
    context = _run(top_n=3)
    assert all(context.position(member) > 0 for member in MEMBERS)
