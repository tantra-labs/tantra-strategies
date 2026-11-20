"""WheelSdkBridge: SDK fills (not requests) are replayed on a wheel-like host."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from tantra_strategies.sdk import OrderSide, Strategy, WheelSdkBridge


@dataclass
class FakeIid:
    symbol: str = "ABC"
    exchange: str = "NSE"


@dataclass
class FakeBar:
    instrument_id: FakeIid
    ts: dt.datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 100


class _Ctx:
    def __init__(self) -> None:
        self.is_busy = False

    def busy(self, iid: Any) -> bool:
        return self.is_busy


@dataclass
class FakeHost:
    calls: list[tuple[str, Decimal]] = field(default_factory=list)
    pos: Decimal = Decimal(0)
    ctx: _Ctx = field(default_factory=_Ctx)

    def buy(self, iid: Any, qty: Decimal) -> None:
        self.calls.append(("buy", qty))
        self.pos += qty

    def sell(self, iid: Any, qty: Decimal) -> None:
        self.calls.append(("sell", qty))
        self.pos -= qty

    def position(self, iid: Any) -> Decimal:
        return self.pos


class Scripted(Strategy):
    """Buys 3 on bar 1, brackets on bar 2, sells 5 on bar 5."""

    def __init__(self, instrument: str) -> None:
        super().__init__()
        self.instrument = instrument
        self.n = 0

    def on_bar(self, bar: Any) -> None:
        self.n += 1
        if self.n == 1:
            self.buy(bar.instrument, 3)
        elif self.n == 2:
            self.bracket(
                bar.instrument,
                position_side=OrderSide.BUY,
                quantity=3,
                stop=Decimal("50"),
                target=Decimal("200"),
            )
        elif self.n == 5:
            self.sell(bar.instrument, 5)

    def emit_scene(self) -> Any:
        from tantra_strategies.sdk import OverlayScene

        return OverlayScene(strategy_id="scripted", symbol=self.instrument, timeframe="1m")


def _bar(i: int, price: float = 100.0, iid: FakeIid | None = None) -> FakeBar:
    ts = dt.datetime(2026, 5, 4, 9, 15, tzinfo=dt.UTC) + dt.timedelta(minutes=i)
    return FakeBar(iid or FakeIid(), ts, price, price + 1, price - 1, price)


def _bridge() -> WheelSdkBridge:
    return WheelSdkBridge(
        Scripted, symbol="NSE:ABC", exchange="NSE", empty_scene_id="scripted-empty"
    )


def test_market_fill_forwarded_once_and_resting_legs_not_forwarded() -> None:
    bridge, host = _bridge(), FakeHost()
    bridge.start()
    for i in range(4):
        bridge.on_wheel_bar(host, _bar(i))
    assert host.calls == [("buy", Decimal(3))]


def test_filled_bracket_leg_is_forwarded() -> None:
    bridge, host = _bridge(), FakeHost()
    bridge.start()
    bridge.on_wheel_bar(host, _bar(0))
    bridge.on_wheel_bar(host, _bar(1))
    bridge.on_wheel_bar(host, _bar(2, price=100.0))
    bridge.on_wheel_bar(host, _bar(3, price=250.0))  # target leg fills intrabar
    assert host.calls == [("buy", Decimal(3)), ("sell", Decimal(3))]


def test_host_position_mirrors_sdk_position() -> None:
    bridge, host = _bridge(), FakeHost()
    bridge.start()
    for i in range(5):
        bridge.on_wheel_bar(host, _bar(i))
    # SDK: +3 then sells 5 -> -2; the host is reconciled to the same signed position.
    assert host.calls == [("buy", Decimal(3)), ("sell", Decimal(5))]
    assert host.position(None) == Decimal(-2)


def test_fill_while_busy_is_retried_not_dropped() -> None:
    bridge, host = _bridge(), FakeHost()
    bridge.start()
    host.ctx.is_busy = True
    bridge.on_wheel_bar(host, _bar(0))  # SDK buys 3 while the host is busy
    assert host.calls == []
    host.ctx.is_busy = False
    bridge.on_wheel_bar(host, _bar(1))
    assert host.calls == [("buy", Decimal(3))]


def test_busy_host_skips_forwarding() -> None:
    bridge, host = _bridge(), FakeHost()
    host.ctx.is_busy = True
    bridge.start()
    for i in range(3):
        bridge.on_wheel_bar(host, _bar(i))
    assert host.calls == []


def test_first_bar_instrument_is_adopted() -> None:
    bridge, host = _bridge(), FakeHost()
    bridge.start()
    bridge.on_wheel_bar(host, _bar(0, iid=FakeIid("XYZ", "BSE")))
    assert bridge.instrument == "BSE:XYZ"
    assert bridge.sdk_strategy is not None
    assert bridge.sdk_strategy.instrument == "BSE:XYZ"  # type: ignore[attr-defined]
    # a different instrument after the first bar is ignored
    bridge.on_wheel_bar(host, _bar(1, iid=FakeIid("OTHER", "NSE")))
    assert bridge.instrument == "BSE:XYZ"


def test_scene_before_start_is_empty_and_after_start_delegates() -> None:
    bridge = _bridge()
    assert bridge.emit_scene().strategy_id == "scripted-empty"
    bridge.start()
    assert bridge.emit_scene().strategy_id == "scripted"
    bridge.stop()


def test_engine_epoch_nanosecond_timestamps_are_coerced_to_utc() -> None:
    """The wheel engine stamps bars with int epoch-ns; the bridge must not parse them as ISO."""
    from tantra_strategies.sdk.wheel_bridge import _coerce_datetime

    when = dt.datetime(2026, 5, 4, 3, 45, 7, 123456, tzinfo=dt.UTC)
    ns = int(when.replace(microsecond=0).timestamp()) * 1_000_000_000 + 123_456_789
    assert _coerce_datetime(ns) == when
    assert _coerce_datetime(when) is when
    assert _coerce_datetime("2026-05-04T03:45:07+00:00") == when.replace(microsecond=0)
