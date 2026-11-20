"""Default catalog: families, concepts, primitives, indicators, composites, detectors, recipes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal
from functools import cache
from importlib.resources import files

from tantra_library import adapters as ad
from tantra_library.composites import PredictiveRanges, ReversalBars, VidyaTrend
from tantra_library.detectors import (
    PrCenterStep,
    PrTrendRegime,
    PrZoneCloseBreak,
    PrZoneTouch,
    ReversalBarSignal,
    VidyaTrendFlip,
)
from tantra_library.indicators import (
    ATR,
    CMO,
    EMA,
    RSI,
    VIDYA,
    Alligator,
    ATRBands,
    AwesomeOscillator,
    BandsValue,
    BollingerBands,
    VolumeDeltaPct,
)
from tantra_library.model import (
    Entry,
    EntryKind,
    InputKind,
    OutputSpec,
    OutputUnit,
    ParamSpec,
    ParamType,
    ParamValue,
    Provenance,
    StreamingComputation,
    VolumeQuality,
)
from tantra_library.primitives import (
    RMA,
    SMA,
    SOURCES,
    Highest,
    LinReg,
    Lowest,
    SwingPivot,
    TrueRange,
    UpDownVolume,
    source_value,
)
from tantra_library.registry import Registry

P = Mapping[str, ParamValue]
Maker = Callable[[P], StreamingComputation]
_PRICE, _EVENT, _STATE = OutputUnit.PRICE, OutputUnit.EVENT, OutputUnit.STATE


def _i(p: P, k: str) -> int:
    return int(p[k])


def _d(p: P, k: str) -> Decimal:
    v = p[k]
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _s(p: P, k: str) -> str:
    return str(p[k])


def _b(p: P, k: str) -> bool:
    return bool(p[k])


def _int(name: str, default: int, desc: str, lo: int = 1, hi: int | None = None) -> ParamSpec:
    return ParamSpec(
        name,
        ParamType.INT,
        default,
        desc,
        Decimal(lo),
        None if hi is None else Decimal(hi),
    )


def _dec(name: str, default: str, desc: str, lo: str = "0", hi: str | None = None) -> ParamSpec:
    return ParamSpec(
        name,
        ParamType.DECIMAL,
        Decimal(default),
        desc,
        Decimal(lo),
        None if hi is None else Decimal(hi),
    )


def _src(default: str = "close") -> ParamSpec:
    return ParamSpec("source", ParamType.ENUM, default, "price source", choices=SOURCES)


def _norm() -> ParamSpec:
    return ParamSpec(
        "normalization",
        ParamType.ENUM,
        "average",
        "delta normalisation",
        choices=("average", "total"),
    )


def _bool(name: str, default: bool, desc: str) -> ParamSpec:
    return ParamSpec(name, ParamType.BOOL, default, desc)


def _outs(*specs: tuple[str, OutputUnit, str]) -> tuple[OutputSpec, ...]:
    return tuple(OutputSpec(n, u, d) for n, u, d in specs)


def _concept_body(slug: str) -> str:
    return (files("tantra_library") / "concepts" / f"{slug}.md").read_text(encoding="utf-8")


_FAMILIES = {
    "volatility": "Measures of how far price travels per bar or window.",
    "trend": "Direction and persistence of price movement.",
    "momentum": "Speed and acceleration of price changes.",
    "volume": "Participation and order-flow proxies derived from volume.",
    "support-resistance": "Price levels where reactions or breaks cluster.",
    "price-action": "Bar-pattern and swing-structure reading.",
}

# (slug, title, summary, family)
_CONCEPTS = (
    ("atr", "Average True Range", "Smoothed per-bar price range.", "volatility"),
    ("volatility-range", "Volatility Range", "ATR-stepped, frozen range bands.", "volatility"),
    ("adaptive-ma", "Adaptive Moving Average", "Averages whose speed adapts.", "trend"),
    ("momentum-oscillator", "Momentum Oscillator", "Bounded or centred momentum.", "momentum"),
    ("volume-delta", "Volume Delta", "Up-bar versus down-bar volume.", "volume"),
    ("reversal-bar", "Reversal Bar", "Exhaustion bar that closes against the run.", "price-action"),
    ("alligator", "Alligator", "Three shifted smoothed averages.", "trend"),
    (
        "support-resistance",
        "Support and Resistance",
        "Levels price reacts to.",
        "support-resistance",
    ),
    ("swing-structure", "Swing Structure", "Confirmed pivots and extremes.", "price-action"),
    ("trend-pullback", "Trend Pullback", "Entering with the trend on a dip.", "trend"),
    ("breakout", "Breakout", "Closing beyond a pinned level.", "support-resistance"),
    ("r-multiple", "R-Multiple", "Reward measured in units of initial risk.", "price-action"),
)

_PR_PROV = Provenance(
    "LuxAlgo — Predictive Ranges (open-source on TradingView, 2023); clean-room "
    "reimplementation for non-commercial research",
    "https://www.tradingview.com/script/lIdNGLiV-Predictive-Ranges-LuxAlgo/",
)


def _pr_params() -> tuple[ParamSpec, ...]:
    return (
        _int("length", 200, "ATR length", 2),
        _dec("factor", "6", "ATR multiplier for the center step", "0.1", "50"),
        _src(),
    )


def _pr_args(p: P) -> tuple[int, Decimal, str]:
    return _i(p, "length"), _d(p, "factor"), _s(p, "source")


def _vt_params() -> tuple[ParamSpec, ...]:
    return (
        _int("length", 10, "VIDYA length"),
        _int("momentum", 20, "CMO momentum window"),
        _int("smoothing", 15, "VIDYA smoothing (0 = none)", 0),
        _int("atr_length", 200, "ATR length for the bands"),
        _dec("band_multiplier", "2", "ATR band multiplier"),
        _norm(),
    )


def _vt_args(p: P) -> tuple[int, int, int, int, Decimal, str]:
    return (
        _i(p, "length"),
        _i(p, "momentum"),
        _i(p, "smoothing"),
        _i(p, "atr_length"),
        _d(p, "band_multiplier"),
        _s(p, "normalization"),
    )


_PR_OUT = _outs(
    ("r2", _PRICE, "upper outer band"),
    ("r1", _PRICE, "upper inner band"),
    ("center", _PRICE, "stepped center line"),
    ("s1", _PRICE, "lower inner band"),
    ("s2", _PRICE, "lower outer band"),
    ("center_step", _STATE, "+1 / -1 when the center stepped this bar, else 0"),
)
_VT_OUT = _outs(
    ("vidya", _PRICE, "VIDYA line"),
    ("upper", _PRICE, "upper ATR band"),
    ("lower", _PRICE, "lower ATR band"),
    ("trend_line", _PRICE, "active trailing band"),
    ("trend", _STATE, "+1 up, -1 down, 0 undetermined"),
    ("flipped", _EVENT, "+1 / -1 on the bar the trend flipped"),
    ("up_volume", OutputUnit.VOLUME, "up-bar volume since the flip"),
    ("down_volume", OutputUnit.VOLUME, "down-bar volume since the flip"),
    ("delta_pct", OutputUnit.PERCENT, "volume delta percent since the flip"),
)
_RB_PARAMS = (
    _int("lookback", 3, "bars of lower highs / higher lows required"),
    _bool("require_alligator", True, "bar must reach the Alligator"),
    _bool("ao_filter", False, "require Awesome Oscillator turning against the move"),
)
_RB_OUT = _outs(
    ("bullish", _EVENT, "bullish reversal bar"),
    ("bearish", _EVENT, "bearish reversal bar"),
    ("bull_trigger", _PRICE, "high of a bullish reversal bar"),
    ("bear_trigger", _PRICE, "low of a bearish reversal bar"),
)


def _prims() -> list[Entry]:
    P_ = EntryKind.PRIMITIVE

    def e(
        id_: str,
        title: str,
        summ: str,
        params: tuple[ParamSpec, ...],
        outs: tuple[OutputSpec, ...],
        fac: Maker,
        concepts: tuple[str, ...],
        inputs: InputKind = InputKind.OHLC,
        vq: VolumeQuality = VolumeQuality.NONE,
        aliases: tuple[str, ...] = (),
    ) -> Entry:
        return Entry(
            id_,
            P_,
            title,
            summ,
            concepts=concepts,
            params=params,
            outputs=outs,
            inputs=inputs,
            volume_quality=vq,
            aliases=aliases,
            factory=fac,
        )

    per = _int("period", 14, "window length")
    return [
        e(
            "prim.true-range",
            "True Range",
            "Per-bar range including the prior close gap.",
            (),
            _outs(("true_range", _PRICE, "true range")),
            lambda p: ad.from_bar(TrueRange(), "true_range"),
            ("concept.atr",),
            aliases=("TR",),
        ),
        e(
            "prim.rma",
            "RMA (Wilder)",
            "Wilder's smoothed moving average.",
            (per, _src()),
            _outs(("rma", _PRICE, "smoothed value")),
            lambda p: ad.from_source(RMA(_i(p, "period")), "rma", _s(p, "source")),
            ("concept.atr",),
            aliases=("SMMA", "Wilder MA"),
        ),
        e(
            "prim.sma",
            "SMA",
            "Simple moving average.",
            (per, _src()),
            _outs(("sma", _PRICE, "average")),
            lambda p: ad.from_source(SMA(_i(p, "period")), "sma", _s(p, "source")),
            ("concept.adaptive-ma",),
            aliases=("Simple Moving Average",),
        ),
        e(
            "prim.highest",
            "Highest",
            "Rolling maximum.",
            (per, _src("high")),
            _outs(("highest", _PRICE, "rolling max")),
            lambda p: ad.from_source(Highest(_i(p, "period")), "highest", _s(p, "source")),
            ("concept.swing-structure",),
            aliases=("Donchian high",),
        ),
        e(
            "prim.lowest",
            "Lowest",
            "Rolling minimum.",
            (per, _src("low")),
            _outs(("lowest", _PRICE, "rolling min")),
            lambda p: ad.from_source(Lowest(_i(p, "period")), "lowest", _s(p, "source")),
            ("concept.swing-structure",),
            aliases=("Donchian low",),
        ),
        e(
            "prim.swing-pivot",
            "Swing Pivot",
            "Pivot high/low confirmed after `right` bars.",
            (_int("left", 5, "bars to the left"), _int("right", 5, "bars to the right")),
            _outs(
                ("pivot_high", _PRICE, "confirmed pivot high"),
                ("pivot_low", _PRICE, "confirmed pivot low"),
            ),
            lambda p: ad.from_tuple(
                SwingPivot(_i(p, "left"), _i(p, "right")), ("pivot_high", "pivot_low")
            ),
            ("concept.swing-structure", "concept.support-resistance"),
            aliases=("Fractal",),
        ),
        e(
            "prim.up-down-volume",
            "Up/Down Volume",
            "Splits bar volume by candle direction.",
            (),
            _outs(
                ("up_volume", OutputUnit.VOLUME, "volume of up bars"),
                ("down_volume", OutputUnit.VOLUME, "volume of down bars"),
            ),
            lambda p: ad.from_tuple(UpDownVolume(), ("up_volume", "down_volume")),
            ("concept.volume-delta",),
            InputKind.OHLCV,
            VolumeQuality.REAL,
        ),
        e(
            "prim.linreg",
            "Linear Regression",
            "Least-squares slope and fitted value.",
            (_int("period", 20, "window length", 2), _src()),
            _outs(("slope", OutputUnit.RATIO, "slope per bar"), ("fitted", _PRICE, "fitted value")),
            lambda p: ad.from_tuple(LinReg(_i(p, "period")), ("slope", "fitted"), _s(p, "source")),
            ("concept.momentum-oscillator",),
            aliases=("LSMA",),
        ),
    ]


def _bollinger(p: P) -> StreamingComputation:
    src = _s(p, "source")
    return ad.StreamAdapter(
        BollingerBands(_i(p, "period"), _d(p, "deviations")),
        lambda o, bar: _bands(o.update(source_value(bar, src))),
    )


def _bands(v: BandsValue | None) -> dict[str, Decimal | None]:
    if v is None:
        return {"upper": None, "middle": None, "lower": None}
    return {"upper": v.upper, "middle": v.middle, "lower": v.lower}


def _indicators() -> list[Entry]:
    K = EntryKind.INDICATOR

    def e(
        id_: str,
        title: str,
        summ: str,
        params: tuple[ParamSpec, ...],
        outs: tuple[OutputSpec, ...],
        fac: Maker,
        concepts: tuple[str, ...],
        deps: tuple[str, ...] = (),
        related: tuple[str, ...] = (),
        vq: VolumeQuality = VolumeQuality.NONE,
        aliases: tuple[str, ...] = (),
        family: str | None = None,
    ) -> Entry:
        return Entry(
            id_,
            K,
            title,
            summ,
            family=family,
            concepts=concepts,
            depends_on=deps,
            params=params,
            outputs=outs,
            inputs=InputKind.OHLCV if vq is VolumeQuality.REAL else InputKind.OHLC,
            volume_quality=vq,
            aliases=aliases,
            related=related,
            factory=fac,
        )

    return [
        e(
            "ind.atr",
            "Average True Range",
            "Wilder-smoothed true range.",
            (_int("period", 14, "ATR length"),),
            _outs(("atr", _PRICE, "ATR")),
            lambda p: ad.from_bar(ATR(_i(p, "period")), "atr"),
            ("concept.atr",),
            ("prim.true-range", "prim.rma"),
            ("ind.atr-bands",),
            aliases=("ATR",),
            family="family.volatility",
        ),
        e(
            "ind.atr-bands",
            "ATR Bands",
            "Moving price source +/- ATR multiple.",
            (_int("period", 14, "ATR length"), _dec("multiplier", "2", "band multiplier"), _src()),
            _outs(
                ("upper", _PRICE, "upper band"),
                ("middle", _PRICE, "middle"),
                ("lower", _PRICE, "lower band"),
            ),
            lambda p: ad.from_dataclass(
                ATRBands(_i(p, "period"), _d(p, "multiplier"), _s(p, "source")),
                ("upper", "middle", "lower"),
            ),
            ("concept.atr", "concept.volatility-range"),
            ("ind.atr",),
            ("ind.predictive-ranges",),
            family="family.volatility",
        ),
        e(
            "ind.ema",
            "Exponential Moving Average",
            "Exponentially weighted average seeded with the first value.",
            (_int("period", 20, "EMA length"), _src()),
            _outs(("ema", _PRICE, "EMA")),
            lambda p: ad.from_source(EMA(_i(p, "period")), "ema", _s(p, "source")),
            ("concept.adaptive-ma",),
            aliases=("EMA",),
            family="family.trend",
        ),
        e(
            "ind.rsi",
            "Relative Strength Index",
            "Wilder RSI scaled to 0-100.",
            (_int("period", 14, "RSI length"), _src()),
            _outs(("rsi", OutputUnit.PERCENT, "RSI")),
            lambda p: ad.from_source(RSI(_i(p, "period")), "rsi", _s(p, "source")),
            ("concept.momentum-oscillator",),
            aliases=("RSI",),
            family="family.momentum",
        ),
        e(
            "ind.bollinger-bands",
            "Bollinger Bands",
            "SMA +/- standard-deviation bands.",
            (
                _int("period", 20, "window length"),
                _dec("deviations", "2", "standard-deviation multiplier"),
                _src(),
            ),
            _outs(
                ("upper", _PRICE, "upper band"),
                ("middle", _PRICE, "middle"),
                ("lower", _PRICE, "lower band"),
            ),
            _bollinger,
            ("concept.volatility-range",),
            aliases=("BBANDS", "Bollinger"),
            family="family.volatility",
        ),
        e(
            "ind.cmo",
            "Chande Momentum Oscillator",
            "Up/down momentum scaled to +/-100.",
            (_int("period", 9, "window length"), _src()),
            _outs(("cmo", OutputUnit.PERCENT, "CMO")),
            lambda p: ad.from_source(CMO(_i(p, "period")), "cmo", _s(p, "source")),
            ("concept.momentum-oscillator",),
            related=("ind.vidya",),
            aliases=("CMO",),
            family="family.momentum",
        ),
        e(
            "ind.vidya",
            "VIDYA",
            "Variable Index Dynamic Average driven by |CMO|.",
            (
                _int("length", 10, "base length"),
                _int("momentum", 20, "CMO window"),
                _int("smoothing", 0, "extra smoothing (0 = none)", 0),
                _src(),
            ),
            _outs(("vidya", _PRICE, "VIDYA")),
            lambda p: ad.from_source(
                VIDYA(_i(p, "length"), _i(p, "momentum"), _i(p, "smoothing")),
                "vidya",
                _s(p, "source"),
            ),
            ("concept.adaptive-ma",),
            ("ind.cmo",),
            ("ind.cmo",),
            aliases=("VIDYA",),
            family="family.trend",
        ),
        e(
            "ind.volume-delta-pct",
            "Volume Delta Percent",
            "Windowed up-minus-down volume as a percentage.",
            (_int("window", 20, "bars in window"), _norm()),
            _outs(("delta_pct", OutputUnit.PERCENT, "volume delta percent")),
            lambda p: ad.from_bar(
                VolumeDeltaPct(_i(p, "window"), _s(p, "normalization")), "delta_pct"
            ),
            ("concept.volume-delta",),
            ("prim.up-down-volume",),
            vq=VolumeQuality.REAL,
            family="family.volume",
        ),
        e(
            "ind.alligator",
            "Alligator",
            "Jaw, teeth and lips: shifted Wilder averages.",
            (
                _int("jaw", 13, "jaw period"),
                _int("teeth", 8, "teeth period"),
                _int("lips", 5, "lips period"),
                _int("jaw_shift", 8, "jaw shift", 0),
                _int("teeth_shift", 5, "teeth shift", 0),
                _int("lips_shift", 3, "lips shift", 0),
            ),
            _outs(("jaw", _PRICE, "jaw"), ("teeth", _PRICE, "teeth"), ("lips", _PRICE, "lips")),
            lambda p: ad.from_dataclass(
                Alligator(
                    _i(p, "jaw"),
                    _i(p, "teeth"),
                    _i(p, "lips"),
                    _i(p, "jaw_shift"),
                    _i(p, "teeth_shift"),
                    _i(p, "lips_shift"),
                ),
                ("jaw", "teeth", "lips"),
            ),
            ("concept.alligator",),
            ("prim.rma",),
            family="family.trend",
        ),
        e(
            "ind.awesome-oscillator",
            "Awesome Oscillator",
            "Fast minus slow SMA of median price.",
            (_int("fast", 5, "fast period"), _int("slow", 34, "slow period")),
            _outs(("ao", _PRICE, "oscillator value")),
            lambda p: ad.from_bar(AwesomeOscillator(_i(p, "fast"), _i(p, "slow")), "ao"),
            ("concept.momentum-oscillator",),
            ("prim.sma",),
            aliases=("AO",),
            family="family.momentum",
        ),
    ]


def _composites() -> list[Entry]:
    K = EntryKind.COMPOSITE
    return [
        Entry(
            "ind.predictive-ranges",
            K,
            "Predictive Ranges",
            "ATR-stepped center line with frozen half-ATR bands.",
            family="family.volatility",
            concepts=("concept.volatility-range", "concept.support-resistance"),
            depends_on=("ind.atr",),
            params=_pr_params(),
            outputs=_PR_OUT,
            related=("ind.atr-bands",),
            provenance=_PR_PROV,
            factory=lambda p: ad.from_dataclass(
                PredictiveRanges(*_pr_args(p)), ("r2", "r1", "center", "s1", "s2", "center_step")
            ),
        ),
        Entry(
            "ind.vidya-trend",
            K,
            "VIDYA Trend with Volume Delta",
            "VIDYA with ATR bands, trend flips and volume delta since the flip.",
            family="family.trend",
            concepts=("concept.adaptive-ma", "concept.volume-delta"),
            depends_on=("ind.vidya", "ind.atr", "ind.volume-delta-pct"),
            params=_vt_params(),
            outputs=_VT_OUT,
            inputs=InputKind.OHLCV,
            volume_quality=VolumeQuality.REAL,
            provenance=Provenance(
                "BigBeluga — Volumatic VIDYA",
                "https://www.tradingview.com/script/llhVjhA5-Volumatic-Variable-Index-Dynamic-Average-BigBeluga/",
            ),
            factory=lambda p: ad.from_dataclass(
                VidyaTrend(*_vt_args(p)),
                (
                    "vidya",
                    "upper",
                    "lower",
                    "trend_line",
                    "trend",
                    "flipped",
                    "up_volume",
                    "down_volume",
                    "delta_pct",
                ),
            ),
        ),
        Entry(
            "ind.reversal-bars",
            K,
            "Reversal Bars",
            "Bullish/bearish reversal bars after a run of lower highs or higher lows.",
            family="family.price-action",
            concepts=("concept.reversal-bar", "concept.alligator"),
            depends_on=("ind.alligator", "ind.awesome-oscillator", "prim.highest", "prim.lowest"),
            params=_RB_PARAMS,
            outputs=_RB_OUT,
            provenance=Provenance(
                "Skyrexio — Bullish/Bearish Reversal Bars",
                "https://www.tradingview.com/script/AQcWYxYa-Bullish-Bearish-Reversal-Bars-Indicator-Skyrexio/",
                "rules reconstructed from the published description; "
                "MFI 'squat' filter not implemented",
            ),
            factory=lambda p: ad.from_dataclass(
                ReversalBars(_i(p, "lookback"), _b(p, "require_alligator"), _b(p, "ao_filter")),
                ("bullish", "bearish", "bull_trigger", "bear_trigger"),
            ),
        ),
    ]


def _detectors() -> list[Entry]:
    K = EntryKind.DETECTOR
    dep = ("ind.predictive-ranges",)

    def e(
        id_: str,
        title: str,
        summ: str,
        params: tuple[ParamSpec, ...],
        outs: tuple[OutputSpec, ...],
        fac: Maker,
        concepts: tuple[str, ...],
        deps: tuple[str, ...],
        family: str,
        vq: VolumeQuality = VolumeQuality.NONE,
    ) -> Entry:
        return Entry(
            id_,
            K,
            title,
            summ,
            family=family,
            concepts=concepts,
            depends_on=deps,
            params=params,
            outputs=outs,
            inputs=InputKind.OHLCV if vq is VolumeQuality.REAL else InputKind.OHLC,
            volume_quality=vq,
            factory=fac,
        )

    return [
        e(
            "det.pr-center-step",
            "Predictive Ranges Center Step",
            "Fires when the center steps.",
            _pr_params(),
            _outs(
                ("step_up", _EVENT, "center stepped up"),
                ("step_down", _EVENT, "stepped down"),
                ("center", _PRICE, "center line"),
            ),
            lambda p: ad.from_dataclass(
                PrCenterStep(*_pr_args(p)), ("step_up", "step_down", "center")
            ),
            ("concept.volatility-range",),
            dep,
            "family.volatility",
        ),
        e(
            "det.pr-trend-regime",
            "Predictive Ranges Trend Regime",
            "+1 / -1 after `steps` consecutive same-direction center steps.",
            (*_pr_params(), _int("steps", 2, "consecutive steps required")),
            _outs(("regime", _STATE, "+1 up, -1 down, 0 neutral")),
            lambda p: ad.from_dataclass(PrTrendRegime(*_pr_args(p), _i(p, "steps")), ("regime",)),
            ("concept.volatility-range", "concept.trend-pullback"),
            dep,
            "family.trend",
        ),
        e(
            "det.pr-zone-touch",
            "Predictive Ranges Zone Touch",
            "Bar low reaches pinned s1 or bar high reaches pinned r1.",
            _pr_params(),
            _outs(
                ("support_touch", _EVENT, "low <= pinned s1"),
                ("resistance_touch", _EVENT, "high >= pinned r1"),
                ("s1", _PRICE, "pinned s1"),
                ("r1", _PRICE, "pinned r1"),
            ),
            lambda p: ad.from_dataclass(
                PrZoneTouch(*_pr_args(p)), ("support_touch", "resistance_touch", "s1", "r1")
            ),
            ("concept.support-resistance", "concept.trend-pullback"),
            dep,
            "family.support-resistance",
        ),
        e(
            "det.pr-zone-close-break",
            "Predictive Ranges Zone Close Break",
            "Close beyond pinned r1 / s1 on a bar without a center step.",
            _pr_params(),
            _outs(
                ("break_up", _EVENT, "close above pinned r1"),
                ("break_down", _EVENT, "close below pinned s1"),
                ("level", _PRICE, "pinned level that broke"),
            ),
            lambda p: ad.from_dataclass(
                PrZoneCloseBreak(*_pr_args(p)), ("break_up", "break_down", "level")
            ),
            ("concept.breakout",),
            dep,
            "family.support-resistance",
        ),
        e(
            "det.reversal-bar",
            "Reversal Bar Signal",
            "Bullish/bearish reversal bar events.",
            _RB_PARAMS,
            _RB_OUT,
            lambda p: ad.from_dataclass(
                ReversalBarSignal(
                    _i(p, "lookback"), _b(p, "require_alligator"), _b(p, "ao_filter")
                ),
                ("bullish", "bearish", "bull_trigger", "bear_trigger"),
            ),
            ("concept.reversal-bar",),
            ("ind.reversal-bars",),
            "family.price-action",
        ),
        e(
            "det.vidya-trend-flip",
            "VIDYA Trend Flip",
            "Fires on VIDYA trend flips.",
            _vt_params(),
            _outs(
                ("flip_up", _EVENT, "flipped up"),
                ("flip_down", _EVENT, "flipped down"),
                ("delta_pct", OutputUnit.PERCENT, "volume delta percent"),
            ),
            lambda p: ad.from_dataclass(
                VidyaTrendFlip(*_vt_args(p)), ("flip_up", "flip_down", "delta_pct")
            ),
            ("concept.adaptive-ma", "concept.volume-delta"),
            ("ind.vidya-trend",),
            "family.trend",
            VolumeQuality.REAL,
        ),
    ]


_PULLBACK_MD = """\
## Rules

| Step | Long | Short |
|---|---|---|
| Filter | `det.pr-trend-regime` = +1 (steps=2) | = -1 |
| Trigger | `det.pr-zone-touch` support_touch AND `det.reversal-bar` bullish, same bar | resistance_touch AND bearish |
| Entry | break above `bull_trigger` on the next bar | break below `bear_trigger` |
| Stop | below pinned s2, or bar low - buffer * ATR, whichever is lower | mirror |
| Target | r1 of the active range | s1 |

Implementation: `tantra_strategies.strategies.predictive_ranges.PrTrendPullbackStrategy`.
"""  # noqa: E501

_BREAKOUT_MD = """\
## Rules

| Step | Long | Short |
|---|---|---|
| Filter | `ind.vidya-trend` trend = +1 AND delta_pct >= +30 (normalization average) | -1 and <= -30 |
| Trigger | `det.pr-zone-close-break` break_up (pinned r1) or `det.pr-center-step` step_up | break_down / step_down |
| Stop | last confirmed `prim.swing-pivot` low, else pinned level - 1 * ATR | mirror |
| Target | 1.5R | 1.5R |

Implementation: `tantra_strategies.strategies.predictive_ranges.PrVidyaBreakoutStrategy`.
"""  # noqa: E501


def _recipes() -> list[Entry]:
    K = EntryKind.RECIPE
    return [
        Entry(
            "recipe.pr-trend-pullback",
            K,
            "Predictive Ranges Trend Pullback",
            "Trade pullbacks to the inner band in a stepping trend, confirmed by a reversal bar.",
            family="family.trend",
            concepts=("concept.trend-pullback", "concept.r-multiple", "concept.support-resistance"),
            depends_on=("det.pr-trend-regime", "det.pr-zone-touch", "det.reversal-bar", "ind.atr"),
            body_md=_PULLBACK_MD,
        ),
        Entry(
            "recipe.pr-vidya-breakout",
            K,
            "Predictive Ranges VIDYA Breakout",
            "Breakouts through pinned range levels filtered by VIDYA trend and volume delta.",
            family="family.support-resistance",
            concepts=("concept.breakout", "concept.r-multiple"),
            depends_on=(
                "ind.vidya-trend",
                "det.pr-zone-close-break",
                "det.pr-center-step",
                "prim.swing-pivot",
                "ind.atr",
            ),
            body_md=_BREAKOUT_MD,
        ),
    ]


def build_default_registry() -> Registry:
    reg = Registry()
    for slug, summary in _FAMILIES.items():
        reg.register(
            Entry(
                f"family.{slug}",
                EntryKind.FAMILY,
                slug.replace("-", " ").title(),
                summary,
                body_md=summary,
            )
        )
    for slug, title, summary, fam in _CONCEPTS:
        reg.register(
            Entry(
                f"concept.{slug}",
                EntryKind.CONCEPT,
                title,
                summary,
                family=f"family.{fam}",
                body_md=_concept_body(slug),
            )
        )
    for entry in (*_prims(), *_indicators(), *_composites(), *_detectors(), *_recipes()):
        reg.register(entry)
    reg.validate()
    return reg


@cache
def default_registry() -> Registry:
    return build_default_registry()
