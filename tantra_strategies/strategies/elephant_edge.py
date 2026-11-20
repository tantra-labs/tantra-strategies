"""Elephant Edge (EE+) — multi-horizon level-fusion & outer-buffer strategy.

Implements plan `docs/plans/0001-elephant-edge-strategy.md` and Phase 2
(`Track T21.2`) generalization on the pure-Python strategy SDK. EE+ composes:

* :class:`~tantra_strategies.sdk.primitives.SessionClock` — supports intraday
  (NSE equity/F&O & MCX extended sessions), weekly expiry, monthly expiry,
  and commodity-cycle horizons via ``horizon_mode`` and ``asset_class``.
* :class:`~tantra_strategies.sdk.primitives.ElephantZonesExtractor` — builds
  Empirical support/resistance percentile bands (with 1.618x/2.618x ORE
  fallback), round-number levels, PDH/PDL/PDC, and optional OI/gamma snapping.
* ``entry_trigger_mode`` — ``"all"`` (default backwards-compatible reversals +
  breakouts + retests), ``"rejection_wick"`` (pinbars/hammers/shooting-stars/
  engulfings only), or ``"zone_touch_close"`` (clean zone touch-and-close bars).
* :class:`~tantra_strategies.sdk.primitives.OuterBufferStopPolicy` — configurable
  ``sl_mode`` (`tight_center` | `outer_edge` | `outer_atr_buffer` |
  `percentile_shield`) plus 3R partial booking + breakeven trail + 5R runner
  + 6-candle stagnation exit.
* :class:`~tantra_strategies.sdk.primitives.HedgeOverlayPolicy` — synthesizes
  Day/Weekly/Monthly/Commodity F&O hedge structures (or live-chain strikes) per
  ``hedge_mode``.
* :class:`~tantra_strategies.sdk.scene.OverlaySceneEmitter` — automatically
  emits the 6-layer ``OverlayScene`` (signals, bands, stops, indicators, hints,
  hedges) alongside ``OrderRequest`` and ``StopProtection``.

Zero floats throughout: every price, stop, band, target, and quantity is an
exact ``Decimal``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, Decimal
from itertools import pairwise
from typing import Any

from tantra_strategies.sdk import (
    AssetClass,
    Bar,
    ElephantZonesExtractor,
    EntryTriggerMode,
    HedgeMode,
    HedgeOverlayPolicy,
    HedgeRecommendationSpec,
    HintMetricSpec,
    HintSeverity,
    HorizonMode,
    Level,
    LevelKind,
    LevelMap,
    LevelSide,
    LevelsUnavailable,
    MarkerKind,
    MarkerSide,
    OptionsSnapshot,
    OptionsUnavailable,
    OrderEvent,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    OuterBufferStopPolicy,
    OverlayScene,
    OverlaySceneEmitter,
    Parameter,
    PositionIntent,
    SessionClock,
    SignalKind,
    SlMode,
    StopKind,
    StopPlan,
    StopProtection,
    StopUpdate,
    Strategy,
    StrategyContext,
    StrategySignal,
    TrailMode,
    ZoneExtractionContext,
    ZoneExtractor,
)

IST = timezone(timedelta(hours=5, minutes=30))

ANCHOR_KINDS: frozenset[LevelKind] = frozenset(
    {
        LevelKind.OI_WALL_CALL,
        LevelKind.OI_WALL_PUT,
        LevelKind.GAMMA_WALL_CALL,
        LevelKind.GAMMA_WALL_PUT,
        LevelKind.PREVIOUS_DAY_OHLC,
        LevelKind.ORDER_BLOCK,
    }
)

_PHI1 = Decimal("1.618")
_PHI2 = Decimal("2.618")


# --- candle-shape helpers (pure, exact Decimal) --------------------------------


def _body(bar: Bar) -> Decimal:
    return abs(bar.close - bar.open)


def _is_hammer(bar: Bar) -> bool:
    """Hammer at support: lower wick >= 2x body, body <= 45% of the range."""
    rng = bar.high - bar.low
    if rng <= 0:
        return False
    body = _body(bar)
    lower_wick = min(bar.open, bar.close) - bar.low
    return lower_wick >= Decimal(2) * body and body <= Decimal("0.45") * rng


def _is_shooting_star(bar: Bar) -> bool:
    """Shooting star at resistance: upper wick >= 2x body, body <= 45% of range."""
    rng = bar.high - bar.low
    if rng <= 0:
        return False
    body = _body(bar)
    upper_wick = bar.high - max(bar.open, bar.close)
    return upper_wick >= Decimal(2) * body and body <= Decimal("0.45") * rng


def _is_bullish_engulfing(bar: Bar, prev: Bar) -> bool:
    return (
        bar.close > bar.open
        and prev.close < prev.open
        and bar.close >= prev.open
        and bar.open <= prev.close
    )


def _is_bearish_engulfing(bar: Bar, prev: Bar) -> bool:
    return (
        bar.close < bar.open
        and prev.close > prev.open
        and bar.close <= prev.open
        and bar.open >= prev.close
    )


def _is_marubozu(bar: Bar, body_ratio: Decimal) -> bool:
    rng = bar.high - bar.low
    if rng <= 0:
        return False
    return _body(bar) >= body_ratio * rng


def _is_hold(bar: Bar) -> bool:
    """A retest hold candle: small body relative to the range (no fresh break)."""
    rng = bar.high - bar.low
    if rng <= 0:
        return False
    return _body(bar) <= Decimal("0.5") * rng


def _nearest_rank_percentile(values: list[Decimal], pct: int) -> Decimal:
    """Nearest-rank percentile of an ascending-sorted Decimal list."""
    if not values:
        raise ValueError("percentile requires at least one value")
    n = len(values)
    rank = (Decimal(pct) * Decimal(n) / Decimal(100)).to_integral_value(rounding=ROUND_CEILING)
    return values[max(0, min(n - 1, int(rank) - 1))]


def _ist_datetime(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=IST)
    return ts.astimezone(IST)


def _parse_time(value: str) -> time:
    hours, minutes = str(value).split(":")
    return time(int(hours), int(minutes))


@dataclass
class _PositionState:
    """Live book-keeping for the single open EE+ position."""

    instrument: str
    side: OrderSide
    entry: Decimal
    quantity: Decimal
    remaining: Decimal
    sl: Decimal
    initial_sl: Decimal
    stop: StopProtection
    atr_at_entry: Decimal
    r1_price: Decimal
    r2_price: Decimal
    highest_close: Decimal
    lowest_close: Decimal
    bars_since_entry: int = 0
    partial_done: bool = False
    entry_bar_index: int = 0
    tight_sl: Decimal = Decimal(0)


class ElephantEdgeStrategy(Strategy):
    """EE+ strategy: composable level fusion, outer-buffer SL, hedges & scene emission.

    Declarative parameters preserve plan §6 defaults while adding Phase 2
    (`Track T21.2`) generalization knobs: ``horizon_mode``,
    ``entry_trigger_mode``, ``sl_mode``, ``hedge_mode``, and ``asset_class``.
    Run against ``SimulatedContext`` or ``LiveContext``; feeds degrade honestly
    to price-action / theoretical fallbacks when unseeded.
    """

    # -- plan §6 declarative parameters --------------------------------------
    instrument = "NSE:NIFTY50-INDEX"
    elephant_support_percentiles = Parameter(default=(25, 35))
    elephant_resistance_percentiles = Parameter(default=(63, 74))
    use_oi_walls = Parameter(default=True)
    use_gamma = Parameter(default=True)
    use_order_blocks = Parameter(default=True)
    use_pdh_pdl = Parameter(default=True)
    use_max_pain = Parameter(default=True)
    snap_zones_to_oi_strikes = Parameter(default=True)
    use_mid_month_cycle = Parameter(default=True)
    mid_month_window_days = Parameter(default=(14, 16))
    mid_month_stretch_atr = Parameter(default="2.5", min="1.5", max="5.0", step="0.5")
    min_level_score = Parameter(default=3, min=0, max=4, step=1)
    entry_window = Parameter(default=("09:20", "14:30"))
    square_off_time = Parameter(default="15:10")
    max_trades_per_day = Parameter(default=3, min=1, max=10, step=1)
    risk_per_trade_pct = Parameter(default="0.5", min="0.1", max="2.0", step="0.1")
    max_position_fraction = Parameter(default="0.25", min="0.05", max="1.0", step="0.05")
    target_r1 = Parameter(default="3.0", min="1.5", max="5.0", step="0.5")
    target_r2 = Parameter(default="5.0", min="3.0", max="10.0", step="0.5")
    confirm_bars_breakout = Parameter(default=2, min=0, max=3, step=1)
    max_stagnant_bars = Parameter(default=6, min=3, max=15, step=1)
    trail_mode = Parameter(default="atr")
    trail_atr_mult = Parameter(default="2.0", min="1.0", max="5.0", step="0.5")
    activation_after_r = Parameter(default="1.0", min="0.5", max="3.0", step="0.5")
    sl_buffer_atr = Parameter(default="0.25", min="0.0", max="1.0", step="0.05")
    min_sl_atr = Parameter(default="0.5", min="0.2", max="3.0", step="0.1")
    volume_mult = Parameter(default="1.5", min="1.0", max="5.0", step="0.1")
    body_ratio_breakout = Parameter(default="0.6", min="0.5", max="0.9", step="0.05")
    alternate_mode = Parameter(default=False)
    account_equity = Parameter(default="1000000", min="1000", max="10000000000", step="1")
    lot_size = Parameter(default="1", min="1", max="100000", step="1")

    # -- Phase 2 (Track T21.2) generalized multi-horizon & primitive knobs ---
    horizon_mode = Parameter(default="intraday")
    entry_trigger_mode = Parameter(default="all")
    sl_mode = Parameter(default="outer_atr_buffer")
    hedge_mode = Parameter(default="auto")
    asset_class = Parameter(default="index")
    timeframe = Parameter(default="1m")
    percentile_shield_atr = Parameter(default="0.50", min="0.10", max="1.50", step="0.05")
    zone_round_step = Parameter(default="50", min="1", max="5000", step="1")

    def __init__(self, **overrides: object) -> None:
        self._explicit_entry_window = "entry_window" in overrides
        self._explicit_square_off = "square_off_time" in overrides
        custom_zone_extractor = overrides.pop("zone_extractor", None)
        custom_stop_policy = overrides.pop("stop_policy", None)
        custom_hedge_policy = overrides.pop("hedge_policy", None)

        super().__init__(**overrides)
        self._instrument = str(self.instrument)
        self._horizon_enum = HorizonMode(str(self.horizon_mode))
        self._trigger_enum = EntryTriggerMode(str(self.entry_trigger_mode))
        self._sl_enum = SlMode(str(self.sl_mode))
        self._hedge_enum = HedgeMode(str(self.hedge_mode))
        self._asset_enum = AssetClass(str(self.asset_class))

        self._bars: list[Bar] = []
        self._volume_series: list[Decimal] = []
        self._session_date: Any = None
        self._session_start_index = 0
        self._session_bars: list[Bar] = []
        self._session_bar_count = 0
        self._session_open = Decimal(0)
        self._low_min = Decimal(0)
        self._high_max = Decimal(0)
        self._first_bar: Bar | None = None
        self._completed_sessions: dict[Any, list[Bar]] = {}
        self._level_map: LevelMap | None = None
        self._levels_by_id: dict[str, Level] = {}
        self._fallback = False
        self._trades_today = 0
        self._traded_levels: set[str] = set()
        self._last_trade_side: OrderSide | None = None
        self._pending_breakouts: dict[str, dict[str, Any]] = {}
        self._broken_levels: dict[str, OrderSide] = {}
        self._position_state: dict[str, _PositionState] = {}
        self._pending_entry_stop: StopProtection | None = None
        self._pending_entry_plan: StopPlan | None = None
        self.signal_log: list[StrategySignal] = []
        self.position_intent_log: list[PositionIntent] = []
        self.trail_log: list[StopUpdate] = []
        self.hedge_log: list[HedgeRecommendationSpec] = []

        self.zone_extractor: ZoneExtractor = (
            custom_zone_extractor
            if isinstance(custom_zone_extractor, ZoneExtractor)
            else ElephantZonesExtractor(
                support_percentiles=tuple(self.elephant_support_percentiles),
                resistance_percentiles=tuple(self.elephant_resistance_percentiles),
                round_step=str(self.zone_round_step),
                use_pdh_pdl=bool(self.use_pdh_pdl),
            )
        )
        self.stop_policy: OuterBufferStopPolicy = (
            custom_stop_policy
            if isinstance(custom_stop_policy, OuterBufferStopPolicy)
            else OuterBufferStopPolicy(
                sl_mode=self._sl_enum,
                buffer_atr=str(self.sl_buffer_atr),
                percentile_atr=str(self.percentile_shield_atr),
                target_r1=str(self.target_r1),
                target_r2=str(self.target_r2),
                trail_mode=TrailMode(str(self.trail_mode)),
                trail_atr_mult=str(self.trail_atr_mult),
                activation_after_r=str(self.activation_after_r),
                max_stagnant_bars=int(self.max_stagnant_bars),
            )
        )
        self.hedge_policy: HedgeOverlayPolicy = (
            custom_hedge_policy
            if isinstance(custom_hedge_policy, HedgeOverlayPolicy)
            else HedgeOverlayPolicy()
        )
        self.scene_emitter = OverlaySceneEmitter(
            strategy_id="elephant_edge_v3",
            symbol=self._instrument,
            timeframe=str(self.timeframe),
        )

    # -- lifecycle ------------------------------------------------------------
    def on_start(self) -> None:
        self._instrument = str(self.instrument)
        self._horizon_enum = HorizonMode(str(self.horizon_mode))
        self._trigger_enum = EntryTriggerMode(str(self.entry_trigger_mode))
        self._sl_enum = SlMode(str(self.sl_mode))
        self._hedge_enum = HedgeMode(str(self.hedge_mode))
        self._asset_enum = AssetClass(str(self.asset_class))
        self.scene_emitter.reset(symbol=self._instrument, timeframe=str(self.timeframe))
        self.indicators.atr(self._instrument, 14)

    def on_bar(self, bar: Bar) -> None:
        if bar.instrument != self._instrument:
            return
        self._ingest(bar)
        self._manage_open_position(bar)
        if self._in_entry_window(bar) and not self._near_square_off(bar):
            self._process_signals(bar)

    def on_order_event(self, event: OrderEvent) -> None:
        if event.instrument != self._instrument:
            return
        if event.status is not OrderStatus.COMPLETE or event.filled_quantity <= 0:
            return
        if self._pending_entry_stop is not None:
            self._record_entry(event)
            return
        state = self._position_state.get(self._instrument)
        if state is None:
            return
        state.remaining = state.remaining - event.filled_quantity
        if state.remaining <= 0:
            state.remaining = Decimal(0)
            self._position_state.pop(self._instrument, None)

    def on_stop_update(self, event: StopUpdate) -> None:
        self.trail_log.append(event)

    def on_stop(self) -> None:
        self._exit_position("ee.squareoff")

    @property
    def context(self) -> StrategyContext:
        return self._require_context()

    def emit_scene(self) -> OverlayScene:
        """Return the immutable 6-layer ``OverlayScene`` accumulated during the run."""
        return self.scene_emitter.emit()

    def scene_dict(self) -> dict[str, Any]:
        """Serialize the accumulated 6-layer scene matching ``tantra-ui-charts`` JSON."""
        return self.scene_emitter.to_dict()

    # -- session / bar plumbing ----------------------------------------------
    def _current_bar_index(self) -> int:
        return max(0, len(self._bars) - 1)

    def _ingest(self, bar: Bar) -> None:
        self._bars.append(bar)
        bar_idx = self._current_bar_index()
        self._volume_series.append(Decimal(bar.volume))
        atr_ind = self.indicators.atr(self._instrument, 14)
        atr_ind.update(bar)
        if atr_ind.ready:
            self.scene_emitter.record_indicator_point("ATR(14)", bar_idx, atr_ind.value)
        self._update_session(bar)

    def _session_key_for(self, bar: Bar) -> Any:
        if self._horizon_enum is HorizonMode.INTRADAY:
            return _ist_datetime(bar.ts).date()
        return SessionClock.session_key(bar.ts, self._horizon_enum, self._asset_enum)

    def _update_session(self, bar: Bar) -> None:
        session_key = self._session_key_for(bar)
        bar_idx = self._current_bar_index()
        if self._session_date is not None and session_key != self._session_date:
            self._completed_sessions[self._session_date] = self._session_bars
            self._session_date = None
        if self._session_date is None:
            self._session_date = session_key
            self._session_start_index = bar_idx
            self._session_bars = [bar]
            self._session_bar_count = 1
            self._session_open = bar.open
            self._low_min = bar.low
            self._high_max = bar.high
            self._first_bar = bar
            self._trades_today = 0
            self._traded_levels = set()
            self._last_trade_side = None
            self._pending_breakouts = {}
            self._broken_levels = {}
            self._build_level_map(bar)
            return
        self._session_bars.append(bar)
        self._session_bar_count += 1
        self._low_min = min(self._low_min, bar.low)
        self._high_max = max(self._high_max, bar.high)
        if self._session_bar_count % 5 == 0 or self._horizon_enum is not HorizonMode.INTRADAY:
            self._build_level_map(bar)

    @staticmethod
    def _ist_time(bar: Bar) -> time:
        return _ist_datetime(bar.ts).time()

    @staticmethod
    def _ist_date(bar: Bar) -> Any:
        return _ist_datetime(bar.ts).date()

    def _effective_entry_window(self) -> tuple[str, str]:
        if self._explicit_entry_window:
            start, end = self.entry_window
            return str(start), str(end)
        return SessionClock.default_entry_window(self._asset_enum)

    def _effective_square_off_str(self) -> str:
        if self._explicit_square_off:
            return str(self.square_off_time)
        return SessionClock.default_square_off_time(self._asset_enum)

    def _in_entry_window(self, bar: Bar) -> bool:
        if self._horizon_enum is not HorizonMode.INTRADAY:
            return True
        start, end = self._effective_entry_window()
        t = self._ist_time(bar)
        return _parse_time(start) <= t <= _parse_time(end)

    @staticmethod
    def _time_minutes(value: time) -> int:
        return value.hour * 60 + value.minute

    def _near_square_off(self, bar: Bar) -> bool:
        if not self._explicit_square_off and not SessionClock.is_intraday_square_off_enabled(
            self._horizon_enum
        ):
            return False
        minutes = self._time_minutes(self._ist_time(bar))
        return minutes >= self._time_minutes(self._square_off_time()) - 30

    def _square_off_time(self) -> time:
        return _parse_time(self._effective_square_off_str())

    def _atr_value(self) -> Decimal | None:
        indicator = self.indicators.atr(self._instrument, 14)
        return indicator.value if indicator.ready else None

    def _volume_avg(self) -> Decimal | None:
        series = self._volume_series
        if len(series) < 21:
            return None
        window = series[-21:-1]
        return sum(window, Decimal(0)) / Decimal(20)

    # -- level map construction ----------------------------------------------
    def _options_snapshot(self) -> OptionsSnapshot | None:
        try:
            return self.context.options_snapshot(self._instrument)
        except OptionsUnavailable:
            return None

    def _build_level_map(self, bar: Bar) -> None:
        try:
            level_map = self.context.level_map()
            self._fallback = False
        except LevelsUnavailable:
            self._fallback = True
            level_map = self._fallback_level_map(bar)
        snapshot = self._options_snapshot()
        if snapshot is not None and (self.use_oi_walls or self.use_gamma or self.use_max_pain):
            level_map = self._augment_with_options(level_map, snapshot)
            if self.snap_zones_to_oi_strikes:
                level_map = self._snap_elephant_zones(level_map, snapshot)
        scored: list[Level] = []
        for level in level_map.levels:
            score = self._score_level(level, level_map, snapshot, bar)
            scored.append(
                Level(
                    level.level_id,
                    level.kind,
                    level.side,
                    level.price,
                    level.band_half_width,
                    score,
                    level.source,
                )
            )
        self._level_map = LevelMap(instrument=self._instrument, levels=tuple(scored), as_of=bar.ts)
        self._levels_by_id = {lvl.level_id: lvl for lvl in scored}
        self.zone_extractor.populate_scene(
            self.scene_emitter,
            self._level_map,
            self._session_start_index,
            self._current_bar_index(),
            equilibrium=self._session_open if self._session_open > 0 else None,
        )

    def _band_half_width(self, strike: Decimal | None = None) -> Decimal:
        atr = self._atr_value()
        if atr is not None:
            base = Decimal("0.5") * atr
        elif self._first_bar is not None:
            base = Decimal("0.5") * (self._first_bar.high - self._first_bar.low)
        else:
            base = Decimal("1")
        if strike is not None:
            return max(strike / Decimal(2), base)
        return base

    # -- price-action fallback level map -------------------------------------
    def _fallback_level_map(self, bar: Bar) -> LevelMap:
        if not isinstance(self.zone_extractor, ElephantZonesExtractor):
            ctx = ZoneExtractionContext(
                instrument=self._instrument,
                bar=bar,
                bar_index=self._current_bar_index(),
                session_open=self._session_open,
                session_bars=tuple(self._session_bars),
                completed_sessions=tuple(
                    (k, tuple(v)) for k, v in self._completed_sessions.items()
                ),
                atr=self._atr_value(),
                snapshot=self._options_snapshot(),
            )
            return self.zone_extractor.extract(ctx)

        first = self._first_bar
        if first is None:
            first = bar
        first_range = first.high - first.low
        anchor = first.close
        prior = self._completed_sessions
        if len(prior) >= 2:
            downs: list[Decimal] = []
            ups: list[Decimal] = []
            for bars in prior.values():
                downs.append(bars[0].open - min(b.low for b in bars))
                ups.append(max(b.high for b in bars) - bars[0].open)
            p25 = _nearest_rank_percentile(sorted(downs), int(self.elephant_support_percentiles[0]))
            p35 = _nearest_rank_percentile(sorted(downs), int(self.elephant_support_percentiles[1]))
            p63 = _nearest_rank_percentile(
                sorted(ups), int(self.elephant_resistance_percentiles[0])
            )
            p74 = _nearest_rank_percentile(
                sorted(ups), int(self.elephant_resistance_percentiles[1])
            )
            open_price = self._session_open
            s1, s2 = open_price - p25, open_price - p35
            r1, r2 = open_price + p63, open_price + p74
        else:
            s1 = anchor - _PHI1 * first_range
            s2 = anchor - _PHI2 * first_range
            r1 = anchor + _PHI1 * first_range
            r2 = anchor + _PHI2 * first_range
        half = self._band_half_width()
        levels: list[Level] = [
            Level("ee:s1", LevelKind.ELEPHANT_SUPPORT_1, LevelSide.SUPPORT, s1, half, 0),
            Level("ee:s2", LevelKind.ELEPHANT_SUPPORT_2, LevelSide.SUPPORT, s2, half, 0),
            Level("ee:r1", LevelKind.ELEPHANT_RESISTANCE_1, LevelSide.RESISTANCE, r1, half, 0),
            Level("ee:r2", LevelKind.ELEPHANT_RESISTANCE_2, LevelSide.RESISTANCE, r2, half, 0),
        ]
        for round_level in self._round_levels(bar.close):
            levels.append(
                Level(
                    f"rn:{round_level}",
                    LevelKind.STRIKE_ROUND,
                    LevelSide.BOTH,
                    round_level,
                    half,
                    0,
                )
            )
        if self.use_pdh_pdl:
            previous = self._previous_session_ohlc()
            if previous is not None:
                for name, value in (
                    ("pdh", previous["high"]),
                    ("pdl", previous["low"]),
                    ("pdc", previous["close"]),
                ):
                    levels.append(
                        Level(name, LevelKind.PREVIOUS_DAY_OHLC, LevelSide.BOTH, value, half, 0)
                    )
        return LevelMap(instrument=self._instrument, levels=tuple(levels), as_of=bar.ts)

    def _round_levels(self, price: Decimal) -> set[Decimal]:
        step = Decimal(str(self.zone_round_step))
        below = (price / step).to_integral_value(rounding=ROUND_FLOOR) * step
        return {below, below + step}

    def _previous_session_ohlc(self) -> dict[str, Decimal] | None:
        if not self._completed_sessions:
            return None
        last_date = max(self._completed_sessions)
        bars = self._completed_sessions[last_date]
        return {
            "open": bars[0].open,
            "high": max(b.high for b in bars),
            "low": min(b.low for b in bars),
            "close": bars[-1].close,
        }

    # -- options augmentation / snapping -------------------------------------
    def _strike_interval(self, snapshot: OptionsSnapshot) -> Decimal:
        strikes = sorted({leg.strike for leg in snapshot.legs})
        if len(strikes) < 2:
            return Decimal("50")
        diffs = [b - a for a, b in pairwise(strikes) if b > a]
        return min(diffs) if diffs else Decimal("50")

    def _augment_with_options(self, level_map: LevelMap, snapshot: OptionsSnapshot) -> LevelMap:
        levels = list(level_map.levels)
        strike = self._strike_interval(snapshot)
        half = strike / Decimal(2)
        if self.use_oi_walls:
            for leg in snapshot.call_walls(2):
                levels.append(
                    Level(
                        f"oi:call:{leg.strike}",
                        LevelKind.OI_WALL_CALL,
                        LevelSide.RESISTANCE,
                        leg.strike,
                        half,
                        0,
                    )
                )
            for leg in snapshot.put_walls(2):
                levels.append(
                    Level(
                        f"oi:put:{leg.strike}",
                        LevelKind.OI_WALL_PUT,
                        LevelSide.SUPPORT,
                        leg.strike,
                        half,
                        0,
                    )
                )
        if self.use_gamma:
            flip = self._gamma_flip(snapshot)
            if flip is not None:
                levels.append(
                    Level("gamma:flip", LevelKind.GAMMA_FLIP, LevelSide.BOTH, flip, half, 0)
                )
            for option_type, kind, side in (
                ("CE", LevelKind.GAMMA_WALL_CALL, LevelSide.RESISTANCE),
                ("PE", LevelKind.GAMMA_WALL_PUT, LevelSide.SUPPORT),
            ):
                wall = self._gamma_wall(snapshot, option_type)
                if wall is not None:
                    levels.append(Level(f"gamma:{option_type}:{wall}", kind, side, wall, half, 0))
        if self.use_max_pain:
            max_pain = snapshot.max_pain()
            if max_pain is not None:
                levels.append(
                    Level("maxpain", LevelKind.MAX_PAIN, LevelSide.BOTH, max_pain, half, 0)
                )
        return LevelMap(
            instrument=level_map.instrument, levels=tuple(levels), as_of=level_map.as_of
        )

    def _gamma_flip(self, snapshot: OptionsSnapshot) -> Decimal | None:
        pairs = [
            (leg.strike, leg.gamma)
            for leg in snapshot.legs
            if leg.gamma is not None and leg.gamma > 0
        ]
        total = sum((gamma for _strike, gamma in pairs), Decimal(0))
        if total <= 0:
            return None
        weighted = sum((strike * gamma for strike, gamma in pairs), Decimal(0))
        return weighted / total

    def _gamma_wall(self, snapshot: OptionsSnapshot, option_type: str) -> Decimal | None:
        walls = [
            (leg.strike, leg.gamma)
            for leg in snapshot.legs
            if leg.option_type == option_type and leg.gamma is not None
        ]
        if not walls:
            return None
        return max(walls, key=lambda pair: pair[1])[0]

    def _snap_elephant_zones(self, level_map: LevelMap, snapshot: OptionsSnapshot) -> LevelMap:
        if not self.snap_zones_to_oi_strikes:
            return level_map
        strike = self._strike_interval(snapshot)
        walls = [(leg.strike, leg.option_type) for leg in snapshot.call_walls(2)]
        walls += [(leg.strike, leg.option_type) for leg in snapshot.put_walls(2)]
        snapped: list[Level] = []
        elephant_kinds = {
            LevelKind.ELEPHANT_SUPPORT_1,
            LevelKind.ELEPHANT_SUPPORT_2,
            LevelKind.ELEPHANT_RESISTANCE_1,
            LevelKind.ELEPHANT_RESISTANCE_2,
        }
        for level in level_map.levels:
            price = level.price
            if level.kind in elephant_kinds:
                wanted_type = "PE" if level.side in (LevelSide.SUPPORT, LevelSide.BOTH) else "CE"
                for wall_strike, option_type in walls:
                    if option_type == wanted_type and abs(level.price - wall_strike) <= strike:
                        price = wall_strike
                        break
            snapped.append(
                Level(
                    level.level_id,
                    level.kind,
                    level.side,
                    price,
                    level.band_half_width,
                    level.score,
                    level.source,
                )
            )
        return LevelMap(
            instrument=level_map.instrument, levels=tuple(snapped), as_of=level_map.as_of
        )

    # -- confluence scoring (plan §2, 0..4 clamped) ---------------------------
    def _score_level(
        self,
        level: Level,
        level_map: LevelMap,
        snapshot: OptionsSnapshot | None,
        bar: Bar,
    ) -> int:
        score = 0
        if self._overlaps_anchor(level, level_map):
            score += 1
        if self._delta_oi_matches(level, snapshot):
            score += 1
        if self._pcr_tilt_supports(level, snapshot):
            score += 1
        if self._regime_agrees(level, snapshot):
            score += 1
        else:
            score += self._mid_month_adjust(level, bar)
        return max(0, min(4, score))

    def _overlaps_anchor(self, level: Level, level_map: LevelMap) -> bool:
        if level.kind in ANCHOR_KINDS:
            return True
        low, high = level.band()
        for other in level_map.levels:
            if other.level_id == level.level_id or other.kind not in ANCHOR_KINDS:
                continue
            other_low, other_high = other.band()
            if other_low <= high and other_high >= low:
                return True
        return False

    def _oi_change_at(self, level: Level, snapshot: OptionsSnapshot) -> Decimal | None:
        option_type = "PE" if level.side in (LevelSide.SUPPORT, LevelSide.BOTH) else "CE"
        for leg in snapshot.legs:
            if leg.strike == level.price and leg.option_type == option_type:
                return leg.open_interest_change
        return None

    def _delta_oi_matches(self, level: Level, snapshot: OptionsSnapshot | None) -> bool:
        if snapshot is None:
            return False
        change = self._oi_change_at(level, snapshot)
        if change is None:
            return False
        if level.side in (LevelSide.SUPPORT, LevelSide.BOTH):
            return change > 0
        return change < 0

    def _pcr_tilt_supports(self, level: Level, snapshot: OptionsSnapshot | None) -> bool:
        if snapshot is None:
            return False
        call_oi = sum((leg.open_interest for leg in snapshot.call_walls(2)), Decimal(0))
        put_oi = sum((leg.open_interest for leg in snapshot.put_walls(2)), Decimal(0))
        if call_oi <= 0:
            return False
        pcr = put_oi / call_oi
        if level.side in (LevelSide.SUPPORT, LevelSide.BOTH):
            return pcr > Decimal("1.0")
        return pcr < Decimal("0.75")

    def _gamma_regime(self, snapshot: OptionsSnapshot) -> str | None:
        net = Decimal(0)
        for leg in snapshot.legs:
            if leg.gamma is None:
                continue
            net = net + leg.gamma if leg.option_type == "CE" else net - leg.gamma
        if net > 0:
            return "long"
        if net < 0:
            return "short"
        return None

    def _regime_agrees(self, level: Level, snapshot: OptionsSnapshot | None) -> bool:
        if snapshot is None:
            return False
        regime = self._gamma_regime(snapshot)
        if regime is None:
            return False
        if regime == "long":
            return level.side in (LevelSide.SUPPORT, LevelSide.BOTH)
        return level.side in (LevelSide.RESISTANCE, LevelSide.BOTH)

    def _mid_month_adjust(self, level: Level, bar: Bar) -> int:
        """Mid-Month reversal gate: +1 counter-trend reversal, -1 late breakout."""
        if not self.use_mid_month_cycle:
            return 0
        if _ist_datetime(bar.ts).date().day not in self.mid_month_window_days:
            return 0
        atr = self._atr_value()
        if atr is None or atr <= 0:
            return 0
        stretch = abs(bar.close - self._session_open)
        if stretch < Decimal(str(self.mid_month_stretch_atr)) * atr:
            return 0
        trend_up = bar.close >= self._session_open
        if trend_up:
            if level.side in (LevelSide.RESISTANCE, LevelSide.BOTH):
                return 1
            return -1
        if level.side in (LevelSide.SUPPORT, LevelSide.BOTH):
            return 1
        return -1

    # -- signal generation (plan §3) -----------------------------------------
    def _process_signals(self, bar: Bar) -> None:
        if self._position_state.get(self._instrument) is not None:
            return
        if self._trades_today >= int(self.max_trades_per_day):
            return
        self._process_pending_breakouts(bar)
        if self._position_state.get(self._instrument) is not None:
            return
        if self._trades_today >= int(self.max_trades_per_day):
            return
        level_map = self._level_map
        if level_map is None:
            return
        atr = self._atr_value()
        if atr is None:
            return
        for level in self._candidate_levels(bar, atr):
            if level.level_id in self._traded_levels:
                continue
            kind, side = self._classify(bar, level, atr)
            if kind is None or side is None:
                continue
            if kind is SignalKind.BREAKOUT and int(self.confirm_bars_breakout) > 0:
                if level.level_id not in self._pending_breakouts:
                    self._pending_breakouts[level.level_id] = {
                        "side": side,
                        "band": level.band(),
                        "level": level,
                        "follow_through": 0,
                    }
                    self._broken_levels[level.level_id] = side
                continue
            self._emit_signal(bar, level, kind, side)

    def _process_pending_breakouts(self, bar: Bar) -> None:
        if not self._pending_breakouts:
            return
        pending: dict[str, dict[str, Any]] = {}
        for level_id, entry in self._pending_breakouts.items():
            if not self._sustains_breakout(bar, entry["band"], entry["side"]):
                continue
            entry["follow_through"] = int(entry["follow_through"]) + 1
            if entry["follow_through"] >= int(self.confirm_bars_breakout):
                self._emit_signal(bar, entry["level"], SignalKind.BREAKOUT, entry["side"])
                continue
            pending[level_id] = entry
        self._pending_breakouts = pending

    @staticmethod
    def _sustains_breakout(bar: Bar, band: tuple[Decimal, Decimal], side: OrderSide) -> bool:
        band_low, band_high = band
        if side is OrderSide.BUY:
            return bar.close > band_high
        return bar.close < band_low

    def _candidate_levels(self, bar: Bar, atr: Decimal) -> tuple[Level, ...]:
        level_map = self._level_map
        if level_map is None:
            return ()
        near = {
            level.level_id for level in level_map.overlapping(bar.close, width=atr * Decimal(2))
        }
        return tuple(
            level
            for level in level_map.levels
            if level.level_id in near and level.score >= int(self.min_level_score)
        )

    def _classify(
        self, bar: Bar, level: Level, atr: Decimal
    ) -> tuple[SignalKind | None, OrderSide | None]:
        band_low, band_high = level.band()
        rng = bar.high - bar.low
        if rng < Decimal("0.2") * atr or rng > Decimal("4") * atr:
            return None, None
        prev = self._session_bars[-2] if len(self._session_bars) >= 2 else None
        if (
            level.side in (LevelSide.SUPPORT, LevelSide.BOTH)
            and bar.low <= band_high
            and (_is_hammer(bar) or (prev is not None and _is_bullish_engulfing(bar, prev)))
        ):
            return SignalKind.REVERSAL, OrderSide.BUY
        if (
            level.side in (LevelSide.RESISTANCE, LevelSide.BOTH)
            and bar.high >= band_low
            and (_is_shooting_star(bar) or (prev is not None and _is_bearish_engulfing(bar, prev)))
        ):
            return SignalKind.REVERSAL, OrderSide.SELL

        if self._trigger_enum is EntryTriggerMode.REJECTION_WICK:
            return None, None

        body_ratio = Decimal(str(self.body_ratio_breakout))
        if (
            bar.close > band_high
            and level.side in (LevelSide.RESISTANCE, LevelSide.BOTH)
            and _is_marubozu(bar, body_ratio)
            and rng >= Decimal("1.5") * atr
        ):
            return SignalKind.BREAKOUT, OrderSide.BUY
        if (
            bar.close < band_low
            and level.side in (LevelSide.SUPPORT, LevelSide.BOTH)
            and _is_marubozu(bar, body_ratio)
            and rng >= Decimal("1.5") * atr
        ):
            return SignalKind.BREAKOUT, OrderSide.SELL
        if (
            level.level_id in self._broken_levels
            and band_low <= bar.close <= band_high
            and _is_hold(bar)
        ):
            return SignalKind.RETEST, self._broken_levels[level.level_id]

        if self._trigger_enum is EntryTriggerMode.ZONE_TOUCH_CLOSE:
            if (
                level.side in (LevelSide.SUPPORT, LevelSide.BOTH)
                and bar.low <= band_high
                and bar.close >= band_low
                and bar.close > bar.open
            ):
                return SignalKind.REVERSAL, OrderSide.BUY
            if (
                level.side in (LevelSide.RESISTANCE, LevelSide.BOTH)
                and bar.high >= band_low
                and bar.close <= band_high
                and bar.close < bar.open
            ):
                return SignalKind.REVERSAL, OrderSide.SELL

        return None, None

    def _delta_oi_ok(
        self,
        side: OrderSide,
        kind: SignalKind,
        level: Level,
        snapshot: OptionsSnapshot | None,
    ) -> bool:
        """ΔOI gate: building for Reversal, short-covering for Breakout/Retest."""
        del side
        if snapshot is None:
            return True
        change = self._oi_change_at(level, snapshot)
        if change is None:
            return True
        if kind is SignalKind.REVERSAL:
            return change > 0
        return change < 0

    def _compute_sl_plan(
        self, entry: Decimal, side: OrderSide, level: Level, atr: Decimal
    ) -> StopPlan | None:
        band = level.band()
        if self._sl_enum is SlMode.OUTER_ATR_BUFFER:
            buffer = Decimal(str(self.sl_buffer_atr)) * atr
            try:
                stop = self.stop_loss(side, band, buffer)
            except ValueError:
                return None
            sl = stop.sl
            tight_anchor = (band[0] + band[1]) / Decimal(2)
            tight_sl = (
                min(entry - Decimal("0.15") * atr, tight_anchor)
                if side is OrderSide.BUY
                else max(entry + Decimal("0.15") * atr, tight_anchor)
            )
            one_r = abs(entry - sl)
            r1 = self._target_price(entry, side, Decimal(str(self.target_r1)), one_r)
            r2 = self._target_price(entry, side, Decimal(str(self.target_r2)), one_r)
            prot = StopProtection(
                sl=sl,
                trail=TrailMode(str(self.trail_mode)),
                trail_distance=Decimal(str(self.trail_atr_mult)),
                activation_after_r=Decimal(str(self.activation_after_r)),
            )
            return StopPlan(
                sl=sl,
                tight_sl=max(Decimal("0.05"), tight_sl),
                outer_sl=sl,
                one_r=one_r,
                target_r1=r1,
                target_r2=r2,
                stop_protection=prot,
                saved_cushion=max(Decimal(0), abs(sl - tight_sl)),
            )
        try:
            return self.stop_policy.compute_plan(entry=entry, side=side, level_band=band, atr=atr)
        except ValueError:
            return None

    def _emit_signal(
        self, bar: Bar, level: Level, kind: SignalKind, side: OrderSide
    ) -> StrategySignal | None:
        """Validate every §3 gate, size the position, emit scene + hedge, submit entry."""
        if self._position_state.get(self._instrument) is not None:
            return None
        if self._trades_today >= int(self.max_trades_per_day):
            return None
        if level.level_id in self._traded_levels:
            return None
        if not self._volume_filter(bar):
            return None
        atr = self._atr_value()
        if atr is None:
            return None
        snapshot = self._options_snapshot()
        if not self._delta_oi_ok(side, kind, level, snapshot):
            return None
        if (
            self.alternate_mode
            and self._last_trade_side is not None
            and side is self._last_trade_side
        ):
            return None

        entry = bar.close
        plan = self._compute_sl_plan(entry, side, level, atr)
        if plan is None:
            return None
        sl = plan.sl
        one_r = plan.one_r
        if one_r <= 0 or one_r < Decimal(str(self.min_sl_atr)) * atr:
            return None
        if Decimal(2) * one_r > self._expected_move(atr):
            return None
        quantity = self._position_size(entry, one_r)
        if quantity <= 0:
            return None

        quality = self._trigger_quality(bar, kind)
        confidence = min(Decimal(level.score) * quality, Decimal(100))
        signal = StrategySignal(
            instrument=self._instrument,
            side=side,
            kind=kind,
            ref_levels=(level.level_id,),
            confidence=confidence,
        )
        r2 = plan.target_r2
        intent = PositionIntent(
            instrument=self._instrument,
            side=side,
            quantity=quantity,
            entry=entry,
            stop=sl,
            target=r2,
            risk_amount=self._risk_amount(),
        )
        self.signal_log.append(signal)
        self.position_intent_log.append(intent)
        self._trades_today += 1
        self._traded_levels.add(level.level_id)
        if self._level_map is not None:
            for other in self._level_map.levels:
                if other.level_id != level.level_id and self._bands_overlap(
                    other.band(), level.band()
                ):
                    self._traded_levels.add(other.level_id)
        self._last_trade_side = side

        bar_idx = self._current_bar_index()
        marker_side = MarkerSide.BUY if side is OrderSide.BUY else MarkerSide.SELL
        marker_kind = MarkerKind(kind.value)
        tight_probed = (
            bar.low <= plan.tight_sl if side is OrderSide.BUY else bar.high >= plan.tight_sl
        )
        if self._sl_enum in (SlMode.OUTER_ATR_BUFFER, SlMode.PERCENTILE_SHIELD) and tight_probed:
            self.scene_emitter.add_signal(entry, bar_idx, marker_side, MarkerKind.SWEEP_SAVED)
            self.scene_emitter.add_hint(
                bar_idx,
                entry,
                HintSeverity.POSITIVE,
                "Outer-SL Shield Active",
                f"Tight SL {plan.tight_sl} probed on entry candle while outer SL {sl} held.",
                metrics=(
                    HintMetricSpec("Level", level.level_id),
                    HintMetricSpec("Tight SL", str(plan.tight_sl)),
                    HintMetricSpec("Outer SL", str(sl)),
                ),
            )
        else:
            self.scene_emitter.add_signal(entry, bar_idx, marker_side, marker_kind)
            self.scene_emitter.add_hint(
                bar_idx,
                entry,
                HintSeverity.INFO,
                f"EE+ {kind.value.title()} @ {level.level_id}",
                f"Score {level.score}/4, sl_mode={self._sl_enum.value}, SL={sl}, 5R={r2}",
                metrics=(
                    HintMetricSpec("Confidence", str(confidence)),
                    HintMetricSpec("1R", str(one_r)),
                    HintMetricSpec("SL", str(sl)),
                ),
            )
        self.stop_policy.emit_stop_lines(self.scene_emitter, plan, bar_idx, bar_idx)

        hedge = self.hedge_policy.synthesize(
            spot=entry,
            atr=atr,
            side=side,
            level_map=self._level_map,
            horizon_mode=self._horizon_enum,
            hedge_mode=self._hedge_enum,
            lot_size=str(self.lot_size),
            snapshot=snapshot,
        )
        if hedge is not None:
            self.hedge_log.append(hedge)
            self.hedge_policy.emit_to_scene(self.scene_emitter, hedge, bar_idx, bar_idx)

        self._pending_entry_stop = plan.stop_protection
        self._pending_entry_plan = plan
        tag = "ee.entry.long" if side is OrderSide.BUY else "ee.entry.short"
        self._submit_order(side, quantity, tag)
        self._pending_entry_stop = None
        self._pending_entry_plan = None
        return signal

    @staticmethod
    def _bands_overlap(a: tuple[Decimal, Decimal], b: tuple[Decimal, Decimal]) -> bool:
        return a[1] >= b[0] and a[0] <= b[1]

    def _expected_move(self, atr: Decimal) -> Decimal:
        """Proxy for the IV-implied daily move: session range or 5x ATR (no IV in SDK)."""
        return max(self._high_max - self._low_min, atr * Decimal(5))

    def _trigger_quality(self, bar: Bar, kind: SignalKind) -> Decimal:
        quality = Decimal("20")
        avg = self._volume_avg()
        if avg is not None and avg > 0 and Decimal(bar.volume) >= Decimal(2) * avg:
            quality += Decimal("2")
        if kind is SignalKind.BREAKOUT:
            quality += Decimal("1")
        return min(quality, Decimal("25"))

    def _target_price(
        self, entry: Decimal, side: OrderSide, multiple: Decimal, one_r: Decimal
    ) -> Decimal:
        if side is OrderSide.BUY:
            return entry + multiple * one_r
        return entry - multiple * one_r

    # -- positioning (plan §5) ------------------------------------------------
    def _risk_amount(self) -> Decimal:
        equity = Decimal(str(self.account_equity))
        return equity * Decimal(str(self.risk_per_trade_pct)) / Decimal(100)

    def _position_size(self, entry: Decimal, one_r: Decimal) -> Decimal:
        if one_r <= 0:
            return Decimal(0)
        lot = Decimal(str(self.lot_size))
        if lot <= 0:
            return Decimal(0)
        quantity_raw = self._risk_amount() / one_r
        lots = (quantity_raw / lot).to_integral_value(rounding=ROUND_DOWN)
        quantity = lots * lot
        cap_notional = Decimal(str(self.account_equity)) * Decimal(str(self.max_position_fraction))
        if quantity * entry > cap_notional:
            max_quantity = (cap_notional / entry).to_integral_value(rounding=ROUND_DOWN)
            quantity = (max_quantity / lot).to_integral_value(rounding=ROUND_DOWN) * lot
        return quantity

    def _volume_filter(self, bar: Bar) -> bool:
        avg = self._volume_avg()
        if avg is None or avg <= 0:
            return False
        return Decimal(bar.volume) >= Decimal(str(self.volume_mult)) * avg

    # -- execution / stop management (plan §4) --------------------------------
    def _submit_order(self, side: OrderSide, quantity: Decimal, tag: str) -> OrderEvent | None:
        quantity = quantity if isinstance(quantity, Decimal) else Decimal(str(quantity))
        if quantity <= 0:
            return None
        return self.submit(
            OrderRequest(
                instrument=self._instrument,
                side=side,
                quantity=quantity,
                order_type=OrderType.MARKET,
                tag=tag,
            )
        )

    def _record_entry(self, event: OrderEvent) -> None:
        stop = self._pending_entry_stop
        if stop is None:
            return
        side = event.side
        entry = event.price if event.price is not None else self.current_price(self._instrument)
        quantity = event.filled_quantity
        one_r = abs(entry - stop.sl)
        atr = self._atr_value() or Decimal("1")
        r1 = self._target_price(entry, side, Decimal(str(self.target_r1)), one_r)
        r2 = self._target_price(entry, side, Decimal(str(self.target_r2)), one_r)
        plan = self._pending_entry_plan
        self._position_state[self._instrument] = _PositionState(
            instrument=self._instrument,
            side=side,
            entry=entry,
            quantity=quantity,
            remaining=quantity,
            sl=stop.sl,
            initial_sl=stop.sl,
            stop=stop,
            atr_at_entry=atr,
            r1_price=r1,
            r2_price=r2,
            highest_close=max(entry, event.price) if event.price is not None else entry,
            lowest_close=min(entry, event.price) if event.price is not None else entry,
            entry_bar_index=self._current_bar_index(),
            tight_sl=plan.tight_sl if plan is not None else Decimal(0),
        )
        self._pending_entry_stop = None
        self._pending_entry_plan = None

    def _manage_open_position(self, bar: Bar) -> None:
        state = self._position_state.get(self._instrument)
        if state is None:
            return
        state.bars_since_entry += 1
        if state.side is OrderSide.BUY:
            state.highest_close = max(state.highest_close, bar.close)
        else:
            state.lowest_close = min(state.lowest_close, bar.close)
        atr = self._atr_value()
        if atr is None:
            return
        one_r = abs(state.entry - state.initial_sl)
        if one_r <= 0:
            return
        if self._stop_breached(bar, state):
            self._record_exit_scene(bar, state, "ee.stop", stopped_out=True)
            self._exit_position("ee.stop")
            return
        if state.bars_since_entry >= int(self.max_stagnant_bars):
            excursion = abs(bar.close - state.entry)
            if excursion < Decimal("0.5") * one_r:
                self._record_exit_scene(bar, state, "ee.scratch", stopped_out=False)
                self._exit_position("ee.scratch")
                return
        if not state.partial_done and self._hit_r1(bar, state):
            half = (state.quantity / Decimal(2)).to_integral_value(rounding=ROUND_DOWN)
            if half > 0 and state.remaining >= half:
                close_side = OrderSide.SELL if state.side is OrderSide.BUY else OrderSide.BUY
                self._submit_order(close_side, half, "ee.partial")
            state.partial_done = True
            self._move_stop(state, state.entry, "breakeven")
        if state.partial_done and self._hit_r2(bar, state):
            self._record_exit_scene(bar, state, "ee.target_r2", stopped_out=False)
            self._exit_position("ee.target_r2")
            return
        self._trail(bar, state, one_r, atr)
        should_square_off = (
            self._explicit_square_off
            or SessionClock.is_intraday_square_off_enabled(self._horizon_enum)
        )
        if should_square_off and self._ist_time(bar) >= self._square_off_time():
            self._record_exit_scene(bar, state, "ee.squareoff", stopped_out=False)
            self._exit_position("ee.squareoff")

    def _record_exit_scene(
        self, bar: Bar, state: _PositionState, tag: str, *, stopped_out: bool
    ) -> None:
        bar_idx = self._current_bar_index()
        one_r = abs(state.entry - state.initial_sl)
        if one_r > 0:
            diff = (
                bar.close - state.entry if state.side is OrderSide.BUY else state.entry - bar.close
            )
            realized_r = diff / one_r
        else:
            realized_r = Decimal(0)
        marker_side = MarkerSide.SELL if state.side is OrderSide.BUY else MarkerSide.BUY
        marker_kind = MarkerKind.STOP_LINE if stopped_out else MarkerKind.TARGET_HIT
        self.scene_emitter.add_signal(bar.close, bar_idx, marker_side, marker_kind)
        self.scene_emitter.add_connector(
            from_index=state.entry_bar_index,
            from_price=state.entry,
            to_index=max(state.entry_bar_index, bar_idx),
            to_price=bar.close,
            side=MarkerSide.BUY if state.side is OrderSide.BUY else MarkerSide.SELL,
            realized_r=realized_r,
            stopped_out=stopped_out,
            label=tag,
        )

    @staticmethod
    def _stop_breached(bar: Bar, state: _PositionState) -> bool:
        if state.side is OrderSide.BUY:
            return bar.low <= state.sl
        return bar.high >= state.sl

    @staticmethod
    def _hit_r1(bar: Bar, state: _PositionState) -> bool:
        if state.side is OrderSide.BUY:
            return bar.high >= state.r1_price
        return bar.low <= state.r1_price

    @staticmethod
    def _hit_r2(bar: Bar, state: _PositionState) -> bool:
        if state.side is OrderSide.BUY:
            return bar.high >= state.r2_price
        return bar.low <= state.r2_price

    def _trail(self, bar: Bar, state: _PositionState, one_r: Decimal, atr: Decimal) -> None:
        if state.stop.trail is TrailMode.OFF:
            return
        excursion = abs(bar.close - state.entry)
        if excursion < state.stop.activation_after_r * one_r:
            return
        if state.stop.trail is TrailMode.ATR:
            extreme = state.highest_close if state.side is OrderSide.BUY else state.lowest_close
            updated = self.trail_stop(state.side, state.stop, atr=atr, extreme=extreme)
        else:
            swing = self._recent_swing(state.side)
            if swing is None:
                return
            updated = self.trail_stop(state.side, state.stop, swing_level=swing)
        if updated.sl != state.sl:
            self._move_stop(state, updated.sl, "trail")

    def _recent_swing(self, side: OrderSide) -> Decimal | None:
        window = self._session_bars[-3:]
        if not window:
            return None
        if side is OrderSide.BUY:
            return min(bar.low for bar in window)
        return max(bar.high for bar in window)

    def _move_stop(self, state: _PositionState, new_sl: Decimal, reason: str) -> None:
        if new_sl == state.sl:
            return
        bar_idx = self._current_bar_index()
        stop_kind = StopKind.BREAKEVEN if reason == "breakeven" else StopKind.TRAILING
        self.scene_emitter.add_stop(
            new_sl, x0=bar_idx, x1=bar_idx, kind=stop_kind, previous=state.sl
        )
        self.on_stop_update(
            StopUpdate(
                instrument=self._instrument,
                side=state.side,
                new_stop=new_sl,
                old_stop=state.sl,
            )
        )
        state.sl = new_sl
        state.stop = StopProtection(
            sl=new_sl,
            trail=state.stop.trail,
            trail_distance=state.stop.trail_distance,
            activation_after_r=state.stop.activation_after_r,
        )

    def _exit_position(self, tag: str) -> None:
        state = self._position_state.get(self._instrument)
        if state is None or state.remaining <= 0:
            return
        close_side = OrderSide.SELL if state.side is OrderSide.BUY else OrderSide.BUY
        self._submit_order(close_side, state.remaining, tag)
