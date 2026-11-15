from decimal import Decimal

import pytest
from conftest import make_bars

from tantra_strategies import (
    Bar,
    Level,
    LevelKind,
    LevelMap,
    LevelSide,
    LevelsUnavailable,
    LiveContext,
    OptionLeg,
    OptionsSnapshot,
    OptionsUnavailable,
    OrderEvent,
    OrderRequest,
    OrderSide,
    SimulatedContext,
    StopProtection,
    StopUpdate,
    Strategy,
    TrailMode,
)


def test_simulated_context_level_map_unavailable() -> None:
    context = SimulatedContext()
    with pytest.raises(LevelsUnavailable) as exc_info:
        context.level_map()
    assert "0005" in str(exc_info.value)


def test_simulated_context_level_map_seeded() -> None:
    context = SimulatedContext()
    level_map = LevelMap(
        instrument="NSE:NIFTY50-INDEX",
        levels=(
            Level(
                "s1",
                LevelKind.ELEPHANT_SUPPORT_1,
                LevelSide.SUPPORT,
                Decimal("100"),
                band_half_width=Decimal("1"),
            ),
        ),
    )
    context.seed_level_map(level_map)
    assert context.level_map() is level_map


def test_simulated_context_options_seeded_and_unavailable() -> None:
    context = SimulatedContext()
    snapshot = OptionsSnapshot(
        instrument="NFO:NIFTY24NOV24000CE",
        expiry="2024-11-28",
        legs=(OptionLeg(strike=Decimal("24400"), option_type="CE"),),
    )
    context.seed_options(snapshot)
    assert context.options_snapshot("NFO:NIFTY24NOV24000CE", "2024-11-28") is snapshot
    with pytest.raises(OptionsUnavailable) as exc_info:
        context.options_snapshot("NFO:NIFTY24NOV24000CE", "2024-11-21")
    assert "0016" in str(exc_info.value)


def test_live_context_degrades_honestly() -> None:
    class FakeFeed:
        def current_price(self, instrument: str) -> Decimal:
            return Decimal("100")

    class FakeGateway:
        def submit(self, request: OrderRequest) -> OrderEvent:
            raise NotImplementedError

    context = LiveContext(FakeFeed(), FakeGateway())
    with pytest.raises(LevelsUnavailable) as exc_levels:
        context.level_map()
    assert "0005" in str(exc_levels.value)
    with pytest.raises(OptionsUnavailable) as exc_options:
        context.options_snapshot("NFO:NIFTY24NOV24000CE", "2024-11-28")
    assert "0016" in str(exc_options.value)


def test_eeplus_style_strategy_golden_sl_tsl() -> None:
    class EEPlus(Strategy):
        def __init__(self, **overrides: object) -> None:
            super().__init__(**overrides)
            self.initial_sl: Decimal | None = None
            self.stop: StopProtection | None = None
            self.updates: list[StopUpdate] = []
            self.band: tuple[Decimal, Decimal] = (Decimal("0"), Decimal("0"))

        def level_map(self) -> LevelMap:
            return self._require_context().level_map()

        def on_start(self) -> None:
            support = self.level_map().supports()[0]
            self.band = support.band()
            sl = self.stop_loss(OrderSide.BUY, self.band, Decimal("0.25")).sl
            self.initial_sl = sl
            self.stop = StopProtection(sl=sl, trail=TrailMode.ATR, trail_distance=Decimal("2"))

        def on_bar(self, bar: Bar) -> None:
            assert self.stop is not None
            new_stop = self.trail_stop(
                OrderSide.BUY, self.stop, atr=Decimal("1.5"), extreme=bar.high
            )
            if new_stop.sl != self.stop.sl:
                self._emit_stop_update(bar.instrument, OrderSide.BUY, new_stop.sl, self.stop.sl)
            self.stop = new_stop

        def on_stop_update(self, event: StopUpdate) -> None:
            self.updates.append(event)

    level_map = LevelMap(
        instrument="NSE:NIFTY50-INDEX",
        levels=(
            Level(
                "s1",
                LevelKind.ELEPHANT_SUPPORT_1,
                LevelSide.SUPPORT,
                Decimal("100"),
                band_half_width=Decimal("1"),
            ),
        ),
    )
    bars = make_bars([Decimal("100"), Decimal("101"), Decimal("105")])
    context = SimulatedContext()
    context.seed_level_map(level_map)
    strategy = EEPlus()
    strategy.run(context, bars)

    assert strategy.initial_sl == Decimal("98.75")
    assert strategy.stop is not None
    assert strategy.stop.sl == Decimal("102")
    assert len(strategy.updates) == 1
    assert strategy.updates[0].new_stop == Decimal("102")
    assert strategy.updates[0].old_stop == Decimal("98.75")
    band_low, band_high = strategy.band
    for stop_level in (
        strategy.initial_sl,
        *(update.new_stop for update in strategy.updates),
    ):
        assert stop_level is not None
        assert not (band_low < stop_level < band_high)

    unseeded = SimulatedContext()
    with pytest.raises(LevelsUnavailable):
        EEPlus().run(unseeded, bars)
