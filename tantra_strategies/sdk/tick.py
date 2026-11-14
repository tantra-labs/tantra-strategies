"""Canonical market-data tick with exact ``Decimal`` prices (zero-floats)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Tick:
    """One market-data tick (last trade or top-of-book update).

    Mirrors the canonical ``Tick`` contract consumed by ``tantra-market`` feed
    adapters: every price is an exact ``Decimal``. ``bid``/``ask`` are optional
    top-of-book levels for tick-driven quoting / market-making strategies.
    """

    instrument: str
    ts: datetime
    last_price: Decimal
    volume: int = 0
    bid: Decimal | None = None
    ask: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "last_price", self._coerce(self.last_price))
        object.__setattr__(self, "bid", self._coerce(self.bid) if self.bid is not None else None)
        object.__setattr__(self, "ask", self._coerce(self.ask) if self.ask is not None else None)
        if self.last_price < 0:
            raise ValueError("last_price must be non-negative")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("bid must be <= ask")

    @staticmethod
    def _coerce(value: Decimal | int | str) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))
