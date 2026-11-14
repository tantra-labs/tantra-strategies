"""Composite smart-money signal: pure per-leg scoring + strategy wiring."""

from __future__ import annotations

from decimal import Decimal

from conftest import make_bars

from tantra_strategies import SimulatedContext
from tantra_strategies.strategies.composite_signal import (
    BlockPrint,
    CompositeSignal,
    CompositeSignalConfig,
    CompositeSignalStrategy,
    DeliveryObservation,
    InstitutionalFlow,
    OiBuildupSnapshot,
    compute_composite_signal,
)

INSTRUMENT = "NSE:RELIANCE-EQ"


def cfg(**overrides: object) -> CompositeSignalConfig:
    values: dict[str, object] = dict(
        delivery_lookback=20,
        delivery_spike_multiple=Decimal("1.5"),
        delivery_min_pct=Decimal("40"),
        oi_min_change_pct=Decimal("2"),
        price_min_change_pct=Decimal("1"),
        block_min_qty=Decimal("50000"),
        dii_heavy_sell=Decimal("-500000000"),
        regime_discount=Decimal("0.5"),
    )
    values.update(overrides)
    return CompositeSignalConfig(**values)


def score(
    delivery: list[DeliveryObservation] | None = None,
    filings: list[str] | None = None,
    blocks: list[BlockPrint] | None = None,
    oi: OiBuildupSnapshot | None = None,
    flows: list[InstitutionalFlow] | None = None,
    **overrides: object,
) -> CompositeSignal:
    return compute_composite_signal(
        cfg(**overrides),
        delivery=delivery or [],
        filings=filings or [],
        blocks=blocks or [],
        oi=oi,
        flows=flows or [],
    )


def delivery_history(pct: Decimal, traded_qty: Decimal) -> list[DeliveryObservation]:
    return [
        DeliveryObservation(
            date=f"2026-11-{day:02d}",
            traded_qty=traded_qty,
            delivered_qty=Decimal(0),
            delivery_pct=pct,
        )
        for day in range(1, 6)
    ]


def day(pct: Decimal, traded_qty: Decimal) -> DeliveryObservation:
    return DeliveryObservation(
        date="2026-11-06",
        traded_qty=traded_qty,
        delivered_qty=Decimal(0),
        delivery_pct=pct,
    )


def make_oi(
    classification: str, oi_change: str = "6.5", price_change: str = "2.1"
) -> OiBuildupSnapshot:
    return OiBuildupSnapshot(
        open_interest=Decimal("1250000"),
        oi_change_pct=Decimal(oi_change),
        price_change_pct=Decimal(price_change),
        classification=classification,
    )


def test_delivery_leg_spike_scores_accumulation() -> None:
    # Trailing average activity = 50% * 1_000_000; latest 80% * 2_000_000 is
    # well above the 1.5x spike multiple → a confirmed delivery spike.
    delivery = delivery_history(Decimal("50"), Decimal("1000000"))
    delivery.append(day(Decimal("80"), Decimal("2000000")))
    signal = score(delivery=delivery)
    assert signal.delivery_leg == Decimal(1)
    assert signal.total >= Decimal(1)


def test_delivery_leg_low_percentage_is_churn() -> None:
    delivery = delivery_history(Decimal("50"), Decimal("1000000"))
    delivery.append(day(Decimal("30"), Decimal("1000000")))
    signal = score(delivery=delivery)
    assert signal.delivery_leg == Decimal(-1)


def test_delivery_leg_neutral_with_too_few_observations() -> None:
    signal = score(delivery=[day(Decimal("80"), Decimal("1000000"))])
    assert signal.delivery_leg == Decimal(0)


def test_filings_leg_scoring() -> None:
    assert score().filings_leg == Decimal(0)
    assert score(filings=["quarterly_result"]).filings_leg == Decimal(0)
    assert score(filings=["shareholding"]).filings_leg == Decimal("0.5")
    both = score(filings=["shareholding", "insider_trade"]).filings_leg
    assert both == Decimal(1)


def test_block_leg_scoring() -> None:
    buy = score(blocks=[BlockPrint(side="buy", quantity=Decimal("100000"))])
    assert buy.block_leg == Decimal(1)
    sell = score(blocks=[BlockPrint(side="sell", quantity=Decimal("200000"))])
    assert sell.block_leg == Decimal(-1)
    noise = score(blocks=[BlockPrint(side="buy", quantity=Decimal("1000"))])
    assert noise.block_leg == Decimal(0)


def test_oi_leg_four_quadrants() -> None:
    def leg(classification: str) -> Decimal:
        return score(oi=make_oi(classification)).oi_leg

    assert leg("long_buildup") == Decimal(1)
    assert leg("short_covering") == Decimal("0.5")
    assert leg("long_unwinding") == Decimal("-0.5")
    assert leg("short_buildup") == Decimal(-1)
    assert leg("bogus_class") == Decimal(0)


def test_oi_leg_neutral_on_small_moves() -> None:
    small = make_oi("long_buildup", oi_change="0.5", price_change="0.1")
    assert score(oi=small).oi_leg == Decimal(0)


def test_regime_gate_discounts_when_dii_heavy_sell() -> None:
    heavy_sell = [InstitutionalFlow(category="dii", net_value=Decimal("-1000000000"))]
    signal = score(flows=heavy_sell)
    assert signal.regime_adjustment == Decimal("-0.5")

    benign = [InstitutionalFlow(category="dii", net_value=Decimal("50000000"))]
    assert score(flows=benign).regime_adjustment == Decimal(0)


def test_composite_verdict_accumulation() -> None:
    delivery = delivery_history(Decimal("50"), Decimal("1000000"))
    delivery.append(day(Decimal("80"), Decimal("2000000")))
    signal = score(
        delivery=delivery,
        filings=["shareholding", "insider_trade"],
        blocks=[BlockPrint(side="buy", quantity=Decimal("100000"))],
        oi=make_oi("long_buildup"),
    )
    assert signal.total == Decimal(4)
    assert signal.verdict == "accumulation"


def test_composite_verdict_distribution() -> None:
    delivery = delivery_history(Decimal("50"), Decimal("1000000"))
    delivery.append(day(Decimal("30"), Decimal("1000000")))
    signal = score(
        delivery=delivery,
        blocks=[BlockPrint(side="sell", quantity=Decimal("200000"))],
        oi=make_oi("long_unwinding", price_change="-3.0"),
    )
    assert signal.total < Decimal("-1.5")
    assert signal.verdict == "distribution"


def test_regime_gate_flips_accumulation_verdict() -> None:
    delivery = delivery_history(Decimal("50"), Decimal("1000000"))
    delivery.append(day(Decimal("80"), Decimal("2000000")))
    heavy_sell = [InstitutionalFlow(category="dii", net_value=Decimal("-1000000000"))]
    signal = score(delivery=delivery, flows=heavy_sell)
    # 1 (delivery) + 0 + 0 + 0 - 0.5 = 0.5 → below the accumulation threshold.
    assert signal.total == Decimal("0.5")
    assert signal.verdict == "neutral"


def test_strategy_config_reflects_parameters() -> None:
    strategy = CompositeSignalStrategy(delivery_spike_multiple="2.0", delivery_min_pct="50")
    c = strategy.config()
    assert c.delivery_spike_multiple == Decimal("2.0")
    assert c.delivery_min_pct == Decimal("50")


def test_strategy_buys_on_accumulation_signal() -> None:
    strategy = CompositeSignalStrategy(signal_threshold="1.5", signal_quantity="100")
    delivery = delivery_history(Decimal("50"), Decimal("1000000"))
    delivery.append(day(Decimal("80"), Decimal("2000000")))
    signal = strategy.score(
        delivery=delivery,
        filings=["shareholding", "insider_trade"],
        blocks=[BlockPrint(side="buy", quantity=Decimal("100000"))],
        oi=make_oi("long_buildup"),
    )
    assert signal.total >= Decimal("1.5")
    strategy.register_signal(INSTRUMENT, signal)
    context = SimulatedContext()
    strategy.run(context, make_bars([Decimal(100)], instrument=INSTRUMENT))
    assert context.position(INSTRUMENT) == Decimal(100)


def test_strategy_holds_when_signal_neutral() -> None:
    strategy = CompositeSignalStrategy(signal_threshold="1.5")
    signal = strategy.score()
    assert signal.total == Decimal(0)
    strategy.register_signal(INSTRUMENT, signal)
    context = SimulatedContext()
    strategy.run(context, make_bars([Decimal(100)], instrument=INSTRUMENT))
    assert context.position(INSTRUMENT) == Decimal(0)
