"""Ported StockSharp strategy families (Quoting, Arbitrage, Market Making,
Mean Reversion, Turtle, Risk Parity) and execution slicers."""

from tantra_strategies.strategies.alpha30 import Alpha30Factor
from tantra_strategies.strategies.arbitrage import CashFuturesArbitrage
from tantra_strategies.strategies.composite_signal import CompositeSignalStrategy
from tantra_strategies.strategies.elephant_edge import ElephantEdgeStrategy
from tantra_strategies.strategies.equal_weight import EqualWeight
from tantra_strategies.strategies.execution import TWAPSlicer, VWAPSlicer
from tantra_strategies.strategies.market_making import MarketMakingStrategy
from tantra_strategies.strategies.mean_reversion import BollingerMeanReversion
from tantra_strategies.strategies.options import CoveredCallWriter
from tantra_strategies.strategies.quoting import QuotingStrategy
from tantra_strategies.strategies.risk_parity import RiskParity
from tantra_strategies.strategies.sizing import FixedFractional
from tantra_strategies.strategies.turtle import TurtleBreakout

__all__ = [
    "Alpha30Factor",
    "BollingerMeanReversion",
    "CashFuturesArbitrage",
    "CompositeSignalStrategy",
    "CoveredCallWriter",
    "ElephantEdgeStrategy",
    "EqualWeight",
    "FixedFractional",
    "MarketMakingStrategy",
    "QuotingStrategy",
    "RiskParity",
    "TWAPSlicer",
    "TurtleBreakout",
    "VWAPSlicer",
]
