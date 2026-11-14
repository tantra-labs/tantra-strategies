"""Basket allocation optimizer and run loop (gaps 0004 + 0005)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from tantra_strategies import BasketManifest
from tantra_strategies.manifest.basket import MemberStrategyRef, optimize_allocations
from tantra_strategies.manifest.basket_run import (
    RiskBudgetViolation,
    realized_pnl,
    resolve_manifest,
    run_basket,
)
from tantra_strategies.sdk.bar import Bar
from tantra_strategies.sdk.order import OrderEvent, OrderSide, OrderStatus

ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST_DIR = ROOT / "manifests"
BASKET_DIR = MANIFEST_DIR / "baskets"

CLOSES = [Decimal(100) + Decimal(i) for i in range(30)] + [
    Decimal(130) - Decimal(i) for i in range(15)
]


def make_bars(closes: list[Decimal], instrument: str) -> list[Bar]:
    """Deterministic daily bars with OHLC == close (conftest pattern)."""
    return [
        Bar(
            instrument=instrument,
            ts=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=100_000,
            interval="1d",
        )
        for i, close in enumerate(closes)
    ]


def base_basket() -> dict[str, object]:
    """Structurally valid two-member basket with equal weights (0.5 / 0.5)."""
    return {
        "basket_name": "turtle_twap_basket",
        "version": "0.1.0",
        "combined_capital": 1000000,
        "member_strategies": [
            {"name": "turtle_breakout", "version": "0.1.0", "weight": 0.5},
            {"name": "twap_slicer", "version": "0.1.0", "weight": 0.5},
        ],
    }


def test_optimize_allocations_no_caps_uses_naive_weights() -> None:
    basket = BasketManifest.model_validate(base_basket())
    assert optimize_allocations(basket) == [Decimal("500000.00"), Decimal("500000.00")]


def test_optimize_allocations_max_position_fraction_caps_total() -> None:
    basket = BasketManifest.model_validate(
        {**base_basket(), "risk_budget": {"max_position_fraction": 0.25}}
    )
    assert optimize_allocations(basket) == [Decimal("125000.00"), Decimal("125000.00")]


def test_optimize_allocations_per_member_cap() -> None:
    basket = BasketManifest.model_validate(
        {
            **base_basket(),
            "member_strategies": [
                {"name": "turtle_breakout", "version": "0.1.0", "weight": 0.8},
                {"name": "twap_slicer", "version": "0.1.0", "weight": 0.2},
            ],
            "risk_budget": {"max_position_fraction": 0.5},
        }
    )
    assert optimize_allocations(basket) == [Decimal("400000.00"), Decimal("100000.00")]


def test_optimize_allocations_max_loss_bounds_deployment() -> None:
    basket = BasketManifest.model_validate({**base_basket(), "risk_budget": {"max_loss": 100000}})
    assert optimize_allocations(basket) == [Decimal("50000.00"), Decimal("50000.00")]


def test_realized_pnl_average_cost() -> None:
    buy = OrderEvent(
        order_id="1",
        instrument="NSE:NIFTY50-INDEX",
        side=OrderSide.BUY,
        status=OrderStatus.COMPLETE,
        quantity=Decimal(10),
        filled_quantity=Decimal(10),
        price=Decimal(100),
    )
    sell = OrderEvent(
        order_id="2",
        instrument="NSE:NIFTY50-INDEX",
        side=OrderSide.SELL,
        status=OrderStatus.COMPLETE,
        quantity=Decimal(10),
        filled_quantity=Decimal(10),
        price=Decimal(110),
    )
    assert realized_pnl([buy, sell]) == Decimal("100")
    loss_sell = OrderEvent(
        order_id="3",
        instrument="NSE:NIFTY50-INDEX",
        side=OrderSide.SELL,
        status=OrderStatus.COMPLETE,
        quantity=Decimal(10),
        filled_quantity=Decimal(10),
        price=Decimal(90),
    )
    assert realized_pnl([buy, loss_sell]) == Decimal("-100")


def test_turtle_twap_basket_runs_deterministically() -> None:
    basket = BasketManifest.load_toml(BASKET_DIR / "turtle_twap_basket.toml")
    bars = {
        "NSE:NIFTY50-INDEX": make_bars(CLOSES, "NSE:NIFTY50-INDEX"),
        "NSE:RELIANCE-EQ": make_bars(CLOSES, "NSE:RELIANCE-EQ"),
    }
    result1 = run_basket(basket, bars)
    assert result1.allocations == {
        "turtle_breakout": Decimal("50000.00"),
        "twap_slicer": Decimal("50000.00"),
    }
    assert len(result1.runs["turtle_breakout"].events) >= 1
    assert len(result1.runs["twap_slicer"].events) >= 1
    assert result1.total_position_fraction <= Decimal("0.25")
    result2 = run_basket(basket, bars)
    assert result1.runs["turtle_breakout"].events == result2.runs["turtle_breakout"].events
    assert result1.runs["twap_slicer"].events == result2.runs["twap_slicer"].events


def test_risk_budget_violation_when_position_fraction_exceeds_cap() -> None:
    basket = BasketManifest.load_toml(BASKET_DIR / "turtle_twap_basket.toml")
    bars = {
        "NSE:NIFTY50-INDEX": make_bars(CLOSES, "NSE:NIFTY50-INDEX"),
        "NSE:RELIANCE-EQ": make_bars(CLOSES, "NSE:RELIANCE-EQ"),
    }
    # The turtle ``quantity`` Parameter caps at 1000, too small to breach the
    # 0.25 position-fraction cap on a 1M basket; inflate the twap parent order
    # instead (max 1,000,000 units -> ~115M notional -> fraction ~115 >> 0.25).
    with pytest.raises(RiskBudgetViolation):
        run_basket(
            basket,
            bars,
            strategy_overrides={"twap_slicer": {"total_quantity": 1000000}},
        )


def test_resolve_manifest_missing_raises() -> None:
    member = MemberStrategyRef(name="nope", version="0.1.0", weight=Decimal("1"))
    with pytest.raises(KeyError):
        resolve_manifest(member, ROOT / "manifests" / "strategies")
