"""Alpha-30 momentum factor for the ``tantra-examples`` harness loader.

This file is the loader surface that ``load_named("alpha30_factor")`` imports
(tantra-examples ``harness/loader.py``): the directory registered in
``registry.json`` must contain a ``strategy.py`` defining exactly one
``tantra.base.Strategy`` subclass plus a ``config.toml``. It speaks the wheel
API (``InstrumentId``, ``OrderIntent``, ``self.ctx``) so it is driven by
``StrategyRunner`` / ``run_portfolio_backtest``.

The declarative ``step.toml`` beside it keeps the chain contract
(``signal.alpha30_factor`` consumes ``universe``, emits ``orders``); this
class is what makes the step runnable rather than merely validated (gap 0007).
"""

from __future__ import annotations

from decimal import Decimal

from tantra.base import Parameter, Strategy
from tantra.instrument import InstrumentId
from tantra.markets.india.universes import resolve_universe


class Alpha30Factor(Strategy):
    """Long the top ``top_n`` universe names by ``lookback``-day ROC (wheel surface)."""

    name = "alpha30_factor"

    universe = Parameter(default="nifty200_alpha_30")
    lookback = Parameter(default=30, min=2, max=252, step=1)
    top_n = Parameter(default=10, min=1, max=64, step=1)
    rebalance_period = Parameter(default=5, min=1, max=252, step=1)
    capital = Parameter(default=1_000_000, min=1, max=10_000_000_000, step=1)

    def __init__(self, config: object | None = None) -> None:
        if config is not None:
            self._params = dict(getattr(config, "params", {}))
        self._members: list[InstrumentId] = []
        self._history: dict[InstrumentId, list[Decimal]] = {}
        self._driving_bars = 0
        self._last_day: object = None
        self._established = False

    def on_start(self) -> None:
        self._members = sorted(
            resolve_universe(str(self.universe), exchange="NSE"),
            key=lambda iid: (iid.symbol, iid.exchange),
        )
        self._history = {member: [] for member in self._members}

    def _enough_priced(self) -> bool:
        """True once at least all-but-one member has priced (missing-data tolerant)."""
        return sum(1 for history in self._history.values() if history) >= max(
            1, len(self._members) - 1
        )

    def on_bar(self, bar: object) -> None:
        iid: InstrumentId = bar.instrument_id
        if iid in self._history:
            self._history[iid].append(bar.close)
            if len(self._history[iid]) > self.lookback + 1:
                del self._history[iid][0]
        new_day = bar.ts != self._last_day
        if new_day:
            self._last_day = bar.ts
            self._driving_bars += 1
        if self._enough_priced() and (
            not self._established or (new_day and self._driving_bars % self.rebalance_period == 0)
        ):
            self._established = True
            self._rebalance()

    def _roc(self, iid: InstrumentId) -> Decimal | None:
        history = self._history.get(iid) or []
        if len(history) < self.lookback + 1:
            return None
        start = history[-(self.lookback + 1)]
        if start <= 0:
            return None
        return history[-1] / start

    def _rebalance(self) -> None:
        scores: dict[InstrumentId, Decimal] = {}
        closes: dict[InstrumentId, Decimal] = {}
        for member in self._members:
            roc = self._roc(member)
            if roc is not None:
                scores[member] = roc
                closes[member] = self._history[member][-1]
        if not scores:
            return
        ranked = sorted(scores, key=scores.__getitem__, reverse=True)
        selected = set(ranked[: int(self.top_n)])
        per_name = Decimal(self.capital) / len(selected)
        for member in sorted(self._members, key=lambda iid: (iid.symbol, iid.exchange)):
            if self.ctx.busy(member):
                continue
            current = self.position(member)
            if member not in selected:
                if current > 0:
                    self.sell(member, current)
                continue
            close = closes[member]
            if close <= 0:
                continue
            target = per_name // close
            delta = target - current
            if delta > 0:
                self.buy(member, delta)
            elif delta < 0:
                self.sell(member, -delta)

    def on_stop(self) -> None:
        """Clean stop: intents submitted in ``on_stop`` are never executed."""
