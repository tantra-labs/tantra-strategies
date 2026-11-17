"""Equal-weight portfolio rebalancer across a basket of instruments."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from tantra_strategies.sdk import Bar, Parameter, Strategy


class EqualWeight(Strategy):
    """Hold every basket member at an equal capital share, rebalanced periodically.

    The basket is the comma-separated ``instruments`` parameter (the manifest
    universe). On the first bar on which every member has priced, and then every
    ``rebalance_period`` driving bars, each member's target quantity is
    ``floor(capital / n_members / close)``; the strategy buys or sells the
    difference to its current position with exact ``Decimal`` arithmetic
    (zero floats). ``on_stop`` is a clean no-op: there is nothing left to
    release in the simulated or live run.
    """

    instruments = Parameter(default="NSE:NIFTY50-INDEX")
    rebalance_period = Parameter(default=5, min=1, max=252, step=1)
    capital = Parameter(default=1_000_000, min=1, max=10_000_000_000, step=1)

    def __init__(self, **overrides: object) -> None:
        super().__init__(**overrides)
        self._members: list[str] = []
        self._closes: dict[str, Decimal] = {}
        self._driving_bars = 0
        self._last_day: datetime | None = None
        self._established = False

    def on_start(self) -> None:
        members = [name.strip() for name in str(self.instruments).split(",") if name.strip()]
        if not members:
            raise ValueError("EqualWeight requires a non-empty 'instruments' basket")
        self._members = members

    def _enough_priced(self) -> bool:
        """True once at least all-but-one member has priced (missing-data tolerant)."""
        return len(self._closes) >= max(1, len(self._members) - 1)

    def on_bar(self, bar: Bar) -> None:
        self._closes[bar.instrument] = bar.close
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
        per_name = Decimal(self.capital) / len(self._members)
        for instrument in sorted(self._members):
            close = self._closes.get(instrument)
            if close is None or close <= 0:
                continue
            target = per_name // close
            current = self.position(instrument)
            delta = target - current
            if delta > 0:
                self.buy(instrument, delta)
            elif delta < 0:
                self.sell(instrument, -delta)

    def on_stop(self) -> None:
        """Clean stop: nothing left to release in the simulated or live run."""
