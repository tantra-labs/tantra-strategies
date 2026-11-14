"""BasketManifest: several strategy versions under one capital/risk budget.

Phase 2 of plan 0001. A basket references one or more ``StrategyManifest``
versions and validates that the combined allocation fits ``combined_capital``.
The basket-level risk budget is sized by :func:`optimize_allocations` (defined
here, gap 0004) and enforced by the basket run loop in ``basket_run.py``
(gap 0005); a full allocation-objective optimizer such as
``tantra-ledger-allocation`` remains a future cross-repo integration.
"""

from __future__ import annotations

import tomllib
from decimal import Decimal
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MemberStrategyRef(BaseModel):
    """A reference to one ``StrategyManifest`` version plus its allocation."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z0-9_]+$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    weight: Decimal | None = Field(default=None, description="Fraction of combined capital.")
    allocation: Decimal | None = Field(default=None, description="Absolute Money amount (INR).")

    @model_validator(mode="after")
    def _exactly_one_allocation(self) -> Self:
        has_weight = self.weight is not None
        has_allocation = self.allocation is not None
        if has_weight == has_allocation:
            raise ValueError("member strategy must set exactly one of weight or allocation")
        if self.weight is not None and not Decimal("0") < self.weight <= Decimal("1"):
            raise ValueError("member weight must be in the open unit interval (0, 1]")
        if self.allocation is not None and self.allocation < 0:
            raise ValueError("member allocation must be non-negative")
        return self


class RiskBudget(BaseModel):
    """Phase-1 simple-cap risk budget at the basket level."""

    model_config = ConfigDict(extra="forbid")

    max_position_fraction: Decimal | None = Field(
        default=None, description="Simple cap on total position fraction in (0, 1]."
    )
    max_loss: Decimal | None = Field(default=None, description="Absolute loss cap (INR).")

    @model_validator(mode="after")
    def _validate_caps(self) -> Self:
        if self.max_position_fraction is not None and not (
            Decimal("0") < self.max_position_fraction <= Decimal("1")
        ):
            raise ValueError(
                "risk_budget.max_position_fraction must be in the open unit interval (0, 1]"
            )
        if self.max_loss is not None and self.max_loss < 0:
            raise ValueError("risk_budget.max_loss must be non-negative")
        return self


class BasketManifest(BaseModel):
    """A group of strategy versions run as one logical unit."""

    model_config = ConfigDict(extra="forbid")

    basket_name: str = Field(pattern=r"^[a-z0-9_]+$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    combined_capital: Decimal = Field(gt=Decimal(0))
    member_strategies: list[MemberStrategyRef] = Field(min_length=1)
    risk_budget: RiskBudget = Field(default_factory=RiskBudget)

    @model_validator(mode="after")
    def _allocations_within_combined_capital(self) -> Self:
        weights = [member.weight for member in self.member_strategies if member.weight is not None]
        allocations = [
            member.allocation for member in self.member_strategies if member.allocation is not None
        ]
        if weights and allocations:
            raise ValueError(
                "basket members must all use the same mode: either weight or absolute allocation"
            )
        if weights:
            total = sum(weights, Decimal(0))
            if total > Decimal(1):
                raise ValueError(
                    f"member weights sum to {total} which exceeds the basket budget of 1.0"
                )
        else:
            total = sum(allocations, Decimal(0))
            if total > self.combined_capital:
                raise ValueError(
                    f"member allocations sum to {total} which exceeds "
                    f"combined_capital {self.combined_capital}"
                )
        return self

    # -- loading -------------------------------------------------------------
    @classmethod
    def from_toml(cls, text: str) -> Self:
        return cls.model_validate(tomllib.loads(text))

    @classmethod
    def load_toml(cls, path: str | Path) -> Self:
        return cls.from_toml(Path(path).read_text(encoding="utf-8"))


def optimize_allocations(basket: BasketManifest) -> list[Decimal]:
    """Size member capital under the basket ``RiskBudget`` caps.

    Naive sizing is ``weight * combined_capital`` (weight mode) or the
    absolute ``allocation`` (allocation mode). The risk budget then scales:

    - ``max_position_fraction``: the total position fraction never exceeds
      the cap, and no single member exceeds it.
    - ``max_loss``: worst case (a 100% loss of deployed capital) never
      exceeds the absolute cap, so total deployment <= ``max_loss``.

    A full allocation-objective optimizer (``tantra-ledger-allocation``) is
    a future cross-repo integration (gap 0005); this is the in-repo cap math.
    """
    capital = basket.combined_capital
    members = basket.member_strategies
    naive: list[Decimal] = [
        member.weight * capital
        if member.weight is not None
        else (member.allocation if member.allocation is not None else Decimal(0))
        for member in members
    ]
    fractions = [
        (member.weight if member.weight is not None else naive[i] / capital)
        for i, member in enumerate(members)
    ]
    scale = Decimal(1)
    max_pos = basket.risk_budget.max_position_fraction
    if max_pos is not None:
        total = sum(fractions, Decimal(0))
        if total > max_pos:
            scale = min(scale, max_pos / total)
        for fraction in fractions:
            if fraction > max_pos:
                scale = min(scale, max_pos / fraction)
    max_loss = basket.risk_budget.max_loss
    if max_loss is not None:
        total_naive = sum(naive, Decimal(0))
        if total_naive > max_loss:
            scale = min(scale, max_loss / total_naive)
    return [(value * scale).quantize(Decimal("0.01")) for value in naive]
