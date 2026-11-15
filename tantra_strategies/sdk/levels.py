"""Level-map / options-context domain models for the strategy SDK.

1:1 frozen-Decimal mirrors of the canonical models defined upstream in
tantra-core plan 0003 / gap 0002 (feed surfaces land via tantra-market
gap 0005 / tantra-data gap 0016).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from tantra_strategies.sdk.order import OrderSide


class LevelSide(StrEnum):
    SUPPORT = "support"
    RESISTANCE = "resistance"
    BOTH = "both"


class LevelKind(StrEnum):
    ELEPHANT_SUPPORT_1 = "elephant_support_1"
    ELEPHANT_SUPPORT_2 = "elephant_support_2"
    ELEPHANT_RESISTANCE_1 = "elephant_resistance_1"
    ELEPHANT_RESISTANCE_2 = "elephant_resistance_2"
    PREVIOUS_DAY_OHLC = "previous_day_ohlc"
    OI_WALL_CALL = "oi_wall_call"
    OI_WALL_PUT = "oi_wall_put"
    GAMMA_FLIP = "gamma_flip"
    GAMMA_WALL_CALL = "gamma_wall_call"
    GAMMA_WALL_PUT = "gamma_wall_put"
    MAX_PAIN = "max_pain"
    STRIKE_ROUND = "strike_round"
    ORDER_BLOCK = "order_block"


class SignalKind(StrEnum):
    BREAKOUT = "breakout"
    REVERSAL = "reversal"
    RETEST = "retest"


@dataclass(frozen=True, slots=True)
class Level:
    """A named price level with an optional band (half-width) and score."""

    level_id: str
    kind: LevelKind
    side: LevelSide
    price: Decimal
    band_half_width: Decimal = Decimal(0)
    score: int = 0
    source: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.price, Decimal):
            object.__setattr__(self, "price", Decimal(str(self.price)))
        if not isinstance(self.band_half_width, Decimal):
            object.__setattr__(self, "band_half_width", Decimal(str(self.band_half_width)))
        if self.price <= 0:
            raise ValueError("price must be > 0")
        if self.band_half_width < 0:
            raise ValueError("band_half_width must be >= 0")
        if not 0 <= self.score <= 4:
            raise ValueError("score must be within 0..4")

    def band(self) -> tuple[Decimal, Decimal]:
        return (self.price - self.band_half_width, self.price + self.band_half_width)


@dataclass(frozen=True, slots=True)
class LevelMap:
    """A snapshot of named support/resistance levels for one instrument."""

    instrument: str
    levels: tuple[Level, ...] = ()
    as_of: datetime | None = None

    def supports(self) -> tuple[Level, ...]:
        return tuple(
            level for level in self.levels if level.side in (LevelSide.SUPPORT, LevelSide.BOTH)
        )

    def resistances(self) -> tuple[Level, ...]:
        return tuple(
            level for level in self.levels if level.side in (LevelSide.RESISTANCE, LevelSide.BOTH)
        )

    def overlapping(self, price: Decimal, width: Decimal | None = None) -> tuple[Level, ...]:
        """Levels whose band contains ``price`` or intersects ``price +/- width``."""
        if not isinstance(price, Decimal):
            price = Decimal(str(price))
        if width is None:
            return tuple(
                level for level in self.levels if level.band()[0] <= price <= level.band()[1]
            )
        if not isinstance(width, Decimal):
            width = Decimal(str(width))
        low, high = price - width, price + width
        return tuple(
            level for level in self.levels if level.band()[1] >= low and level.band()[0] <= high
        )


@dataclass(frozen=True, slots=True)
class StrategySignal:
    """A directional strategy signal anchored to reference levels."""

    instrument: str
    side: OrderSide
    kind: SignalKind
    ref_levels: tuple[str, ...] = ()
    confidence: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        if not isinstance(self.confidence, Decimal):
            object.__setattr__(self, "confidence", Decimal(str(self.confidence)))
        if not 0 <= self.confidence <= 100:
            raise ValueError("confidence must be within 0..100")


@dataclass(frozen=True, slots=True)
class PositionIntent:
    """A proposed entry with its planned stop/target and risk."""

    instrument: str
    side: OrderSide
    quantity: Decimal
    entry: Decimal
    stop: Decimal
    target: Decimal | None = None
    risk_amount: Decimal | None = None

    def __post_init__(self) -> None:
        for name in ("quantity", "entry", "stop"):
            value = getattr(self, name)
            if not isinstance(value, Decimal):
                object.__setattr__(self, name, Decimal(str(value)))
        for name in ("target", "risk_amount"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, Decimal):
                object.__setattr__(self, name, Decimal(str(value)))
        if self.quantity <= 0:
            raise ValueError("quantity must be > 0")
        if self.entry <= 0:
            raise ValueError("entry must be > 0")
        if self.stop <= 0:
            raise ValueError("stop must be > 0")


@dataclass(frozen=True, slots=True)
class OptionLeg:
    """One option strike row (CE or PE) with OI and gamma stats."""

    strike: Decimal
    option_type: str
    open_interest: Decimal = Decimal(0)
    open_interest_change: Decimal | None = None
    gamma: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.strike, Decimal):
            object.__setattr__(self, "strike", Decimal(str(self.strike)))
        if not isinstance(self.open_interest, Decimal):
            object.__setattr__(self, "open_interest", Decimal(str(self.open_interest)))
        for name in ("open_interest_change", "gamma"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, Decimal):
                object.__setattr__(self, name, Decimal(str(value)))
        if self.strike <= 0:
            raise ValueError("strike must be > 0")
        if self.option_type not in {"CE", "PE"}:
            raise ValueError("option_type must be 'CE' or 'PE'")
        if self.open_interest < 0:
            raise ValueError("open_interest must be >= 0")


@dataclass(frozen=True, slots=True)
class OptionsSnapshot:
    """A point-in-time option-chain snapshot for one instrument/expiry."""

    instrument: str
    expiry: str | None = None
    underlying_spot: Decimal | None = None
    legs: tuple[OptionLeg, ...] = ()

    def __post_init__(self) -> None:
        if self.underlying_spot is not None and not isinstance(self.underlying_spot, Decimal):
            object.__setattr__(self, "underlying_spot", Decimal(str(self.underlying_spot)))

    def max_pain(self) -> Decimal | None:
        """Strike with the maximum combined call+put open interest."""
        combined: dict[Decimal, Decimal] = {}
        for leg in self.legs:
            combined[leg.strike] = combined.get(leg.strike, Decimal(0)) + leg.open_interest
        if not combined:
            return None
        return max(combined, key=lambda strike: combined[strike])

    def call_walls(self, n: int = 2) -> tuple[OptionLeg, ...]:
        """Top-n call legs by open interest."""
        calls = [leg for leg in self.legs if leg.option_type == "CE"]
        return tuple(sorted(calls, key=lambda leg: leg.open_interest, reverse=True)[:n])

    def put_walls(self, n: int = 2) -> tuple[OptionLeg, ...]:
        """Top-n put legs by open interest."""
        puts = [leg for leg in self.legs if leg.option_type == "PE"]
        return tuple(sorted(puts, key=lambda leg: leg.open_interest, reverse=True)[:n])
