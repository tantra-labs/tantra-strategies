"""Institutional smart-money composite signal (agent plan 0010 Phase 5).

A pure, cross-validated accumulation/distribution signal combining four
independently-sourced per-instrument legs plus one market-wide regime gate:

1. **Delivery-adjusted volume** (`delivery_analysis`): a delivery-pct x volume
   spike relative to its trailing average confirms cash-market accumulation;
   persistently low delivery % signals weak-hand churn.
2. **Shareholding / insider filings** (`filings_search`): disclosed ownership
   movement corroborates (or contradicts) the price read.
3. **Block/bulk deal prints** (`block_deals`): a large negotiated buy or sell is
   direct institutional footprint.
4. **OI-buildup direction** (`oi_buildup`): the four-quadrant price/OI
   classification gives the derivatives read.
5. **Regime gate** (`institutional_flows`): when DIIs are net heavy sellers, a
   long-buildup read is discounted — the per-stock signal cannot outweigh the
   broader institutional tape.

Every threshold lives in [`CompositeSignalConfig`] as an exact ``Decimal``
(never ``float``); the pure [`compute_composite_signal`] function is the
unit-tested core, and [`CompositeSignalStrategy`] wires the same thresholds as
declarative ``Parameter``s for the strategy catalog.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from tantra_strategies.sdk import Parameter, Strategy

# --- canonical enums (mirror the Rust-side contracts) -----------------------------

# Four-quadrant OI buildup classes — mirror `tantra-market-store`'s
# `BuildupClass` snake_case names (agent plan 0010 Phase 3).
LONG_BUILDUP = "long_buildup"
SHORT_BUILDUP = "short_buildup"
SHORT_COVERING = "short_covering"
LONG_UNWINDING = "long_unwinding"

# Filing types relevant to ownership change — the canonical `FilingType` set
# mirrored by the chat `filings_search` tool.
SHAREHOLDING_FILING = "shareholding"
INSIDER_FILING = "insider_trade"

# FII/DII categories in the chat `institutional_flows` tool output.
FII = "fii"
DII = "dii"


# --- observation value objects (mirror the chat tool outputs) ---------------------


@dataclass(frozen=True)
class DeliveryObservation:
    """One day's delivery-adjusted volume observation (``delivery_analysis``)."""

    date: str
    traded_qty: Decimal
    delivered_qty: Decimal
    delivery_pct: Decimal


@dataclass(frozen=True)
class BlockPrint:
    """One disclosed block/bulk deal print (``block_deals``)."""

    side: str  # "buy" | "sell"
    quantity: Decimal
    category: str = "block"  # "block" | "bulk"


@dataclass(frozen=True)
class InstitutionalFlow:
    """One day's FII or DII net flow (``institutional_flows``)."""

    category: str  # "fii" | "dii"
    net_value: Decimal


@dataclass(frozen=True)
class OiBuildupSnapshot:
    """One instrument's OI-buildup classification (``oi_buildup``)."""

    open_interest: Decimal
    oi_change_pct: Decimal | None
    price_change_pct: Decimal | None
    classification: str


# --- thresholds -------------------------------------------------------------------


@dataclass(frozen=True)
class CompositeSignalConfig:
    """Every composite-score threshold, exact ``Decimal`` throughout."""

    # Delivery leg: how many times the trailing-average delivery-adjusted
    # activity the latest day must reach to count as a spike.
    delivery_lookback: int = 20
    delivery_spike_multiple: Decimal = Decimal("1.5")
    # Latest delivery % below this is treated as weak-hand churn (distribution read).
    delivery_min_pct: Decimal = Decimal("40")
    # OI leg: |oi_change_pct| below this neutralizes the OI read.
    oi_min_change_pct: Decimal = Decimal("2")
    # OI leg: |price_change_pct| below this neutralizes the OI read.
    price_min_change_pct: Decimal = Decimal("1")
    # Block leg: prints below this quantity are ignored as noise.
    block_min_qty: Decimal = Decimal("50000")
    # Regime gate: when the latest DII net value is below this (INR), the
    # composite is discounted by `regime_discount`.
    dii_heavy_sell: Decimal = Decimal("-500000000")
    # Regime gate: absolute discount applied to the total when DIIs are net heavy sellers.
    regime_discount: Decimal = Decimal("0.5")
    # Composite thresholds for the verdict band.
    accumulation_threshold: Decimal = Decimal("1.5")
    distribution_threshold: Decimal = Decimal("-1.5")


# --- result -----------------------------------------------------------------------


@dataclass(frozen=True)
class CompositeSignal:
    """The composite smart-money signal for one instrument."""

    delivery_leg: Decimal
    filings_leg: Decimal
    block_leg: Decimal
    oi_leg: Decimal
    regime_adjustment: Decimal
    total: Decimal
    verdict: str


# --- per-leg scoring (pure, exact Decimal) ----------------------------------------


def delivery_leg(
    config: CompositeSignalConfig,
    delivery: Sequence[DeliveryObservation],
) -> Decimal:
    """Score the delivery-adjusted-volume leg in ``[-1, +1]``.

    A spike is ``latest_delivery_pct >= delivery_min_pct`` AND
    ``latest_activity >= trailing_average_activity * delivery_spike_multiple``
    where activity = ``delivery_pct * traded_qty``. With too few observations
    the leg is neutral (``0``); a latest delivery % below the minimum reads as
    churn (``-1``); a spike reads as accumulation (``+1``).
    """
    if not delivery:
        return Decimal(0)
    latest = delivery[-1]
    if latest.delivery_pct < config.delivery_min_pct:
        return Decimal(-1)
    if len(delivery) < 2:
        return Decimal(0)
    history = delivery[:-1][-config.delivery_lookback :]
    if not history:
        return Decimal(0)
    total_activity = sum((d.delivery_pct * d.traded_qty for d in history), Decimal(0))
    average_activity = total_activity / Decimal(len(history))
    if average_activity <= 0:
        return Decimal(0)
    latest_activity = latest.delivery_pct * latest.traded_qty
    if latest_activity >= average_activity * config.delivery_spike_multiple:
        return Decimal(1)
    return Decimal(0)


def filings_leg(
    config: CompositeSignalConfig,
    filings: Sequence[str],
) -> Decimal:
    """Score the shareholding/insider-filing leg in ``[0, +1]``.

    Any disclosed shareholding or insider-trade filing corroborates ownership
    movement; each relevant filing type contributes ``+0.5``, capped at ``+1``.
    """
    del config
    score = Decimal(0)
    if SHAREHOLDING_FILING in filings:
        score += Decimal("0.5")
    if INSIDER_FILING in filings:
        score += Decimal("0.5")
    return min(score, Decimal(1))


def block_leg(
    config: CompositeSignalConfig,
    blocks: Sequence[BlockPrint],
) -> Decimal:
    """Score the block/bulk-deal leg in ``[-1, +1]``.

    A large buy print reads ``+1``, a large sell print ``-1``; smaller prints
    are ignored as noise.
    """
    for block in blocks:
        if block.quantity >= config.block_min_qty:
            return Decimal(1) if block.side == "buy" else Decimal(-1)
    return Decimal(0)


def oi_leg(
    config: CompositeSignalConfig,
    oi: OiBuildupSnapshot | None,
) -> Decimal:
    """Score the OI-buildup leg in ``[-1, +1]``.

    The four-quadrant class maps: long buildup ``+1``, short covering ``+0.5``,
    long unwinding ``-0.5``, short buildup ``-1``. A move too small to be
    meaningful (either change % below its threshold) neutralizes the leg.
    """
    if oi is None:
        return Decimal(0)
    small_move = oi.oi_change_pct is not None and abs(oi.oi_change_pct) < config.oi_min_change_pct
    small_price = (
        oi.price_change_pct is not None and abs(oi.price_change_pct) < config.price_min_change_pct
    )
    if small_move or small_price:
        return Decimal(0)
    return {
        LONG_BUILDUP: Decimal(1),
        SHORT_COVERING: Decimal("0.5"),
        LONG_UNWINDING: Decimal("-0.5"),
        SHORT_BUILDUP: Decimal(-1),
    }.get(oi.classification, Decimal(0))


def regime_adjustment(
    config: CompositeSignalConfig,
    flows: Sequence[InstitutionalFlow],
) -> Decimal:
    """The market-wide regime gate in ``[0, -regime_discount]``.

    When the latest DII net flow is a heavy net sell (below ``dii_heavy_sell``)
    the composite is discounted; otherwise no adjustment.
    """
    latest_dii = next((f for f in reversed(flows) if f.category == DII), None)
    if latest_dii is not None and latest_dii.net_value < config.dii_heavy_sell:
        return -config.regime_discount
    return Decimal(0)


def verdict_for(config: CompositeSignalConfig, total: Decimal) -> str:
    """Classify the composite total into an accumulation/distribution verdict."""
    if total >= config.accumulation_threshold:
        return "accumulation"
    if total <= config.distribution_threshold:
        return "distribution"
    return "neutral"


def compute_composite_signal(
    config: CompositeSignalConfig,
    *,
    delivery: Sequence[DeliveryObservation],
    filings: Sequence[str],
    blocks: Sequence[BlockPrint],
    oi: OiBuildupSnapshot | None,
    flows: Sequence[InstitutionalFlow],
) -> CompositeSignal:
    """Compute the cross-validated composite signal for one instrument.

    All legs are exact ``Decimal`` arithmetic; the total is the plain sum of
    the four per-instrument legs plus the (non-positive) regime adjustment.
    """
    delivery_score = delivery_leg(config, delivery)
    filings_score = filings_leg(config, filings)
    block_score = block_leg(config, blocks)
    oi_score = oi_leg(config, oi)
    regime = regime_adjustment(config, flows)
    total = delivery_score + filings_score + block_score + oi_score + regime
    return CompositeSignal(
        delivery_leg=delivery_score,
        filings_leg=filings_score,
        block_leg=block_score,
        oi_leg=oi_score,
        regime_adjustment=regime,
        total=total,
        verdict=verdict_for(config, total),
    )


# --- strategy catalog entry -------------------------------------------------------


class CompositeSignalStrategy(Strategy):
    """Cross-validated institutional accumulation/distribution detector.

    Computes the four-factor composite score (delivery spike, ownership
    filings, block prints, OI buildup) gated by the FII/DII regime for each
    instrument, and buys/sells toward ``signal_quantity`` whenever the
    composite crosses ``signal_threshold``.

    Observations are fed from the chat tool outputs (``delivery_analysis``,
    ``filings_search``, ``block_deals``, ``oi_buildup``, ``institutional_flows``)
    via :meth:`register_signal`; the pure scoring core is
    :func:`compute_composite_signal`.
    """

    instruments = Parameter(default="NSE:NIFTY50-INDEX")
    delivery_lookback = Parameter(default=20, min=2, max=100, step=1)
    delivery_spike_multiple = Parameter(default="1.5", min="1.0", max="5.0", step="0.1")
    delivery_min_pct = Parameter(default="40", min="1", max="100", step="1")
    oi_min_change_pct = Parameter(default="2", min="0", max="50", step="1")
    price_min_change_pct = Parameter(default="1", min="0", max="50", step="1")
    block_min_qty = Parameter(default="50000", min="100", max="100000000", step="100")
    dii_heavy_sell = Parameter(
        default="-500000000", min="-100000000000", max="100000000000", step="1000000"
    )
    regime_discount = Parameter(default="0.5", min="0", max="4", step="0.1")
    signal_threshold = Parameter(default="1.5", min="0", max="4", step="0.1")
    signal_quantity = Parameter(default="100", min="1", max="1000000", step="1")

    def __init__(self, **overrides: object) -> None:
        super().__init__(**overrides)
        self._signals: dict[str, CompositeSignal] = {}

    def config(self) -> CompositeSignalConfig:
        """The pure scoring configuration derived from the declarative parameters."""
        return CompositeSignalConfig(
            delivery_lookback=int(self.delivery_lookback),
            delivery_spike_multiple=Decimal(str(self.delivery_spike_multiple)),
            delivery_min_pct=Decimal(str(self.delivery_min_pct)),
            oi_min_change_pct=Decimal(str(self.oi_min_change_pct)),
            price_min_change_pct=Decimal(str(self.price_min_change_pct)),
            block_min_qty=Decimal(str(self.block_min_qty)),
            dii_heavy_sell=Decimal(str(self.dii_heavy_sell)),
            regime_discount=Decimal(str(self.regime_discount)),
        )

    def register_signal(self, instrument: str, signal: CompositeSignal) -> None:
        """Feed a computed composite signal for an instrument (tool-fed)."""
        self._signals[instrument] = signal

    def score(
        self,
        *,
        delivery: Sequence[DeliveryObservation] = (),
        filings: Sequence[str] = (),
        blocks: Sequence[BlockPrint] = (),
        oi: OiBuildupSnapshot | None = None,
        flows: Sequence[InstitutionalFlow] = (),
    ) -> CompositeSignal:
        """Compute a composite signal with this strategy's configured thresholds."""
        return compute_composite_signal(
            self.config(),
            delivery=delivery,
            filings=filings,
            blocks=blocks,
            oi=oi,
            flows=flows,
        )

    def on_bar(self, bar) -> None:
        signal = self._signals.get(bar.instrument)
        if signal is None:
            return
        threshold = Decimal(str(self.signal_threshold))
        target = Decimal(str(self.signal_quantity))
        current = self.position(bar.instrument)
        if signal.total >= threshold and current < target:
            self.buy(bar.instrument, target - current)
        elif signal.total <= -threshold and current > 0:
            self.sell(bar.instrument, current)
