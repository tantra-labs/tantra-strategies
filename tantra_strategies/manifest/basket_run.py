"""Basket reference run loop: resolve, size, run, and enforce (gaps 0004/0005).

For each ``MemberStrategyRef`` in a :class:`BasketManifest`, resolve the
referenced :class:`StrategyManifest` sidecar under ``manifests/strategies/``,
size each member's capital with :func:`optimize_allocations` (gap 0004), run
the member strategy deterministically through a :class:`SimulatedContext`, and
enforce the basket ``RiskBudget`` caps -- raising :class:`RiskBudgetViolation`
when a run exceeds them.

The cross-repo consumer is ``tantra-runtime-backtest`` (basket loop); a full
allocation-objective optimizer (``tantra-ledger-allocation``) is gap 0005 and
remains a future integration.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from tantra_strategies.manifest.basket import (
    BasketManifest,
    MemberStrategyRef,
    RiskBudget,
    optimize_allocations,
)
from tantra_strategies.manifest.strategy import StrategyManifest
from tantra_strategies.sdk.bar import Bar
from tantra_strategies.sdk.context import SimulatedContext
from tantra_strategies.sdk.order import OrderEvent, OrderSide, OrderStatus
from tantra_strategies.sdk.strategy import Strategy


class RiskBudgetViolation(RuntimeError):
    """Raised when a basket run exceeds its declared RiskBudget caps."""


DEFAULT_STRATEGIES_DIR = Path(__file__).resolve().parent.parent.parent / "manifests" / "strategies"


@dataclass(frozen=True, slots=True)
class BasketMemberRun:
    """One member strategy's allocation, instance, context, and event trace."""

    member: MemberStrategyRef
    allocation: Decimal
    strategy: Strategy
    context: SimulatedContext
    events: tuple[OrderEvent, ...]


@dataclass(frozen=True, slots=True)
class BasketRunResult:
    """Outcome of a full basket run: allocations, member runs, budget totals."""

    allocations: dict[str, Decimal]
    runs: dict[str, BasketMemberRun]
    total_position_fraction: Decimal
    total_realized_pnl: Decimal


def resolve_manifest(member: MemberStrategyRef, strategies_dir: Path) -> StrategyManifest:
    """Find the strategy sidecar whose name/version match a basket member."""
    for path in sorted(strategies_dir.glob("*.toml")):
        manifest = StrategyManifest.load_toml(path)
        if manifest.name == member.name and manifest.version == member.version:
            return manifest
    raise KeyError(f"no strategy manifest for {member.name}@{member.version} in {strategies_dir}")


def realized_pnl(events: Sequence[OrderEvent]) -> Decimal:
    """Average-cost realized PnL from COMPLETE fills."""
    inventory = Decimal(0)
    avg_cost = Decimal(0)
    pnl = Decimal(0)
    for event in events:
        if (
            event.status is not OrderStatus.COMPLETE
            or event.price is None
            or event.filled_quantity <= 0
        ):
            continue
        signed = event.filled_quantity if event.side is OrderSide.BUY else -event.filled_quantity
        if signed > 0:
            new_inventory = inventory + signed
            avg_cost = (avg_cost * inventory + event.price * signed) / new_inventory
            inventory = new_inventory
        else:
            pnl += (event.price - avg_cost) * (-signed)
            inventory += signed
            if inventory == 0:
                avg_cost = Decimal(0)
    return pnl


def run_basket(
    basket: BasketManifest,
    bars: Mapping[str, Sequence[Bar]],
    *,
    strategies_dir: Path | None = None,
    strategy_overrides: Mapping[str, Mapping[str, object]] | None = None,
) -> BasketRunResult:
    """Run every member strategy in the basket deterministically.

    Resolves each member sidecar, sizes capital with ``optimize_allocations``
    (gap 0004), runs each member in a fresh :class:`SimulatedContext`, and
    enforces the basket ``RiskBudget`` (gap 0005).
    """
    if strategies_dir is None:
        strategies_dir = DEFAULT_STRATEGIES_DIR
    allocations = optimize_allocations(basket)
    overrides = dict(strategy_overrides or {})
    runs: dict[str, BasketMemberRun] = {}
    for member, allocation in zip(basket.member_strategies, allocations, strict=True):
        manifest = resolve_manifest(member, strategies_dir)
        strategy = manifest.instantiate(**dict(overrides.get(member.name, {})))
        context = SimulatedContext()
        member_bars = [
            bar
            for instrument in manifest.target_instruments.instruments
            for bar in bars.get(instrument, [])
        ]
        context.run(strategy, member_bars)
        runs[member.name] = BasketMemberRun(
            member=member,
            allocation=allocation,
            strategy=strategy,
            context=context,
            events=tuple(context.events),
        )
    total_position_fraction = _position_fraction(runs, basket.combined_capital)
    total_realized_pnl = sum(
        (realized_pnl(run.context.events) for run in runs.values()),
        Decimal(0),
    )
    _enforce_budget(basket.risk_budget, total_position_fraction, total_realized_pnl)
    return BasketRunResult(
        allocations={m.name: a for m, a in zip(basket.member_strategies, allocations, strict=True)},
        runs=runs,
        total_position_fraction=total_position_fraction,
        total_realized_pnl=total_realized_pnl,
    )


def _position_fraction(runs: Mapping[str, BasketMemberRun], combined_capital: Decimal) -> Decimal:
    """Total open position notional across member runs, as a capital fraction.

    Reads ``SimulatedContext._positions`` directly: same package, and the
    public API exposes no aggregate position ledger (gap 0004).
    """
    notional = sum(
        (
            abs(position) * run.context.current_price(instrument)
            for run in runs.values()
            for instrument, position in run.context._positions.items()
        ),
        Decimal(0),
    )
    return notional / combined_capital


def _enforce_budget(
    budget: RiskBudget,
    total_position_fraction: Decimal,
    total_realized_pnl: Decimal,
) -> None:
    """Raise ``RiskBudgetViolation`` when a basket run exceeds its caps."""
    if (
        budget.max_position_fraction is not None
        and total_position_fraction > budget.max_position_fraction
    ):
        raise RiskBudgetViolation(
            f"total position fraction {total_position_fraction} exceeds the "
            f"cap {budget.max_position_fraction}"
        )
    if budget.max_loss is not None and total_realized_pnl < -budget.max_loss:
        raise RiskBudgetViolation(
            f"total realized PnL {total_realized_pnl} exceeds the loss cap {budget.max_loss}"
        )


__all__ = [
    "DEFAULT_STRATEGIES_DIR",
    "BasketMemberRun",
    "BasketRunResult",
    "RiskBudgetViolation",
    "realized_pnl",
    "resolve_manifest",
    "run_basket",
]
