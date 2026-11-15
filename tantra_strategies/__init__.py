"""tantra-strategies — Production Strategy SDK & Declarative Step Catalog.

Tier 6C bounded context. Jesse-style strategy authoring with declarative
``Parameter`` descriptors, ``decimal.Decimal`` arithmetic, and a deterministic
simulated context for research-live parity testing.
"""

from __future__ import annotations

from tantra_strategies._compat import VYAAPAAR_AVAILABLE
from tantra_strategies.manifest import (
    BasketManifest,
    BasketRunResult,
    CapitalAllocation,
    InstrumentSelector,
    MemberStrategyRef,
    ParameterSpec,
    PromotionRecord,
    PromotionStatus,
    RiskBudget,
    RiskBudgetViolation,
    StrategyManifest,
    optimize_allocations,
    run_basket,
)
from tantra_strategies.sdk import (
    Bar,
    ExecutionGateway,
    Level,
    LevelKind,
    LevelMap,
    LevelSide,
    LevelsUnavailable,
    LiveContext,
    MarketDataFeed,
    OptionLeg,
    OptionsSnapshot,
    OptionsUnavailable,
    OrderEvent,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    Parameter,
    PositionIntent,
    SignalKind,
    SimulatedContext,
    StopProtection,
    StopUpdate,
    Strategy,
    StrategySignal,
    Tick,
    TimeInForce,
    TrailMode,
)
from tantra_strategies.strategies.arbitrage import CashFuturesArbitrage
from tantra_strategies.strategies.composite_signal import CompositeSignalStrategy
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
    "BasketRunResult",
    "BollingerMeanReversion",
    "CapitalAllocation",
    "CashFuturesArbitrage",
    "CompositeSignalStrategy",
    "CoveredCallWriter",
    "ExecutionGateway",
    "FixedFractional",
    "InstrumentSelector",
    "Level",
    "LevelKind",
    "LevelMap",
    "LevelSide",
    "LevelsUnavailable",
    "LiveContext",
    "MarketDataFeed",
    "MarketMakingStrategy",
    "MemberStrategyRef",
    "OptionLeg",
    "OptionsSnapshot",
    "OptionsUnavailable",
    "OrderEvent",
    "OrderRequest",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "Parameter",
    "ParameterSpec",
    "PositionIntent",
    "PromotionRecord",
    "PromotionStatus",
    "QuotingStrategy",
    "RiskBudget",
    "RiskBudgetViolation",
    "RiskParity",
    "SignalKind",
    "SimulatedContext",
    "StopProtection",
    "StopUpdate",
    "Strategy",
    "StrategyManifest",
    "StrategySignal",
    "TWAPSlicer",
    "Tick",
    "TimeInForce",
    "TrailMode",
    "TurtleBreakout",
    "VWAPSlicer",
    "__version__",
    "optimize_allocations",
    "run_basket",
]
