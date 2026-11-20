"""SDK indicator wrappers must match the ``tantra_library`` Decimal kernel."""

from __future__ import annotations

import subprocess
import sys
from decimal import Decimal

import pytest

from tantra_library.indicators import ATR as LibATR
from tantra_library.indicators import EMA as LibEMA
from tantra_library.indicators import RSI as LibRSI
from tantra_library.indicators import BollingerBands as LibBB
from tantra_library.primitives import SMA as LibSMA
from tantra_strategies.sdk import indicators as sdk
from tantra_strategies.sdk.bar import Bar


def _series() -> list[Decimal]:
    out: list[Decimal] = []
    for i in range(80):
        out.append(Decimal(10000 + (i * 37) % 91 - (i * i) % 53) / Decimal(100))
    return out


def _bars() -> list[Bar]:
    import datetime as dt

    bars: list[Bar] = []
    for i, c in enumerate(_series()):
        bars.append(
            Bar(
                instrument="X",
                ts=dt.datetime(2024, 1, 1) + dt.timedelta(days=i),
                open=c - Decimal("0.3"),
                high=c + Decimal(1 + i % 4) / 2,
                low=c - Decimal(1 + i % 3) / 2,
                close=c,
                volume=1000,
            )
        )
    return bars


@pytest.mark.parametrize("period", [3, 14])
def test_sma_parity(period: int) -> None:
    w, lib = sdk.SMA(period), LibSMA(period)
    for x in _series():
        w.update(x)
        expected = lib.update(x)
        assert w.ready == (expected is not None)
        if expected is not None:
            assert w.value == expected


@pytest.mark.parametrize("period", [3, 12])
def test_ema_parity(period: int) -> None:
    w, lib = sdk.EMA(period), LibEMA(period)
    for x in _series():
        w.update(x)
        assert w.value == lib.update(x)


@pytest.mark.parametrize("period", [5, 14])
def test_rsi_parity(period: int) -> None:
    w, lib = sdk.RSI(period), LibRSI(period)
    for x in _series():
        w.update(x)
        expected = lib.update(x)
        assert w.ready == (expected is not None)
        if expected is not None:
            assert w.value == expected


@pytest.mark.parametrize("period", [4, 14])
def test_atr_parity(period: int) -> None:
    w, lib = sdk.ATR(period), LibATR(period)
    for bar in _bars():
        w.update(bar)
        expected = lib.update(bar)
        assert w.ready == (expected is not None)
        if expected is not None:
            assert w.value == expected


def test_bollinger_parity() -> None:
    w, lib = sdk.BollingerBands(10, Decimal("2.5")), LibBB(10, Decimal("2.5"))
    for x in _series():
        w.update(x)
        expected = lib.update(x)
        assert w.ready == (expected is not None)
        if expected is not None:
            assert (w.lower, w.middle, w.upper) == (expected.lower, expected.middle, expected.upper)


@pytest.mark.parametrize(
    "code",
    [
        "import tantra_library; import tantra_strategies.sdk",
        "import tantra_strategies.sdk; import tantra_library",
        "import tantra_strategies.sdk.indicators",
        "import tantra_library.indicators",
    ],
)
def test_import_orders_succeed_in_fresh_interpreters(code: str) -> None:
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_library_ema_rsi_bollinger_warmup_and_reset() -> None:
    xs = _series()
    rsi = LibRSI(5)
    assert [rsi.update(x) for x in xs[:5]] == [None] * 5
    assert rsi.update(xs[5]) is not None
    bb = LibBB(4)
    assert [bb.update(x) for x in xs[:3]] == [None] * 3
    first = bb.update(xs[3])
    assert first is not None and first.lower <= first.middle <= first.upper
    ema = LibEMA(3)
    assert ema.value is None
    assert ema.update(xs[0]) == xs[0]
    for ind in (rsi, bb, ema):
        ind.reset()
        assert ind.value is None
    assert bb.update(xs[0]) is None
    assert rsi.update(xs[0]) is None


@pytest.mark.parametrize("deviations", [Decimal(-1), Decimal("NaN")])
def test_sdk_bollinger_rejects_invalid_deviations_with_value_error(deviations: Decimal) -> None:
    from tantra_strategies.sdk.indicators import BollingerBands as SdkBB

    with pytest.raises(ValueError, match="deviations"):
        SdkBB(5, deviations)
