"""ORB-15 (Opening Range Breakout) strategy — second consumer of Phase 2 primitives.

Demonstrates cross-strategy composition per Plan 0015 §3 (Track T21.2) and
Acceptance Criterion #1: reuses the exact same :class:`SessionClock`,
:class:`OuterBufferStopPolicy`, :class:`HedgeOverlayPolicy`, and
:class:`OverlaySceneEmitter` primitives as :class:`ElephantEdgeStrategy`,
swapping only the :class:`Orb15ZoneExtractor` and opening-range breakout
signal logic. Zero floats: exact ``Decimal`` arithmetic throughout.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time, timedelta, timezone
from decimal import ROUND_DOWN, Decimal
from typing import Any

from tantra_strategies.sdk import (
    AssetClass,
    Bar,
    HedgeMode,
    HedgeOverlayPolicy,
    HedgeRecommendationSpec,
    HintMetricSpec,
    HintSeverity,
    HorizonMode,
    Level,
    LevelMap,
    MarkerKind,
    MarkerSide,
    OptionsSnapshot,
    OptionsUnavailable,
    Orb15ZoneExtractor,
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
)

IST = timezone(timedelta(hours=5, minutes=30))


def _parse_time(value: str) -> time:
    hours, minutes = str(value).split(":")
    return time(int(hours), int(minutes))


@dataclass
class _OrbPositionState:
    instrument: str
    side: OrderSide
    entry: Decimal
    quantity: Decimal
    remaining: Decimal
    sl: Decimal
    initial_sl: Decimal
    stop: StopProtection
    r1_price: Decimal
    r2_price: Decimal
    highest_close: Decimal
    lowest_close: Decimal
    entry_bar_index: int = 0
    partial_done: bool = False


class Orb15Strategy(Strategy):
    """Opening-range breakout strategy sharing ``OuterBufferStopPolicy`` & scene emitter."""

    instrument = "NSE:NIFTY50-INDEX"
    opening_bars = Parameter(default=3, min=1, max=30, step=1)
    asset_class = Parameter(default="index")
    horizon_mode = Parameter(default="intraday")
    sl_mode = Parameter(default="outer_atr_buffer")
    sl_buffer_atr = Parameter(default="0.25", min="0.0", max="1.0", step="0.05")
    percentile_shield_atr = Parameter(default="0.50", min="0.10", max="1.50", step="0.05")
    target_r1 = Parameter(default="2.0", min="1.0", max="5.0", step="0.5")
    target_r2 = Parameter(default="3.0", min="2.0", max="10.0", step="0.5")
    trail_mode = Parameter(default="atr")
    trail_atr_mult = Parameter(default="1.5", min="0.5", max="5.0", step="0.5")
    activation_after_r = Parameter(default="1.0", min="0.5", max="3.0", step="0.5")
    hedge_mode = Parameter(default="auto")
    max_trades_per_day = Parameter(default=2, min=1, max=6, step=1)
    risk_per_trade_pct = Parameter(default="0.5", min="0.1", max="2.0", step="0.1")
    max_position_fraction = Parameter(default="0.25", min="0.05", max="1.0", step="0.05")
    account_equity = Parameter(default="1000000", min="1000", max="10000000000", step="1")
    lot_size = Parameter(default="1", min="1", max="100000", step="1")
    entry_window = Parameter(default=("09:20", "14:45"))
    square_off_time = Parameter(default="15:10")
    timeframe = Parameter(default="5m")

    def __init__(self, **overrides: object) -> None:
        self._explicit_entry_window = "entry_window" in overrides
        self._explicit_square_off = "square_off_time" in overrides
        super().__init__(**overrides)

        self._instrument = str(self.instrument)
        self._horizon_enum = HorizonMode(str(self.horizon_mode))
        self._sl_enum = SlMode(str(self.sl_mode))
        self._hedge_enum = HedgeMode(str(self.hedge_mode))
        self._asset_enum = AssetClass(str(self.asset_class))

        self.zone_extractor = Orb15ZoneExtractor(
            opening_bars=int(self.opening_bars),
            atr_band_mult=Decimal("0.25"),
        )
        self.stop_policy = OuterBufferStopPolicy(
            sl_mode=self._sl_enum,
            buffer_atr=str(self.sl_buffer_atr),
            percentile_atr=str(self.percentile_shield_atr),
            target_r1=str(self.target_r1),
            target_r2=str(self.target_r2),
            trail_mode=TrailMode(str(self.trail_mode)),
            trail_atr_mult=str(self.trail_atr_mult),
            activation_after_r=str(self.activation_after_r),
        )
        self.hedge_policy = HedgeOverlayPolicy()
        self.scene_emitter = OverlaySceneEmitter(
            strategy_id="orb_15",
            symbol=self._instrument,
            timeframe=str(self.timeframe),
        )

        self._bars: list[Bar] = []
        self._session_key: str | None = None
        self._session_start_index = 0
        self._session_bars: list[Bar] = []
        self._completed_sessions: list[tuple[object, tuple[Bar, ...]]] = []
        self._level_map: LevelMap | None = None
        self._trades_today = 0
        self._traded_sides: set[OrderSide] = set()
        self._position_state: _OrbPositionState | None = None
        self._pending_plan: StopPlan | None = None
        self.signal_log: list[StrategySignal] = []
        self.position_intent_log: list[PositionIntent] = []
        self.trail_log: list[StopUpdate] = []
        self.hedge_log: list[HedgeRecommendationSpec] = []

    def on_start(self) -> None:
        self._instrument = str(self.instrument)
        self.scene_emitter.reset(symbol=self._instrument, timeframe=str(self.timeframe))
        self.indicators.atr(self._instrument, 14)

    def on_bar(self, bar: Bar) -> None:
        if bar.instrument != self._instrument:
            return
        self._bars.append(bar)
        bar_idx = len(self._bars) - 1
        atr_ind = self.indicators.atr(self._instrument, 14)
        atr_ind.update(bar)
        if atr_ind.ready:
            self.scene_emitter.record_indicator_point("ATR(14)", bar_idx, atr_ind.value)

        key = SessionClock.session_key(bar.ts, self._horizon_enum, self._asset_enum)
        if self._session_key is not None and key != self._session_key:
            self._completed_sessions.append((self._session_key, tuple(self._session_bars)))
            self._session_key = None
        if self._session_key is None:
            self._session_key = key
            self._session_start_index = bar_idx
            self._session_bars = [bar]
            self._trades_today = 0
            self._traded_sides = set()
            self._level_map = None
        else:
            self._session_bars.append(bar)

        if len(self._session_bars) >= int(self.opening_bars):
            self._refresh_zones(bar, bar_idx)

        had_position = self._position_state is not None
        self._manage_open_position(bar, bar_idx)
        if not had_position and self._can_enter(bar):
            self._evaluate_breakout(bar, bar_idx)

    def on_order_event(self, event: OrderEvent) -> None:
        if event.instrument != self._instrument or event.status is not OrderStatus.COMPLETE:
            return
        if self._pending_plan is not None:
            plan = self._pending_plan
            entry = event.price if event.price is not None else self._bars[-1].close
            qty = event.filled_quantity
            self._position_state = _OrbPositionState(
                instrument=self._instrument,
                side=event.side,
                entry=entry,
                quantity=qty,
                remaining=qty,
                sl=plan.sl,
                initial_sl=plan.sl,
                stop=plan.stop_protection,
                r1_price=plan.target_r1,
                r2_price=plan.target_r2,
                highest_close=entry,
                lowest_close=entry,
                entry_bar_index=len(self._bars) - 1,
            )
            self._pending_plan = None
            return
        if self._position_state is not None:
            self._position_state.remaining -= event.filled_quantity
            if self._position_state.remaining <= 0:
                self._position_state = None

    def on_stop_update(self, event: StopUpdate) -> None:
        self.trail_log.append(event)

    def on_stop(self) -> None:
        if self._position_state is not None and self._position_state.remaining > 0:
            close_side = (
                OrderSide.SELL if self._position_state.side is OrderSide.BUY else OrderSide.BUY
            )
            self.submit(
                OrderRequest(
                    instrument=self._instrument,
                    side=close_side,
                    quantity=self._position_state.remaining,
                    order_type=OrderType.MARKET,
                    tag="orb.squareoff",
                )
            )

    def emit_scene(self) -> OverlayScene:
        return self.scene_emitter.emit()

    def scene_dict(self) -> dict[str, Any]:
        return self.scene_emitter.to_dict()

    @property
    def context(self) -> StrategyContext:
        return self._require_context()

    def _atr_or_range(self, bar: Bar) -> Decimal:
        ind = self.indicators.atr(self._instrument, 14)
        if ind.ready and ind.value > 0:
            return ind.value
        return max(bar.high - bar.low, Decimal("1"))

    def _refresh_zones(self, bar: Bar, bar_idx: int) -> None:
        ctx = ZoneExtractionContext(
            instrument=self._instrument,
            bar=bar,
            bar_index=bar_idx,
            session_open=self._session_bars[0].open,
            session_bars=tuple(self._session_bars),
            completed_sessions=tuple(self._completed_sessions),
            atr=self._atr_or_range(bar),
        )
        self._level_map = self.zone_extractor.extract(ctx)
        mid = next((lvl.price for lvl in self._level_map.levels if lvl.level_id == "orb:mid"), None)
        self.zone_extractor.populate_scene(
            self.scene_emitter,
            self._level_map,
            self._session_start_index,
            bar_idx,
            equilibrium=mid,
        )

    def _local_time(self, bar: Bar) -> time:
        ts = bar.ts if bar.ts.tzinfo is not None else bar.ts.replace(tzinfo=IST)
        return ts.astimezone(IST).time()

    def _effective_window(self) -> tuple[str, str]:
        if self._explicit_entry_window:
            return str(self.entry_window[0]), str(self.entry_window[1])
        return SessionClock.default_entry_window(self._asset_enum)

    def _effective_square_off(self) -> str:
        if self._explicit_square_off:
            return str(self.square_off_time)
        return SessionClock.default_square_off_time(self._asset_enum)

    def _can_enter(self, bar: Bar) -> bool:
        if self._position_state is not None:
            return False
        if self._trades_today >= int(self.max_trades_per_day):
            return False
        if len(self._session_bars) <= int(self.opening_bars):
            return False
        if self._horizon_enum is HorizonMode.INTRADAY:
            start, end = self._effective_window()
            t = self._local_time(bar)
            if not (_parse_time(start) <= t <= _parse_time(end)):
                return False
        return self._level_map is not None

    def _options_snapshot(self) -> OptionsSnapshot | None:
        try:
            return self.context.options_snapshot(self._instrument)
        except OptionsUnavailable:
            return None

    def _position_size(self, entry: Decimal, one_r: Decimal) -> Decimal:
        if one_r <= 0 or entry <= 0:
            return Decimal(0)
        equity = Decimal(str(self.account_equity))
        risk = equity * Decimal(str(self.risk_per_trade_pct)) / Decimal(100)
        lot = Decimal(str(self.lot_size))
        lots = (risk / one_r / lot).to_integral_value(rounding=ROUND_DOWN)
        qty = lots * lot
        cap = equity * Decimal(str(self.max_position_fraction))
        if qty * entry > cap:
            max_qty = (cap / entry).to_integral_value(rounding=ROUND_DOWN)
            qty = (max_qty / lot).to_integral_value(rounding=ROUND_DOWN) * lot
        return qty

    def _evaluate_breakout(self, bar: Bar, bar_idx: int) -> None:
        if self._level_map is None:
            return
        by_id: dict[str, Level] = {lvl.level_id: lvl for lvl in self._level_map.levels}
        or_high = by_id.get("orb:high")
        or_low = by_id.get("orb:low")
        if or_high is None or or_low is None:
            return

        side: OrderSide | None = None
        anchor_level: Level | None = None
        if bar.close > or_high.price:
            side = OrderSide.BUY
            anchor_level = or_low
        elif bar.close < or_low.price:
            side = OrderSide.SELL
            anchor_level = or_high
        if side is None or anchor_level is None or side in self._traded_sides:
            return

        atr = self._atr_or_range(bar)
        try:
            plan = self.stop_policy.compute_plan(
                entry=bar.close,
                side=side,
                level_band=anchor_level.band(),
                atr=atr,
            )
        except ValueError:
            return

        qty = self._position_size(bar.close, plan.one_r)
        if qty <= 0:
            return

        signal = StrategySignal(
            instrument=self._instrument,
            side=side,
            kind=SignalKind.BREAKOUT,
            ref_levels=(anchor_level.level_id,),
            confidence=Decimal("78"),
        )
        intent = PositionIntent(
            instrument=self._instrument,
            side=side,
            quantity=qty,
            entry=bar.close,
            stop=plan.sl,
            target=plan.target_r2,
            risk_amount=Decimal(str(self.account_equity))
            * Decimal(str(self.risk_per_trade_pct))
            / Decimal(100),
        )
        self.signal_log.append(signal)
        self.position_intent_log.append(intent)
        self._trades_today += 1
        self._traded_sides.add(side)

        marker_side = MarkerSide.BUY if side is OrderSide.BUY else MarkerSide.SELL
        self.scene_emitter.add_signal(bar.close, bar_idx, marker_side, MarkerKind.BREAKOUT)
        self.stop_policy.emit_stop_lines(self.scene_emitter, plan, bar_idx, bar_idx)
        self.scene_emitter.add_hint(
            bar_idx,
            bar.close,
            HintSeverity.INFO,
            f"ORB-15 Breakout {side.value.upper()}",
            f"Breakout beyond {anchor_level.level_id}; sl_mode={self._sl_enum.value}, SL={plan.sl}",
            metrics=(
                HintMetricSpec("Tight SL", str(plan.tight_sl)),
                HintMetricSpec("Outer SL", str(plan.outer_sl)),
            ),
        )

        hedge = self.hedge_policy.synthesize(
            spot=bar.close,
            atr=atr,
            side=side,
            level_map=self._level_map,
            horizon_mode=self._horizon_enum,
            hedge_mode=self._hedge_enum,
            lot_size=str(self.lot_size),
            snapshot=self._options_snapshot(),
        )
        if hedge is not None:
            self.hedge_log.append(hedge)
            self.hedge_policy.emit_to_scene(self.scene_emitter, hedge, bar_idx, bar_idx)

        self._pending_plan = plan
        self.submit(
            OrderRequest(
                instrument=self._instrument,
                side=side,
                quantity=qty,
                order_type=OrderType.MARKET,
                tag="orb.entry",
            )
        )
        self._pending_plan = None

    def _manage_open_position(self, bar: Bar, bar_idx: int) -> None:
        state = self._position_state
        if state is None:
            return
        if state.side is OrderSide.BUY:
            state.highest_close = max(state.highest_close, bar.close)
            stopped = bar.low <= state.sl
            hit_r1 = bar.high >= state.r1_price
            hit_r2 = bar.high >= state.r2_price
        else:
            state.lowest_close = min(state.lowest_close, bar.close)
            stopped = bar.high >= state.sl
            hit_r1 = bar.low <= state.r1_price
            hit_r2 = bar.low <= state.r2_price

        close_side = OrderSide.SELL if state.side is OrderSide.BUY else OrderSide.BUY
        one_r = abs(state.entry - state.initial_sl) or Decimal("1")

        def _connector(tag: str, *, is_stop: bool) -> None:
            diff = (
                bar.close - state.entry if state.side is OrderSide.BUY else state.entry - bar.close
            )
            self.scene_emitter.add_signal(
                bar.close,
                bar_idx,
                MarkerSide.SELL if state.side is OrderSide.BUY else MarkerSide.BUY,
                MarkerKind.STOP_LINE if is_stop else MarkerKind.TARGET_HIT,
            )
            self.scene_emitter.add_connector(
                from_index=state.entry_bar_index,
                from_price=state.entry,
                to_index=max(state.entry_bar_index, bar_idx),
                to_price=bar.close,
                side=MarkerSide.BUY if state.side is OrderSide.BUY else MarkerSide.SELL,
                realized_r=diff / one_r,
                stopped_out=is_stop,
                label=tag,
            )

        if stopped:
            _connector("orb.stop", is_stop=True)
            self.submit(
                OrderRequest(
                    instrument=self._instrument,
                    side=close_side,
                    quantity=state.remaining,
                    order_type=OrderType.MARKET,
                    tag="orb.stop",
                )
            )
            return

        if not state.partial_done and hit_r1:
            half = (state.quantity / Decimal(2)).to_integral_value(rounding=ROUND_DOWN)
            if half > 0 and state.remaining >= half:
                self.submit(
                    OrderRequest(
                        instrument=self._instrument,
                        side=close_side,
                        quantity=half,
                        order_type=OrderType.MARKET,
                        tag="orb.partial",
                    )
                )
            state.partial_done = True
            self.scene_emitter.add_stop(
                state.entry, x0=bar_idx, x1=bar_idx, kind=StopKind.BREAKEVEN, previous=state.sl
            )
            self.on_stop_update(
                StopUpdate(
                    instrument=self._instrument,
                    side=state.side,
                    new_stop=state.entry,
                    old_stop=state.sl,
                )
            )
            state.sl = state.entry
            state.stop = StopProtection(
                sl=state.entry,
                trail=state.stop.trail,
                trail_distance=state.stop.trail_distance,
                activation_after_r=state.stop.activation_after_r,
            )

        if state.partial_done and hit_r2:
            _connector("orb.target_r2", is_stop=False)
            self.submit(
                OrderRequest(
                    instrument=self._instrument,
                    side=close_side,
                    quantity=state.remaining,
                    order_type=OrderType.MARKET,
                    tag="orb.target_r2",
                )
            )
            return

        if SessionClock.is_intraday_square_off_enabled(self._horizon_enum) and self._local_time(
            bar
        ) >= _parse_time(self._effective_square_off()):
            _connector("orb.squareoff", is_stop=False)
            self.submit(
                OrderRequest(
                    instrument=self._instrument,
                    side=close_side,
                    quantity=state.remaining,
                    order_type=OrderType.MARKET,
                    tag="orb.squareoff",
                )
            )
