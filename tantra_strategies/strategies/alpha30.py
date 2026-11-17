"""Alpha-30 style momentum factor: 30-day ROC rank, long the top N equal-weight."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from tantra_strategies.sdk import Bar, Parameter, Strategy


class Alpha30Factor(Strategy):
    """Long the top ``top_n`` basket members by ``lookback``-day rate of change.

    On the first bar on which every member has priced, and then every
    ``rebalance_period`` driving bars, members are ranked by
    ``close / close_{t - lookback}`` and the top ``top_n`` are held at an equal
    capital share (``floor(capital / top_n / close)``). Members that drop out of
    the selection are sold back to flat. All arithmetic is exact ``Decimal``
    (zero floats); ranking ties resolve deterministically by basket order.
    """

    instruments = Parameter(default="NSE:NIFTY50-INDEX")
    lookback = Parameter(default=30, min=2, max=252, step=1)
    top_n = Parameter(default=10, min=1, max=64, step=1)
    rebalance_period = Parameter(default=5, min=1, max=252, step=1)
    capital = Parameter(default=1_000_000, min=1, max=10_000_000_000, step=1)

    def __init__(self, **overrides: object) -> None:
        super().__init__(**overrides)
        self._members: list[str] = []
        self._history: dict[str, list[Decimal]] = {}
        self._driving_bars = 0
        self._last_day: datetime | None = None
        self._established = False

    def on_start(self) -> None:
        members = [name.strip() for name in str(self.instruments).split(",") if name.strip()]
        if not members:
            raise ValueError("Alpha30Factor requires a non-empty 'instruments' basket")
        self._members = members
        self._history = {member: [] for member in members}

    def _enough_priced(self) -> bool:
        """True once at least all-but-one member has priced (missing-data tolerant)."""
        return sum(1 for history in self._history.values() if history) >= max(
            1, len(self._members) - 1
        )

    def on_bar(self, bar: Bar) -> None:
        if bar.instrument in self._history:
            self._history[bar.instrument].append(bar.close)
            if len(self._history[bar.instrument]) > self.lookback + 1:
                del self._history[bar.instrument][0]
        new_day = bar.ts != self._last_day
        if new_day:
            self._last_day = bar.ts
            self._driving_bars += 1
        if self._enough_priced() and (
            not self._established or (new_day and self._driving_bars % self.rebalance_period == 0)
        ):
            self._established = True
            self._rebalance()

    def _roc(self, instrument: str) -> Decimal | None:
        history = self._history.get(instrument)
        if not history or len(history) < self.lookback + 1:
            return None
        start = history[-(self.lookback + 1)]
        if start <= 0:
            return None
        return history[-1] / start

    def _rebalance(self) -> None:
        scores: dict[str, Decimal] = {}
        closes: dict[str, Decimal] = {}
        for member in self._members:
            roc = self._roc(member)
            if roc is not None:
                scores[member] = roc
                closes[member] = self._history[member][-1]
        if not scores:
            return
        ranked = sorted(scores, key=scores.__getitem__, reverse=True)
        selected = set(ranked[: self.top_n])
        per_name = Decimal(self.capital) / len(selected)
        for instrument in sorted(self._members):
            current = self.position(instrument)
            if instrument not in selected:
                if current > 0:
                    self.sell(instrument, current)
                continue
            close = closes[instrument]
            if close <= 0:
                continue
            target = per_name // close
            delta = target - current
            if delta > 0:
                self.buy(instrument, delta)
            elif delta < 0:
                self.sell(instrument, -delta)

    def on_stop(self) -> None:
        """Clean stop: nothing left to release in the simulated or live run."""
