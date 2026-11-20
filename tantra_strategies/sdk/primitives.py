"""Composable Layer A strategy primitives (zero floats, pure ``Decimal``).

Provides orthogonal, reusable building blocks so distinct strategies
(``ElephantEdgeStrategy``, ``Orb15Strategy``, etc.) share identical zone
extraction, outer-buffer stop placement, multi-asset session clocks, F&O/MCX
hedge synthesis, and ``OverlayScene`` graphical emission contracts:

* :class:`SessionClock` — Multi-asset (``NSE`` / ``MCX`` / ``FX``) & multi-horizon
  (``intraday`` | ``weekly_expiry`` | ``monthly_expiry`` | ``commodity_cycle``)
  session boundary and square-off policies.
* :class:`ZoneExtractor`, :class:`ElephantZonesExtractor`, :class:`Orb15ZoneExtractor`
  — Pluggable level & band extraction feeding ``OverlayScene`` + stop policies.
* :class:`StopExitPolicy`, :class:`OuterBufferStopPolicy` — Generic stop computation
  across ``tight_center``, ``outer_edge``, ``outer_atr_buffer``, and
  ``percentile_shield`` modes.
* :class:`HedgeOverlayPolicy`, :class:`HedgeRecommendationSpec` — Horizon-aware
  option & futures hedge synthesis with live-chain quotes or honest
  ``theoretical_model`` pricing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from tantra_strategies.sdk.bar import Bar
from tantra_strategies.sdk.levels import (
    Level,
    LevelKind,
    LevelMap,
    LevelSide,
    OptionsSnapshot,
)
from tantra_strategies.sdk.order import OrderSide
from tantra_strategies.sdk.scene import (
    HedgeLegSide,
    HedgeLevelSpec,
    HedgeOptionKind,
    LevelLineStyleSpec,
    OverlaySceneEmitter,
    StopKind,
)
from tantra_strategies.sdk.stop_protection import StopProtection, TrailMode

IST = timezone(timedelta(hours=5, minutes=30))
_PHI1 = Decimal("1.618")
_PHI2 = Decimal("2.618")
_TWO_DP = Decimal("0.01")


def _dec(value: Decimal | int | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _q2(value: Decimal) -> Decimal:
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_UP)


def _ist_dt(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=IST)
    return ts.astimezone(IST)


def _nearest_rank_percentile(values: list[Decimal], pct: int) -> Decimal:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    n = len(ordered)
    rank = (Decimal(pct) * Decimal(n) / Decimal(100)).to_integral_value(rounding=ROUND_CEILING)
    return ordered[max(0, min(n - 1, int(rank) - 1))]


class HorizonMode(StrEnum):
    """Holding/expiry cycle mode for zone extraction, exits, and hedges."""

    INTRADAY = "intraday"
    WEEKLY_EXPIRY = "weekly_expiry"
    MONTHLY_EXPIRY = "monthly_expiry"
    COMMODITY_CYCLE = "commodity_cycle"


class EntryTriggerMode(StrEnum):
    """Microstructure entry filter for directional signals."""

    ALL = "all"
    REJECTION_WICK = "rejection_wick"
    ZONE_TOUCH_CLOSE = "zone_touch_close"


class SlMode(StrEnum):
    """Stop-loss placement policy relative to a zone band."""

    TIGHT_CENTER = "tight_center"
    OUTER_EDGE = "outer_edge"
    OUTER_ATR_BUFFER = "outer_atr_buffer"
    PERCENTILE_SHIELD = "percentile_shield"


class HedgeMode(StrEnum):
    """F&O / Commodity hedge structure selection."""

    UNHEDGED = "unhedged"
    AUTO = "auto"
    BULL_CALL_SPREAD = "bull_call_spread"
    BULL_PUT_CREDIT_SPREAD = "bull_put_credit_spread"
    BEAR_PUT_SPREAD = "bear_put_spread"
    BEAR_CALL_CREDIT_SPREAD = "bear_call_credit_spread"
    ZONE_IRON_CONDOR = "zone_iron_condor"
    PROTECTIVE_COLLAR = "protective_collar"


class AssetClass(StrEnum):
    """Supported market/session asset classes."""

    INDEX = "index"
    EQUITY_FNO = "equity_fno"
    COMMODITY = "commodity"
    FX = "fx"


class SessionClock:
    """Multi-asset session key & trading-hour rules aligned to Phase 1 presets."""

    @staticmethod
    def session_key(ts: datetime, horizon: HorizonMode, asset_class: AssetClass) -> str:
        local = _ist_dt(ts)
        if horizon is HorizonMode.INTRADAY:
            return local.date().isoformat()
        if horizon is HorizonMode.WEEKLY_EXPIRY:
            iso = local.isocalendar()
            return f"{iso.year}-W{iso.week:02d}"
        if horizon is HorizonMode.MONTHLY_EXPIRY:
            return f"{local.year}-{local.month:02d}"
        # COMMODITY_CYCLE: MCX bi-monthly / contract cycle anchored by month
        del asset_class
        return f"MCX-{local.year}-{local.month:02d}"

    @staticmethod
    def default_entry_window(asset_class: AssetClass) -> tuple[str, str]:
        if asset_class is AssetClass.COMMODITY:
            return ("09:15", "22:30")
        if asset_class is AssetClass.FX:
            return ("09:00", "23:30")
        return ("09:20", "14:30")

    @staticmethod
    def default_square_off_time(asset_class: AssetClass) -> str:
        if asset_class is AssetClass.COMMODITY:
            return "23:10"
        if asset_class is AssetClass.FX:
            return "23:45"
        return "15:10"

    @staticmethod
    def is_intraday_square_off_enabled(horizon: HorizonMode) -> bool:
        return horizon is HorizonMode.INTRADAY

    @staticmethod
    def is_daily_bar_stamp(ts: datetime) -> bool:
        local = _ist_dt(ts)
        return local.time() in (time(0, 0), time(5, 30), time(9, 15))


@dataclass(frozen=True, slots=True)
class ZoneExtractionContext:
    """Inputs supplied to a :class:`ZoneExtractor`."""

    instrument: str
    bar: Bar
    bar_index: int
    session_open: Decimal
    session_bars: tuple[Bar, ...]
    completed_sessions: tuple[tuple[object, tuple[Bar, ...]], ...]
    atr: Decimal | None = None
    snapshot: OptionsSnapshot | None = None


@runtime_checkable
class ZoneExtractor(Protocol):
    """Contract implemented by all pluggable zone/level extractors."""

    def extract(self, ctx: ZoneExtractionContext) -> LevelMap: ...

    def populate_scene(
        self,
        emitter: OverlaySceneEmitter,
        level_map: LevelMap,
        x0: int,
        x1: int,
        equilibrium: Decimal | None = None,
    ) -> None: ...


class ElephantZonesExtractor:
    """Empirical support/resistance percentile + Golden Ratio warmup zone extractor."""

    def __init__(
        self,
        *,
        support_percentiles: tuple[int, int] = (25, 35),
        resistance_percentiles: tuple[int, int] = (63, 74),
        round_step: Decimal | int | str = Decimal("50"),
        use_pdh_pdl: bool = True,
    ) -> None:
        self.support_percentiles = support_percentiles
        self.resistance_percentiles = resistance_percentiles
        self.round_step = _dec(round_step)
        self.use_pdh_pdl = use_pdh_pdl

    def extract(self, ctx: ZoneExtractionContext) -> LevelMap:
        first = ctx.session_bars[0] if ctx.session_bars else ctx.bar
        first_range = max(first.high - first.low, Decimal("0.01"))
        anchor = first.close
        if len(ctx.completed_sessions) >= 2:
            downs: list[Decimal] = []
            ups: list[Decimal] = []
            for _key, bars in ctx.completed_sessions:
                if not bars:
                    continue
                downs.append(bars[0].open - min(b.low for b in bars))
                ups.append(max(b.high for b in bars) - bars[0].open)
            p_s1 = _nearest_rank_percentile(downs, int(self.support_percentiles[0]))
            p_s2 = _nearest_rank_percentile(downs, int(self.support_percentiles[1]))
            p_r1 = _nearest_rank_percentile(ups, int(self.resistance_percentiles[0]))
            p_r2 = _nearest_rank_percentile(ups, int(self.resistance_percentiles[1]))
            open_px = ctx.session_open
            s1, s2 = max(_TWO_DP, open_px - p_s1), max(_TWO_DP, open_px - p_s2)
            r1, r2 = open_px + p_r1, open_px + p_r2
        else:
            s1 = max(_TWO_DP, anchor - _PHI1 * first_range)
            s2 = max(_TWO_DP, anchor - _PHI2 * first_range)
            r1 = anchor + _PHI1 * first_range
            r2 = anchor + _PHI2 * first_range

        half = self._half_width(ctx.atr, first_range)
        levels: list[Level] = [
            Level("ee:s1", LevelKind.ELEPHANT_SUPPORT_1, LevelSide.SUPPORT, s1, half, 0, "ee"),
            Level("ee:s2", LevelKind.ELEPHANT_SUPPORT_2, LevelSide.SUPPORT, s2, half, 0, "ee"),
            Level(
                "ee:r1", LevelKind.ELEPHANT_RESISTANCE_1, LevelSide.RESISTANCE, r1, half, 0, "ee"
            ),
            Level(
                "ee:r2", LevelKind.ELEPHANT_RESISTANCE_2, LevelSide.RESISTANCE, r2, half, 0, "ee"
            ),
        ]
        if self.round_step > 0:
            below = (ctx.bar.close // self.round_step) * self.round_step
            for rn in (below, below + self.round_step):
                if rn > 0:
                    levels.append(
                        Level(f"rn:{rn}", LevelKind.STRIKE_ROUND, LevelSide.BOTH, rn, half, 0, "rn")
                    )
        if self.use_pdh_pdl and ctx.completed_sessions:
            prev_bars = ctx.completed_sessions[-1][1]
            if prev_bars:
                pdh = max(b.high for b in prev_bars)
                pdl = min(b.low for b in prev_bars)
                pdc = prev_bars[-1].close
                for lid, val in (("pdh", pdh), ("pdl", pdl), ("pdc", pdc)):
                    if val > 0:
                        levels.append(
                            Level(lid, LevelKind.PREVIOUS_DAY_OHLC, LevelSide.BOTH, val, half, 0)
                        )
        return LevelMap(instrument=ctx.instrument, levels=tuple(levels), as_of=ctx.bar.ts)

    @staticmethod
    def _half_width(atr: Decimal | None, first_range: Decimal) -> Decimal:
        if atr is not None and atr > 0:
            return Decimal("0.5") * atr
        if first_range > 0:
            return Decimal("0.5") * first_range
        return Decimal("1")

    def populate_scene(
        self,
        emitter: OverlaySceneEmitter,
        level_map: LevelMap,
        x0: int,
        x1: int,
        equilibrium: Decimal | None = None,
    ) -> None:
        band_kinds = {
            LevelKind.ELEPHANT_SUPPORT_1: (0, "S1"),
            LevelKind.ELEPHANT_SUPPORT_2: (1, "S2"),
            LevelKind.ELEPHANT_RESISTANCE_1: (2, "R1"),
            LevelKind.ELEPHANT_RESISTANCE_2: (3, "R2"),
            LevelKind.ORDER_BLOCK: (4, "OB"),
        }
        for lvl in level_map.levels:
            if lvl.kind in band_kinds:
                fill_idx, short_lbl = band_kinds[lvl.kind]
                lo, hi = lvl.band()
                emitter.upsert_band(
                    key=lvl.level_id,
                    low=max(Decimal(0), lo),
                    high=hi,
                    x0=x0,
                    x1=x1,
                    fill_index=fill_idx,
                    label=f"{short_lbl} ({lvl.score}/4)",
                )
            elif lvl.kind in (
                LevelKind.PREVIOUS_DAY_OHLC,
                LevelKind.OI_WALL_CALL,
                LevelKind.OI_WALL_PUT,
                LevelKind.MAX_PAIN,
            ):
                emitter.upsert_level(
                    key=lvl.level_id,
                    price=lvl.price,
                    x0=x0,
                    x1=x1,
                    label=lvl.level_id.upper(),
                    style=LevelLineStyleSpec(dashed=True, color_index=2, line_width=1),
                )
        if equilibrium is not None and equilibrium > 0:
            emitter.upsert_level(
                key="equilibrium",
                price=equilibrium,
                x0=x0,
                x1=x1,
                label="Eq",
                style=LevelLineStyleSpec(dashed=True, color_index=0, line_width=1),
            )


class Orb15ZoneExtractor:
    """15-minute Opening Range Breakout zone extractor plugging into :class:`ZoneExtractor`."""

    def __init__(
        self,
        *,
        opening_bars: int = 3,
        atr_band_mult: Decimal | int | str = Decimal("0.25"),
    ) -> None:
        if opening_bars < 1:
            raise ValueError("opening_bars must be >= 1")
        self.opening_bars = opening_bars
        self.atr_band_mult = _dec(atr_band_mult)

    def extract(self, ctx: ZoneExtractionContext) -> LevelMap:
        window = ctx.session_bars[: self.opening_bars] or (ctx.bar,)
        or_high = max(b.high for b in window)
        or_low = min(b.low for b in window)
        or_mid = (or_high + or_low) / Decimal(2)
        atr = (
            ctx.atr if ctx.atr is not None and ctx.atr > 0 else max(or_high - or_low, Decimal("1"))
        )
        half = max(Decimal("0.05"), self.atr_band_mult * atr)
        levels = (
            Level(
                "orb:high",
                LevelKind.ELEPHANT_RESISTANCE_1,
                LevelSide.RESISTANCE,
                or_high,
                half,
                3,
                "orb15",
            ),
            Level(
                "orb:low",
                LevelKind.ELEPHANT_SUPPORT_1,
                LevelSide.SUPPORT,
                or_low,
                half,
                3,
                "orb15",
            ),
            Level(
                "orb:mid",
                LevelKind.PREVIOUS_DAY_OHLC,
                LevelSide.BOTH,
                or_mid,
                half,
                2,
                "orb15",
            ),
        )
        return LevelMap(instrument=ctx.instrument, levels=levels, as_of=ctx.bar.ts)

    def populate_scene(
        self,
        emitter: OverlaySceneEmitter,
        level_map: LevelMap,
        x0: int,
        x1: int,
        equilibrium: Decimal | None = None,
    ) -> None:
        for lvl in level_map.levels:
            lo, hi = lvl.band()
            if lvl.level_id == "orb:high":
                emitter.upsert_band(
                    key="orb:high",
                    low=max(Decimal(0), lo),
                    high=hi,
                    x0=x0,
                    x1=x1,
                    fill_index=2,
                    label="OR_HIGH",
                )
            elif lvl.level_id == "orb:low":
                emitter.upsert_band(
                    key="orb:low",
                    low=max(Decimal(0), lo),
                    high=hi,
                    x0=x0,
                    x1=x1,
                    fill_index=0,
                    label="OR_LOW",
                )
            elif lvl.level_id == "orb:mid":
                emitter.upsert_level(
                    key="orb:mid",
                    price=lvl.price,
                    x0=x0,
                    x1=x1,
                    label="OR_MID",
                    style=LevelLineStyleSpec(dashed=True, color_index=1, line_width=1),
                )
        if equilibrium is not None and equilibrium > 0:
            emitter.upsert_level(
                key="equilibrium",
                price=equilibrium,
                x0=x0,
                x1=x1,
                label="Eq",
                style=LevelLineStyleSpec(dashed=True, color_index=0, line_width=1),
            )


@dataclass(frozen=True, slots=True)
class StopPlan:
    """Computed initial SL + comparison anchors (tight vs outer shield) & target levels."""

    sl: Decimal
    tight_sl: Decimal
    outer_sl: Decimal
    one_r: Decimal
    target_r1: Decimal
    target_r2: Decimal
    stop_protection: StopProtection
    saved_cushion: Decimal


@runtime_checkable
class StopExitPolicy(Protocol):
    """Contract shared by every strategy for stop placement & target computation."""

    def compute_plan(
        self,
        *,
        entry: Decimal,
        side: OrderSide,
        level_band: tuple[Decimal, Decimal],
        atr: Decimal,
    ) -> StopPlan: ...


class OuterBufferStopPolicy:
    """StopExitPolicy supporting TightCenter, OuterEdge, OuterAtrBuffer & PercentileShield."""

    def __init__(
        self,
        *,
        sl_mode: SlMode = SlMode.OUTER_ATR_BUFFER,
        buffer_atr: Decimal | int | str = Decimal("0.25"),
        percentile_atr: Decimal | int | str = Decimal("0.50"),
        target_r1: Decimal | int | str = Decimal("3.0"),
        target_r2: Decimal | int | str = Decimal("5.0"),
        trail_mode: TrailMode = TrailMode.ATR,
        trail_atr_mult: Decimal | int | str = Decimal("2.0"),
        activation_after_r: Decimal | int | str = Decimal("1.0"),
        max_stagnant_bars: int = 6,
    ) -> None:
        self.sl_mode = SlMode(sl_mode)
        self.buffer_atr = max(Decimal(0), _dec(buffer_atr))
        self.percentile_atr = max(Decimal("0.10"), _dec(percentile_atr))
        self.target_r1_mult = _dec(target_r1)
        self.target_r2_mult = _dec(target_r2)
        self.trail_mode = trail_mode
        self.trail_atr_mult = _dec(trail_atr_mult)
        self.activation_after_r = _dec(activation_after_r)
        self.max_stagnant_bars = max_stagnant_bars

    def compute_plan(
        self,
        *,
        entry: Decimal,
        side: OrderSide,
        level_band: tuple[Decimal, Decimal],
        atr: Decimal,
    ) -> StopPlan:
        entry = _dec(entry)
        atr = max(_dec(atr), Decimal("0.01"))
        band_low = _dec(level_band[0])
        band_high = _dec(level_band[1])
        if band_low >= band_high:
            raise ValueError("level_band must satisfy band_low < band_high")
        band_center = (band_low + band_high) / Decimal(2)

        min_floor = Decimal("0.05")
        tight_offset = Decimal("0.15") * atr
        if side is OrderSide.BUY:
            tight_sl = max(min_floor, min(entry - tight_offset, band_center))
            edge_sl = max(min_floor, band_low)
            atr_buf_sl = max(min_floor, band_low - self.buffer_atr * atr)
            pct_sl = max(min_floor, band_low - self.percentile_atr * atr)
        else:
            tight_sl = max(entry + tight_offset, band_center)
            edge_sl = band_high
            atr_buf_sl = band_high + self.buffer_atr * atr
            pct_sl = band_high + self.percentile_atr * atr

        if self.sl_mode is SlMode.TIGHT_CENTER:
            chosen = tight_sl
        elif self.sl_mode is SlMode.OUTER_EDGE:
            chosen = edge_sl
        elif self.sl_mode is SlMode.PERCENTILE_SHIELD:
            chosen = pct_sl
        else:
            chosen = atr_buf_sl

        # Preserve exact one_r > 0
        one_r = abs(entry - chosen)
        if one_r <= 0:
            step = Decimal("0.10") * atr
            chosen = max(min_floor, entry - step) if side is OrderSide.BUY else entry + step
            one_r = abs(entry - chosen)

        if side is OrderSide.BUY:
            r1 = entry + self.target_r1_mult * one_r
            r2 = entry + self.target_r2_mult * one_r
            cushion = max(Decimal(0), tight_sl - chosen)
        else:
            r1 = max(min_floor, entry - self.target_r1_mult * one_r)
            r2 = max(min_floor, entry - self.target_r2_mult * one_r)
            cushion = max(Decimal(0), chosen - tight_sl)

        protection = StopProtection(
            sl=chosen,
            trail=self.trail_mode,
            trail_distance=self.trail_atr_mult,
            activation_after_r=self.activation_after_r,
        )
        return StopPlan(
            sl=chosen,
            tight_sl=tight_sl,
            outer_sl=atr_buf_sl,
            one_r=one_r,
            target_r1=r1,
            target_r2=r2,
            stop_protection=protection,
            saved_cushion=cushion,
        )

    @staticmethod
    def emit_stop_lines(
        emitter: OverlaySceneEmitter,
        plan: StopPlan,
        x0: int,
        x1: int,
    ) -> None:
        emitter.add_stop(plan.sl, x0=x0, x1=x1, kind=StopKind.INITIAL)
        emitter.add_stop(plan.target_r1, x0=x0, x1=x1, kind=StopKind.TARGET)
        emitter.add_stop(plan.target_r2, x0=x0, x1=x1, kind=StopKind.TARGET)


@dataclass(frozen=True, slots=True)
class HedgeLegPlan:
    """Single synthesized hedge leg (CE/PE/FUT)."""

    side: HedgeLegSide
    option_kind: HedgeOptionKind
    strike: Decimal
    lot_qty: Decimal
    leg_price: Decimal
    quote_source: str
    expiry: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "side": self.side.value,
            "option_kind": self.option_kind.value,
            "strike": str(self.strike),
            "lot_qty": str(self.lot_qty),
            "leg_price": str(self.leg_price),
            "quote_source": self.quote_source,
            "expiry": self.expiry,
        }


@dataclass(frozen=True, slots=True)
class HedgeRecommendationSpec:
    """Full hedged payoff recommendation attached to a directional or range setup."""

    structure: HedgeMode
    horizon_mode: HorizonMode
    spot: Decimal
    max_loss: Decimal
    breakevens: tuple[Decimal, ...]
    net_credit_debit: Decimal
    quote_source: str
    legs: tuple[HedgeLegPlan, ...]
    summary: str

    def to_dict(self) -> dict[str, object]:
        return {
            "structure": self.structure.value,
            "horizon_mode": self.horizon_mode.value,
            "spot": str(self.spot),
            "max_loss": str(self.max_loss),
            "breakevens": [str(b) for b in self.breakevens],
            "net_credit_debit": str(self.net_credit_debit),
            "quote_source": self.quote_source,
            "legs": [leg.to_dict() for leg in self.legs],
            "summary": self.summary,
        }


class HedgeOverlayPolicy:
    """F&O and MCX hedge synthesizer mapping signals + zones + chain into hedged legs."""

    @staticmethod
    def _strike_step(spot: Decimal) -> Decimal:
        if spot >= Decimal("20000"):
            return Decimal("100")
        if spot >= Decimal("5000"):
            return Decimal("50")
        if spot >= Decimal("1000"):
            return Decimal("20")
        if spot >= Decimal("200"):
            return Decimal("5")
        return Decimal("1")

    @staticmethod
    def _snap(price: Decimal, step: Decimal) -> Decimal:
        if step <= 0:
            return _q2(price)
        units = (price / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return max(step, units * step)

    @staticmethod
    def _resolve_option_leg(
        side: HedgeLegSide,
        opt_kind: HedgeOptionKind,
        target_strike: Decimal,
        spot: Decimal,
        atr: Decimal,
        lot_qty: Decimal,
        snapshot: OptionsSnapshot | None,
    ) -> HedgeLegPlan:
        opt_code = "CE" if opt_kind is HedgeOptionKind.CALL else "PE"
        if snapshot is not None and snapshot.legs:
            matching = [leg for leg in snapshot.legs if leg.option_type == opt_code]
            if matching:
                nearest = min(matching, key=lambda leg: abs(leg.strike - target_strike))
                px = HedgeOverlayPolicy._theoretical_option_price(
                    opt_kind, nearest.strike, spot, atr
                )
                return HedgeLegPlan(
                    side=side,
                    option_kind=opt_kind,
                    strike=nearest.strike,
                    lot_qty=lot_qty,
                    leg_price=px,
                    quote_source="chain_strike_theoretical",
                    expiry=snapshot.expiry,
                )
        px = HedgeOverlayPolicy._theoretical_option_price(opt_kind, target_strike, spot, atr)
        return HedgeLegPlan(
            side=side,
            option_kind=opt_kind,
            strike=target_strike,
            lot_qty=lot_qty,
            leg_price=px,
            quote_source="theoretical_model",
            expiry=snapshot.expiry if snapshot is not None else None,
        )

    @staticmethod
    def _theoretical_option_price(
        opt_kind: HedgeOptionKind, strike: Decimal, spot: Decimal, atr: Decimal
    ) -> Decimal:
        if opt_kind is HedgeOptionKind.CALL:
            intrinsic = max(Decimal(0), spot - strike)
        elif opt_kind is HedgeOptionKind.PUT:
            intrinsic = max(Decimal(0), strike - spot)
        else:
            return _q2(spot)
        dist_atr = min(Decimal("6"), abs(strike - spot) / max(atr, Decimal("0.01")))
        time_mult = max(Decimal("0.12"), Decimal("0.65") - dist_atr * Decimal("0.10"))
        floor = max(_TWO_DP, spot * Decimal("0.0015"))
        return _q2(max(floor, intrinsic + atr * time_mult))

    def synthesize(
        self,
        *,
        spot: Decimal,
        atr: Decimal,
        side: OrderSide | None,
        level_map: LevelMap | None,
        horizon_mode: HorizonMode,
        hedge_mode: HedgeMode,
        lot_size: Decimal | int | str = Decimal("1"),
        snapshot: OptionsSnapshot | None = None,
    ) -> HedgeRecommendationSpec | None:
        if hedge_mode is HedgeMode.UNHEDGED:
            return None
        spot = max(_dec(spot), Decimal("1"))
        atr = max(_dec(atr), spot * Decimal("0.005"), Decimal("1"))
        lot_qty = max(Decimal("1"), _dec(lot_size))
        step = self._snap(self._strike_step(spot), Decimal("1"))

        s1_anchor = spot - Decimal("1.5") * atr
        s2_anchor = spot - Decimal("2.6") * atr
        r1_anchor = spot + Decimal("1.5") * atr
        r2_anchor = spot + Decimal("2.6") * atr
        if level_map is not None:
            supports = sorted(level_map.supports(), key=lambda lvl: abs(spot - lvl.price))
            resistances = sorted(level_map.resistances(), key=lambda lvl: abs(lvl.price - spot))
            if supports:
                s1_anchor = supports[0].band()[0]
                s2_anchor = supports[-1].band()[0]
            if resistances:
                r1_anchor = resistances[0].band()[1]
                r2_anchor = resistances[-1].band()[1]

        structure = hedge_mode
        if structure is HedgeMode.AUTO:
            if horizon_mode is HorizonMode.COMMODITY_CYCLE:
                structure = HedgeMode.PROTECTIVE_COLLAR
            elif horizon_mode is HorizonMode.INTRADAY:
                structure = (
                    HedgeMode.BEAR_PUT_SPREAD
                    if side is OrderSide.SELL
                    else HedgeMode.BULL_CALL_SPREAD
                )
            elif side is None:
                structure = HedgeMode.ZONE_IRON_CONDOR
            elif side is OrderSide.BUY:
                structure = HedgeMode.BULL_PUT_CREDIT_SPREAD
            else:
                structure = HedgeMode.BEAR_CALL_CREDIT_SPREAD

        atm_k = self._snap(spot, step)
        legs: list[HedgeLegPlan] = []
        if structure is HedgeMode.BULL_CALL_SPREAD:
            otm_k = max(atm_k + step, self._snap(max(r1_anchor, spot + atr), step))
            legs.append(
                self._resolve_option_leg(
                    HedgeLegSide.BUY, HedgeOptionKind.CALL, atm_k, spot, atr, lot_qty, snapshot
                )
            )
            legs.append(
                self._resolve_option_leg(
                    HedgeLegSide.SELL, HedgeOptionKind.CALL, otm_k, spot, atr, lot_qty, snapshot
                )
            )
        elif structure is HedgeMode.BEAR_PUT_SPREAD:
            otm_k = max(step, min(atm_k - step, self._snap(min(s1_anchor, spot - atr), step)))
            legs.append(
                self._resolve_option_leg(
                    HedgeLegSide.BUY, HedgeOptionKind.PUT, atm_k, spot, atr, lot_qty, snapshot
                )
            )
            legs.append(
                self._resolve_option_leg(
                    HedgeLegSide.SELL, HedgeOptionKind.PUT, otm_k, spot, atr, lot_qty, snapshot
                )
            )
        elif structure is HedgeMode.BULL_PUT_CREDIT_SPREAD:
            short_target = self._snap(s1_anchor - Decimal("0.25") * atr, step)
            wing_target = self._snap(s2_anchor - Decimal("0.50") * atr, step)
            short_k = max(step, min(atm_k - step, short_target))
            wing_k = max(step, min(short_k - step, wing_target))
            legs.append(
                self._resolve_option_leg(
                    HedgeLegSide.SELL, HedgeOptionKind.PUT, short_k, spot, atr, lot_qty, snapshot
                )
            )
            legs.append(
                self._resolve_option_leg(
                    HedgeLegSide.BUY, HedgeOptionKind.PUT, wing_k, spot, atr, lot_qty, snapshot
                )
            )
        elif structure is HedgeMode.BEAR_CALL_CREDIT_SPREAD:
            short_k = max(atm_k + step, self._snap(r1_anchor + Decimal("0.25") * atr, step))
            wing_k = max(short_k + step, self._snap(r2_anchor + Decimal("0.50") * atr, step))
            legs.append(
                self._resolve_option_leg(
                    HedgeLegSide.SELL, HedgeOptionKind.CALL, short_k, spot, atr, lot_qty, snapshot
                )
            )
            legs.append(
                self._resolve_option_leg(
                    HedgeLegSide.BUY, HedgeOptionKind.CALL, wing_k, spot, atr, lot_qty, snapshot
                )
            )
        elif structure is HedgeMode.ZONE_IRON_CONDOR:
            sp_target = self._snap(s1_anchor - Decimal("0.25") * atr, step)
            wp_target = self._snap(s2_anchor - Decimal("0.50") * atr, step)
            short_pe = max(step, min(atm_k - step, sp_target))
            wing_pe = max(step, min(short_pe - step, wp_target))
            short_ce = max(atm_k + step, self._snap(r1_anchor + Decimal("0.25") * atr, step))
            wing_ce = max(short_ce + step, self._snap(r2_anchor + Decimal("0.50") * atr, step))
            for lside, opt, k in (
                (HedgeLegSide.SELL, HedgeOptionKind.PUT, short_pe),
                (HedgeLegSide.BUY, HedgeOptionKind.PUT, wing_pe),
                (HedgeLegSide.SELL, HedgeOptionKind.CALL, short_ce),
                (HedgeLegSide.BUY, HedgeOptionKind.CALL, wing_ce),
            ):
                legs.append(self._resolve_option_leg(lside, opt, k, spot, atr, lot_qty, snapshot))
        else:  # PROTECTIVE_COLLAR
            prot_target = self._snap(s2_anchor - Decimal("0.25") * atr, step)
            prot_pe = max(step, min(atm_k - step, prot_target))
            cap_ce = max(atm_k + step, self._snap(r2_anchor, step))
            legs.append(
                HedgeLegPlan(
                    side=HedgeLegSide.BUY,
                    option_kind=HedgeOptionKind.FUTURE,
                    strike=_q2(spot),
                    lot_qty=lot_qty,
                    leg_price=_q2(spot),
                    quote_source="spot_ref",
                    expiry=snapshot.expiry if snapshot is not None else None,
                )
            )
            legs.append(
                self._resolve_option_leg(
                    HedgeLegSide.BUY, HedgeOptionKind.PUT, prot_pe, spot, atr, lot_qty, snapshot
                )
            )
            legs.append(
                self._resolve_option_leg(
                    HedgeLegSide.SELL, HedgeOptionKind.CALL, cap_ce, spot, atr, lot_qty, snapshot
                )
            )

        net_credit = Decimal(0)
        for leg in legs:
            if leg.option_kind in (HedgeOptionKind.CALL, HedgeOptionKind.PUT):
                signed = leg.leg_price if leg.side is HedgeLegSide.SELL else -leg.leg_price
                net_credit += signed * leg.lot_qty

        opt_kinds = (HedgeOptionKind.CALL, HedgeOptionKind.PUT)
        strikes = [leg.strike for leg in legs if leg.option_kind in opt_kinds]
        width = (max(strikes) - min(strikes)) if len(strikes) >= 2 else atr
        max_loss = _q2(max(lot_qty * atr, width * lot_qty - net_credit))
        breakevens = tuple(_q2(leg.strike) for leg in legs[:2] if leg.strike > 0)
        sources = {leg.quote_source for leg in legs if leg.option_kind in opt_kinds}
        quote_source = (
            "chain_strike_theoretical"
            if "chain_strike_theoretical" in sources
            else "theoretical_model"
        )
        summary = (
            f"{structure.value} ({horizon_mode.value}): "
            f"{len(legs)} legs, max_loss={max_loss}, net={_q2(net_credit)}"
        )
        return HedgeRecommendationSpec(
            structure=structure,
            horizon_mode=horizon_mode,
            spot=_q2(spot),
            max_loss=max_loss,
            breakevens=breakevens,
            net_credit_debit=_q2(net_credit),
            quote_source=quote_source,
            legs=tuple(legs),
            summary=summary,
        )

    @staticmethod
    def emit_to_scene(
        emitter: OverlaySceneEmitter,
        rec: HedgeRecommendationSpec | None,
        x0: int,
        x1: int,
    ) -> None:
        if rec is None:
            return
        be = rec.breakevens[0] if rec.breakevens else None
        for idx, leg in enumerate(rec.legs):
            role = f"{leg.side.value.upper()} {leg.option_kind.value.upper()} {leg.strike}"
            emitter.add_hedge(
                HedgeLevelSpec(
                    role=role,
                    side=leg.side,
                    option_kind=leg.option_kind,
                    strike=leg.strike,
                    x0=x0,
                    x1=max(x0, x1),
                    breakeven=be if idx == 0 else None,
                    max_loss=rec.max_loss if idx == 0 else None,
                    summary=rec.summary if idx == 0 else None,
                )
            )


def filter_level_map_overlap(a: Sequence[Decimal], b: Sequence[Decimal]) -> bool:
    return a[1] >= b[0] and a[0] <= b[1]
