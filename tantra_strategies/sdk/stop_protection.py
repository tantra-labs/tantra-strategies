"""Stop-loss / trailing-stop primitives for the strategy SDK.

Mirror of the canonical stop-loss/trailing-stop types defined upstream in
tantra-core plan 0003 / gap 0002 (frozen, exact-Decimal value objects).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from tantra_strategies.sdk.order import OrderSide


class TrailMode(StrEnum):
    OFF = "off"
    ATR = "atr"
    SWING = "swing"


@dataclass(frozen=True, slots=True)
class StopProtection:
    """Stop-loss specification: initial SL plus optional trailing rules."""

    sl: Decimal
    trail: TrailMode = TrailMode.OFF
    trail_distance: Decimal = Decimal(0)
    activation_after_r: Decimal = Decimal(1)

    def __post_init__(self) -> None:
        if not isinstance(self.sl, Decimal):
            object.__setattr__(self, "sl", Decimal(str(self.sl)))
        if not isinstance(self.trail_distance, Decimal):
            object.__setattr__(self, "trail_distance", Decimal(str(self.trail_distance)))
        if not isinstance(self.activation_after_r, Decimal):
            object.__setattr__(self, "activation_after_r", Decimal(str(self.activation_after_r)))
        if self.sl <= 0:
            raise ValueError("sl must be > 0")
        if self.trail_distance < 0:
            raise ValueError("trail_distance must be >= 0")
        if self.activation_after_r < 0:
            raise ValueError("activation_after_r must be >= 0")

    def to_dict(self) -> dict[str, str]:
        return {
            "sl": str(self.sl),
            "trail": self.trail.value,
            "trail_distance": str(self.trail_distance),
            "activation_after_r": str(self.activation_after_r),
        }


@dataclass(frozen=True, slots=True)
class StopUpdate:
    """A dispatched stop-loss movement event."""

    instrument: str
    side: OrderSide
    new_stop: Decimal
    old_stop: Decimal | None = None
    ts: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.new_stop, Decimal):
            object.__setattr__(self, "new_stop", Decimal(str(self.new_stop)))
        if self.old_stop is not None and not isinstance(self.old_stop, Decimal):
            object.__setattr__(self, "old_stop", Decimal(str(self.old_stop)))
        if self.new_stop <= 0:
            raise ValueError("new_stop must be > 0")
        if self.old_stop is not None and self.old_stop <= 0:
            raise ValueError("old_stop must be > 0")
