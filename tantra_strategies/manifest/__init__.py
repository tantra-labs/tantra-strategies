"""Versioned strategy manifests & basket strategies (plan 0001, Layer 3).

Phase 1: :class:`StrategyManifest` sidecars. Phase 2: :class:`BasketManifest`.
Phase 3: the :class:`PromotionStatus` workflow.
"""

from tantra_strategies.manifest.basket import (
    BasketManifest,
    MemberStrategyRef,
    RiskBudget,
    optimize_allocations,
)
from tantra_strategies.manifest.basket_run import BasketRunResult, RiskBudgetViolation, run_basket
from tantra_strategies.manifest.params import ParameterSpec
from tantra_strategies.manifest.strategy import (
    CapitalAllocation,
    InstrumentSelector,
    StrategyManifest,
)
from tantra_strategies.manifest.version import PROMOTION_ORDER, PromotionRecord, PromotionStatus

__all__ = [
    "PROMOTION_ORDER",
    "BasketManifest",
    "BasketRunResult",
    "CapitalAllocation",
    "InstrumentSelector",
    "MemberStrategyRef",
    "ParameterSpec",
    "PromotionRecord",
    "PromotionStatus",
    "RiskBudget",
    "RiskBudgetViolation",
    "StrategyManifest",
    "optimize_allocations",
    "run_basket",
]
