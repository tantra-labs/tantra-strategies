"""tantra-strategies — Production Strategy SDK & Declarative Step Catalog.

Tier 6C bounded context. Jesse-style strategy authoring with declarative
``Parameter`` descriptors, ``decimal.Decimal`` arithmetic, and a deterministic
simulated context for research-live parity testing.
"""

from __future__ import annotations

from tantra_strategies._compat import VYAAPAAR_AVAILABLE
from tantra_strategies.manifest import (
    BasketManifest,
    CapitalAllocation,
    InstrumentSelector,
    MemberStrategyRef,
    ParameterSpec,
    PromotionRecord,
    PromotionStatus,
    RiskBudget,
    StrategyManifest,
)
from tantra_strategies.sdk import (
    Bar,
    OrderEvent,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    Parameter,
    SimulatedContext,
    Strategy,
    TimeInForce,
)
from tantra_strategies.strategies.arbitrage import CashFuturesArbitrage
from tantra_strategies.strategies.execution import TWAPSlicer, VWAPSlicer
from tantra_strategies.strategies.market_making import MarketMakingStrategy
from tantra_strategies.strategies.mean_reversion import BollingerMeanReversion
from tantra_strategies.strategies.options import CoveredCallWriter
from tantra_strategies.strategies.quoting import QuotingStrategy
from tantra_strategies.strategies.risk_parity import RiskParity
from tantra_strategies.strategies.sizing import FixedFractional
from tantra_strategies.strategies.turtle import TurtleBreakout

__version__ = "0.1.0"

__all__ = [
    "VYAAPAAR_AVAILABLE",
    "Bar",
    "BasketManifest",
    "BollingerMeanReversion",
    "CapitalAllocation",
    "CashFuturesArbitrage",
    "CoveredCallWriter",
    "FixedFractional",
    "InstrumentSelector",
    "MarketMakingStrategy",
    "MemberStrategyRef",
    "OrderEvent",
    "OrderRequest",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "Parameter",
    "ParameterSpec",
    "PromotionRecord",
    "PromotionStatus",
    "QuotingStrategy",
    "RiskBudget",
    "RiskParity",
    "SimulatedContext",
    "Strategy",
    "StrategyManifest",
    "TWAPSlicer",
    "TimeInForce",
    "TurtleBreakout",
    "VWAPSlicer",
    "__version__",
]
