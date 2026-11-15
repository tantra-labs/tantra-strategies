import json
from decimal import Decimal
from pathlib import Path

import pytest

from tantra_strategies import (
    OrderSide,
    StopProtection,
    StopUpdate,
    Strategy,
    TrailMode,
)

GOLDEN = json.loads(
    (Path(__file__).resolve().parents[1] / "golden" / "stop_trail_golden.json").read_text()
)


def test_stop_protection_validation() -> None:
    with pytest.raises(ValueError):
        StopProtection(sl=Decimal("0"))
    with pytest.raises(ValueError):
        StopProtection(sl=Decimal("1"), trail_distance=Decimal("-0.5"))
    with pytest.raises(ValueError):
        StopProtection(sl=Decimal("1"), activation_after_r=Decimal("-1"))
    stop = StopProtection(
        sl=Decimal("99.75"),
        trail=TrailMode.ATR,
        trail_distance=Decimal("2"),
        activation_after_r=Decimal("1.5"),
    )
    assert stop.to_dict() == {
        "sl": "99.75",
        "trail": "atr",
        "trail_distance": "2",
        "activation_after_r": "1.5",
    }


def test_stop_loss_golden() -> None:
    strategy = Strategy()
    long_stop = strategy.stop_loss(OrderSide.BUY, (Decimal("100"), Decimal("102")), Decimal("0.25"))
    assert long_stop.sl == Decimal("99.75")
    assert str(long_stop.sl) == GOLDEN["long_reversal_sl"]["sl"]
    short_stop = strategy.stop_loss(
        OrderSide.SELL, (Decimal("100"), Decimal("102")), Decimal("0.25")
    )
    assert short_stop.sl == Decimal("102.25")
    assert str(short_stop.sl) == GOLDEN["short_breakout_sl"]["sl"]
    edge = strategy.stop_loss(OrderSide.BUY, (Decimal("100"), Decimal("102")), Decimal("0"))
    assert edge.sl == Decimal("100")
    with pytest.raises(ValueError):
        strategy.stop_loss(OrderSide.BUY, (Decimal("102"), Decimal("100")), Decimal("0.25"))


def test_stop_loss_never_inside_band() -> None:
    strategy = Strategy()
    with pytest.raises(ValueError):
        strategy.stop_loss(OrderSide.BUY, (Decimal("100"), Decimal("102")), Decimal("-0.5"))


def test_trail_stop_atr_golden() -> None:
    strategy = Strategy()
    long_stop = strategy.trail_stop(
        OrderSide.BUY,
        StopProtection(sl=Decimal("99.75"), trail=TrailMode.ATR, trail_distance=Decimal("2")),
        atr=Decimal("1.5"),
        extreme=Decimal("105"),
    )
    assert long_stop.sl == Decimal("102")
    assert long_stop.sl == Decimal(GOLDEN["atr_trail_long"]["new_sl"])
    short_stop = strategy.trail_stop(
        OrderSide.SELL,
        StopProtection(sl=Decimal("102.25"), trail=TrailMode.ATR, trail_distance=Decimal("2")),
        atr=Decimal("1.5"),
        extreme=Decimal("96"),
    )
    assert short_stop.sl == Decimal("99")
    assert short_stop.sl == Decimal(GOLDEN["atr_trail_short"]["new_sl"])
    unchanged = strategy.trail_stop(
        OrderSide.BUY,
        StopProtection(sl=Decimal("99.75"), trail=TrailMode.ATR, trail_distance=Decimal("2")),
        atr=Decimal("1.5"),
        extreme=Decimal("100"),
    )
    assert unchanged.sl == Decimal("99.75")
    assert unchanged.trail is TrailMode.ATR


def test_trail_stop_swing_golden() -> None:
    strategy = Strategy()
    stop = StopProtection(sl=Decimal("99.75"), trail=TrailMode.SWING)
    raised = strategy.trail_stop(OrderSide.BUY, stop, swing_level=Decimal("101.5"))
    assert raised.sl == Decimal("101.5")
    assert str(raised.sl) == GOLDEN["swing_trail_long"]["new_sl"]
    unchanged = strategy.trail_stop(OrderSide.BUY, stop, swing_level=Decimal("98"))
    assert unchanged.sl == Decimal("99.75")


def test_trail_stop_requires_arguments() -> None:
    strategy = Strategy()
    atr_stop = StopProtection(sl=Decimal("100"), trail=TrailMode.ATR, trail_distance=Decimal("1"))
    with pytest.raises(ValueError):
        strategy.trail_stop(OrderSide.BUY, atr_stop)
    with pytest.raises(ValueError):
        strategy.trail_stop(OrderSide.BUY, atr_stop, atr=Decimal("1"))
    with pytest.raises(ValueError):
        strategy.trail_stop(OrderSide.BUY, atr_stop, extreme=Decimal("105"))
    swing_stop = StopProtection(sl=Decimal("100"), trail=TrailMode.SWING)
    with pytest.raises(ValueError):
        strategy.trail_stop(OrderSide.BUY, swing_stop)
    off_stop = StopProtection(sl=Decimal("100"))
    assert strategy.trail_stop(OrderSide.BUY, off_stop) is off_stop


def test_stop_update_dispatch() -> None:
    recorded: list[StopUpdate] = []

    class Recorder(Strategy):
        def on_stop_update(self, event: StopUpdate) -> None:
            recorded.append(event)

    strategy = Recorder()
    strategy._emit_stop_update("NSE:X", OrderSide.BUY, Decimal("102"), Decimal("99.75"))
    assert len(recorded) == 1
    assert recorded[0].instrument == "NSE:X"
    assert recorded[0].side is OrderSide.BUY
    assert recorded[0].new_stop == Decimal("102")
    assert recorded[0].old_stop == Decimal("99.75")
