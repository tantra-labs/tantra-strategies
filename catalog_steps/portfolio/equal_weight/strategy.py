"""Equal-weight portfolio rebalancer for the ``tantra-examples`` harness loader.

This file is the loader surface that ``load_named("equal_weight")`` imports
(tantra-examples ``harness/loader.py``): the directory registered in
``registry.json`` must contain a ``strategy.py`` defining exactly one
``tantra.base.Strategy`` subclass plus a ``config.toml``. It speaks the wheel
API (``InstrumentId``, ``OrderIntent``, ``self.ctx``) so it is driven by
``StrategyRunner`` / ``run_portfolio_backtest``.

The declarative SDK twin lives at
``tantra_strategies.strategies.equal_weight`` and is what the in-repo catalog
executor (``tools/run_step.py``) and ``tests/strategies/`` run. Both implement
the same equal-weight rule (gap 0007).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from tantra.bar import Bar as WheelBar
from tantra.base import Parameter, Strategy
from tantra.instrument import InstrumentId
from tantra.markets.india.universes import resolve_universe
from tantra.money import Money


class EqualWeight(Strategy):
    """Equal-weight rebalance over the configured universe (wheel surface)."""

    name = "equal_weight"

    universe = Parameter(default="nifty200_alpha_30")
    rebalance_period = Parameter(default=5, min=1, max=252, step=1)
    capital = Parameter(default=1_000_000, min=1, max=10_000_000_000, step=1)

    def __init__(self, config: object | None = None) -> None:
        if config is not None:
            self._params = dict(getattr(config, "params", {}))
        self._members: list[InstrumentId] = []
        self._closes: dict[InstrumentId, Decimal] = {}
        self._driving_bars = 0
        self._last_day: object = None
        self._established = False

    def on_start(self) -> None:
        self._members = sorted(
            resolve_universe(str(self.universe), exchange="NSE"),
            key=lambda iid: (iid.symbol, iid.exchange),
        )

    def _enough_priced(self) -> bool:
        """True once at least all-but-one member has priced (missing-data tolerant)."""
        return len(self._closes) >= max(1, len(self._members) - 1)

    def on_bar(self, bar: WheelBar, ctx: Any = None) -> None:
        del ctx
        iid: InstrumentId = bar.instrument_id
        self._closes[iid] = bar.close
        new_day = bar.ts != self._last_day
        if new_day:
            self._last_day = bar.ts
            self._driving_bars += 1
        if self._enough_priced() and (
            not self._established or (new_day and self._driving_bars % self.rebalance_period == 0)
        ):
            self._established = True
            self._rebalance()

    def _rebalance(self) -> None:
        priced = [member for member in self._members if member in self._closes]
        if not priced:
            return
        cash = self.ctx.cash()
        equity = cash
        for member in priced:
            equity = equity + Money.mul_qty(
                self.position(member), self._closes[member], cash.currency
            )
        per_name = equity.amount / len(priced)
        for member in sorted(priced, key=lambda iid: (iid.symbol, iid.exchange)):
            if self.ctx.busy(member):
                continue
            close = self._closes[member]
            if close <= 0:
                continue
            target = per_name // close
            current = self.position(member)
            delta = target - current
            if delta > 0:
                self.buy(member, delta)
            elif delta < 0:
                self.sell(member, -delta)

    def on_stop(self) -> None:
        """Clean stop: intents submitted in ``on_stop`` are never executed."""
