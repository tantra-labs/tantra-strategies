"""Unified 6-layer interactive overlay scene primitives for Python strategies.

1:1 ``Decimal`` wire-compatible mirror of ``tantra-ui-charts::scene::OverlayScene``
so Python strategy simulations, agent tools, Web Canvas, TUI ``ratatui::Canvas``,
and CLI exports share one structured visual vocabulary:

1. ``signals``    — Buy/Sell/Sweep/Target markers & entry-to-exit connector rays
2. ``bands``      — Shaded zone boxes (``S1/S2/R1/R2``, ``ORB``) & level lines
3. ``stops``      — Tight/Outer-Buffer/Trailing/Breakeven stops & targets
4. ``indicators`` — Overlay & sub-pane indicator series
5. ``hints``      — Rationale pins explaining trade outcomes & saved sweeps
6. ``hedges``     — F&O / Commodity hedge strike lines & payoff summaries
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any


def _as_decimal(value: Decimal | int | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


class SceneLayerGroup(StrEnum):
    """Top-level toggleable primitive groups in an :class:`OverlayScene`."""

    SIGNALS = "signals"
    BANDS = "bands"
    STOPS = "stops"
    INDICATORS = "indicators"
    HINTS = "hints"
    HEDGES = "hedges"


@dataclass(frozen=True, slots=True)
class SceneLayerMask:
    """Boolean visibility mask across all six scene layer groups."""

    signals: bool = True
    bands: bool = True
    stops: bool = True
    indicators: bool = True
    hints: bool = True
    hedges: bool = True

    def is_visible(self, group: SceneLayerGroup) -> bool:
        return bool(getattr(self, group.value))

    def to_dict(self) -> dict[str, bool]:
        return {
            "signals": self.signals,
            "bands": self.bands,
            "stops": self.stops,
            "indicators": self.indicators,
            "hints": self.hints,
            "hedges": self.hedges,
        }


class MarkerSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class MarkerKind(StrEnum):
    BREAKOUT = "breakout"
    REVERSAL = "reversal"
    RETEST = "retest"
    STOP_LINE = "stop_line"
    SWEEP = "sweep"
    SWEEP_SAVED = "sweep_saved"
    TARGET_HIT = "target_hit"
    ELEPHANT_BAR = "elephant_bar"


@dataclass(frozen=True, slots=True)
class SignalMarkerSpec:
    """Buy/Sell/Sweep/Target marker anchored to candle index and exact price."""

    price: Decimal
    index: int
    side: MarkerSide
    kind: MarkerKind

    def __post_init__(self) -> None:
        if not isinstance(self.price, Decimal):
            object.__setattr__(self, "price", _as_decimal(self.price))
        if self.index < 0:
            raise ValueError("index must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "price": str(self.price),
            "index": self.index,
            "side": self.side.value,
            "kind": self.kind.value,
        }


@dataclass(frozen=True, slots=True)
class TradeConnectorSpec:
    """Entry-to-exit connector ray showing realized R and exit status."""

    from_index: int
    from_price: Decimal
    to_index: int
    to_price: Decimal
    side: MarkerSide
    realized_r: Decimal
    stopped_out: bool
    label: str | None = None

    def __post_init__(self) -> None:
        for name in ("from_price", "to_price", "realized_r"):
            val = getattr(self, name)
            if not isinstance(val, Decimal):
                object.__setattr__(self, name, _as_decimal(val))
        if self.to_index < self.from_index:
            raise ValueError("to_index must be >= from_index")
        if self.from_price < 0 or self.to_price < 0:
            raise ValueError("connector prices must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_index": self.from_index,
            "from_price": str(self.from_price),
            "to_index": self.to_index,
            "to_price": str(self.to_price),
            "side": self.side.value,
            "realized_r": str(self.realized_r),
            "stopped_out": self.stopped_out,
            "label": self.label,
        }


@dataclass(frozen=True, slots=True)
class ZoneBandSpec:
    """Shaded price-band geometry spanning ``x0..=x1``."""

    low: Decimal
    high: Decimal
    x0: int
    x1: int
    fill_index: int = 0
    label: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.low, Decimal):
            object.__setattr__(self, "low", _as_decimal(self.low))
        if not isinstance(self.high, Decimal):
            object.__setattr__(self, "high", _as_decimal(self.high))
        if self.high < self.low:
            raise ValueError("high must be >= low")
        if self.x1 < self.x0 or self.x0 < 0:
            raise ValueError("x0..=x1 span invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "low": str(self.low),
            "high": str(self.high),
            "x0": self.x0,
            "x1": self.x1,
            "fill_index": self.fill_index,
            "label": self.label,
        }


@dataclass(frozen=True, slots=True)
class LevelLineStyleSpec:
    dashed: bool = True
    color_index: int = 0
    line_width: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "dashed": self.dashed,
            "color_index": self.color_index,
            "line_width": self.line_width,
        }


@dataclass(frozen=True, slots=True)
class LevelLineSpec:
    """Horizontal reference level line (Equilibrium, PDH/PDL, ORB Mid)."""

    price: Decimal
    x0: int
    x1: int
    label: str | None = None
    style: LevelLineStyleSpec = field(default_factory=LevelLineStyleSpec)

    def __post_init__(self) -> None:
        if not isinstance(self.price, Decimal):
            object.__setattr__(self, "price", _as_decimal(self.price))
        if self.price < 0:
            raise ValueError("price must be >= 0")
        if self.x1 < self.x0 or self.x0 < 0:
            raise ValueError("x0..=x1 span invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "price": str(self.price),
            "x0": self.x0,
            "x1": self.x1,
            "label": self.label,
            "style": self.style.to_dict(),
        }


class StopKind(StrEnum):
    INITIAL = "initial"
    TRAILING = "trailing"
    BREAKEVEN = "breakeven"
    TARGET = "target"


@dataclass(frozen=True, slots=True)
class StopLineSpec:
    """Stop-loss / trailing / breakeven / target line segment."""

    price: Decimal
    x0: int
    x1: int
    kind: StopKind
    previous: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.price, Decimal):
            object.__setattr__(self, "price", _as_decimal(self.price))
        if self.previous is not None and not isinstance(self.previous, Decimal):
            object.__setattr__(self, "previous", _as_decimal(self.previous))
        if self.price <= 0:
            raise ValueError("stop price must be > 0")
        if self.x1 < self.x0 or self.x0 < 0:
            raise ValueError("x0..=x1 span invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "price": str(self.price),
            "x0": self.x0,
            "x1": self.x1,
            "kind": self.kind.value,
            "previous": str(self.previous) if self.previous is not None else None,
        }


@dataclass(frozen=True, slots=True)
class ChartPointSpec:
    x: Decimal
    y: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.x, Decimal):
            object.__setattr__(self, "x", _as_decimal(self.x))
        if not isinstance(self.y, Decimal):
            object.__setattr__(self, "y", _as_decimal(self.y))

    def to_dict(self) -> dict[str, str]:
        return {"x": str(self.x), "y": str(self.y)}


@dataclass(frozen=True, slots=True)
class IndicatorSeriesSpec:
    """Named indicator line series (overlay or sub-pane)."""

    name: str
    points: tuple[ChartPointSpec, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "points": [pt.to_dict() for pt in self.points],
        }


class HintSeverity(StrEnum):
    INFO = "info"
    POSITIVE = "positive"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class HintMetricSpec:
    key: str
    value: str

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key, "value": self.value}


@dataclass(frozen=True, slots=True)
class HintAnnotationSpec:
    """Interactive hint pin explaining signal/stop rationale on a candle."""

    bar_index: int
    price: Decimal
    severity: HintSeverity
    title: str
    detail: str
    metrics: tuple[HintMetricSpec, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.price, Decimal):
            object.__setattr__(self, "price", _as_decimal(self.price))
        if self.price < 0:
            raise ValueError("hint price must be >= 0")
        if self.bar_index < 0:
            raise ValueError("bar_index must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "bar_index": self.bar_index,
            "price": str(self.price),
            "severity": self.severity.value,
            "title": self.title,
            "detail": self.detail,
            "metrics": [m.to_dict() for m in self.metrics],
        }


class HedgeLegSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class HedgeOptionKind(StrEnum):
    SPOT = "spot"
    FUTURE = "future"
    CALL = "call"
    PUT = "put"


@dataclass(frozen=True, slots=True)
class HedgeLevelSpec:
    """Strike / payoff ray for F&O & Commodity hedge overlays."""

    role: str
    side: HedgeLegSide
    option_kind: HedgeOptionKind
    strike: Decimal
    x0: int
    x1: int
    breakeven: Decimal | None = None
    max_loss: Decimal | None = None
    summary: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.strike, Decimal):
            object.__setattr__(self, "strike", _as_decimal(self.strike))
        if self.breakeven is not None and not isinstance(self.breakeven, Decimal):
            object.__setattr__(self, "breakeven", _as_decimal(self.breakeven))
        if self.max_loss is not None and not isinstance(self.max_loss, Decimal):
            object.__setattr__(self, "max_loss", _as_decimal(self.max_loss))
        if self.strike <= 0:
            raise ValueError("strike must be > 0")
        if self.x1 < self.x0 or self.x0 < 0:
            raise ValueError("x0..=x1 span invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "side": self.side.value,
            "option_kind": self.option_kind.value,
            "strike": str(self.strike),
            "x0": self.x0,
            "x1": self.x1,
            "breakeven": str(self.breakeven) if self.breakeven is not None else None,
            "max_loss": str(self.max_loss) if self.max_loss is not None else None,
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class OverlayScene:
    """Immutable 6-layer graphical scene matching ``tantra-ui-charts::scene::OverlayScene``."""

    strategy_id: str
    symbol: str
    timeframe: str
    layers: SceneLayerMask = field(default_factory=SceneLayerMask)
    signals: tuple[SignalMarkerSpec, ...] = ()
    connectors: tuple[TradeConnectorSpec, ...] = ()
    bands: tuple[ZoneBandSpec, ...] = ()
    levels: tuple[LevelLineSpec, ...] = ()
    stops: tuple[StopLineSpec, ...] = ()
    indicators: tuple[IndicatorSeriesSpec, ...] = ()
    hints: tuple[HintAnnotationSpec, ...] = ()
    hedges: tuple[HedgeLevelSpec, ...] = ()

    def layer_counts(self) -> dict[str, int]:
        return {
            "signals": len(self.signals),
            "bands": len(self.bands) + len(self.levels),
            "stops": len(self.stops),
            "indicators": len(self.indicators),
            "hints": len(self.hints),
            "hedges": len(self.hedges),
        }

    def filtered_visible(self, mask: SceneLayerMask | None = None) -> OverlayScene:
        active = mask if mask is not None else self.layers
        return OverlayScene(
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            timeframe=self.timeframe,
            layers=active,
            signals=self.signals if active.signals else (),
            connectors=self.connectors if active.signals else (),
            bands=self.bands if active.bands else (),
            levels=self.levels if active.bands else (),
            stops=self.stops if active.stops else (),
            indicators=self.indicators if active.indicators else (),
            hints=self.hints if active.hints else (),
            hedges=self.hedges if active.hedges else (),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "layers": self.layers.to_dict(),
            "signals": [s.to_dict() for s in self.signals],
            "connectors": [c.to_dict() for c in self.connectors],
            "bands": [b.to_dict() for b in self.bands],
            "levels": [lvl.to_dict() for lvl in self.levels],
            "stops": [st.to_dict() for st in self.stops],
            "indicators": [ind.to_dict() for ind in self.indicators],
            "hints": [h.to_dict() for h in self.hints],
            "hedges": [hd.to_dict() for hd in self.hedges],
        }


class OverlaySceneEmitter:
    """Mutable composition hook accumulating graphical primitives during a strategy run."""

    def __init__(
        self,
        strategy_id: str,
        symbol: str,
        timeframe: str = "1m",
        layers: SceneLayerMask | None = None,
    ) -> None:
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.timeframe = timeframe
        self.layers = layers or SceneLayerMask()
        self._signals: list[SignalMarkerSpec] = []
        self._connectors: list[TradeConnectorSpec] = []
        self._bands: dict[str, ZoneBandSpec] = {}
        self._levels: dict[str, LevelLineSpec] = {}
        self._stops: list[StopLineSpec] = []
        self._indicators: dict[str, list[ChartPointSpec]] = {}
        self._hints: list[HintAnnotationSpec] = []
        self._hedges: list[HedgeLevelSpec] = []

    def reset(self, *, symbol: str | None = None, timeframe: str | None = None) -> None:
        if symbol is not None:
            self.symbol = symbol
        if timeframe is not None:
            self.timeframe = timeframe
        self._signals.clear()
        self._connectors.clear()
        self._bands.clear()
        self._levels.clear()
        self._stops.clear()
        self._indicators.clear()
        self._hints.clear()
        self._hedges.clear()

    def add_signal(
        self,
        price: Decimal | int | str,
        index: int,
        side: MarkerSide,
        kind: MarkerKind,
    ) -> SignalMarkerSpec:
        spec = SignalMarkerSpec(price=_as_decimal(price), index=index, side=side, kind=kind)
        self._signals.append(spec)
        return spec

    def add_connector(
        self,
        from_index: int,
        from_price: Decimal | int | str,
        to_index: int,
        to_price: Decimal | int | str,
        side: MarkerSide,
        realized_r: Decimal | int | str,
        stopped_out: bool,
        label: str | None = None,
    ) -> TradeConnectorSpec:
        spec = TradeConnectorSpec(
            from_index=from_index,
            from_price=_as_decimal(from_price),
            to_index=to_index,
            to_price=_as_decimal(to_price),
            side=side,
            realized_r=_as_decimal(realized_r),
            stopped_out=stopped_out,
            label=label,
        )
        self._connectors.append(spec)
        return spec

    def upsert_band(
        self,
        key: str,
        low: Decimal | int | str,
        high: Decimal | int | str,
        x0: int,
        x1: int,
        *,
        fill_index: int = 0,
        label: str | None = None,
    ) -> ZoneBandSpec:
        spec = ZoneBandSpec(
            low=_as_decimal(low),
            high=_as_decimal(high),
            x0=x0,
            x1=max(x0, x1),
            fill_index=fill_index,
            label=label,
        )
        self._bands[key] = spec
        return spec

    def upsert_level(
        self,
        key: str,
        price: Decimal | int | str,
        x0: int,
        x1: int,
        *,
        label: str | None = None,
        style: LevelLineStyleSpec | None = None,
    ) -> LevelLineSpec:
        spec = LevelLineSpec(
            price=_as_decimal(price),
            x0=x0,
            x1=max(x0, x1),
            label=label,
            style=style or LevelLineStyleSpec(),
        )
        self._levels[key] = spec
        return spec

    def add_stop(
        self,
        price: Decimal | int | str,
        x0: int,
        x1: int,
        kind: StopKind,
        *,
        previous: Decimal | int | str | None = None,
    ) -> StopLineSpec:
        spec = StopLineSpec(
            price=_as_decimal(price),
            x0=x0,
            x1=max(x0, x1),
            kind=kind,
            previous=_as_decimal(previous) if previous is not None else None,
        )
        self._stops.append(spec)
        return spec

    def record_indicator_point(
        self,
        name: str,
        bar_index: int,
        value: Decimal | int | str,
    ) -> None:
        pts = self._indicators.setdefault(name, [])
        pts.append(ChartPointSpec(x=Decimal(bar_index), y=_as_decimal(value)))

    def add_hint(
        self,
        bar_index: int,
        price: Decimal | int | str,
        severity: HintSeverity,
        title: str,
        detail: str,
        metrics: tuple[HintMetricSpec, ...] | list[HintMetricSpec] = (),
    ) -> HintAnnotationSpec:
        spec = HintAnnotationSpec(
            bar_index=bar_index,
            price=_as_decimal(price),
            severity=severity,
            title=title,
            detail=detail,
            metrics=tuple(metrics),
        )
        self._hints.append(spec)
        return spec

    def add_hedge(self, hedge: HedgeLevelSpec) -> HedgeLevelSpec:
        self._hedges.append(hedge)
        return hedge

    def emit(self) -> OverlayScene:
        series = tuple(
            IndicatorSeriesSpec(name=name, points=tuple(pts))
            for name, pts in self._indicators.items()
        )
        return OverlayScene(
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            timeframe=self.timeframe,
            layers=self.layers,
            signals=tuple(self._signals),
            connectors=tuple(self._connectors),
            bands=tuple(self._bands.values()),
            levels=tuple(self._levels.values()),
            stops=tuple(self._stops),
            indicators=series,
            hints=tuple(self._hints),
            hedges=tuple(self._hedges),
        )

    def to_dict(self) -> dict[str, Any]:
        return self.emit().to_dict()
