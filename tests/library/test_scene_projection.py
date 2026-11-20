from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal

from tantra_library import default_registry
from tantra_library.mcp.server import LibraryMcpServer
from tantra_library.scene_projection import frame_to_scene, study_to_scene
from tantra_library.study import signal_study
from tantra_strategies.sdk.bar import Bar
from tantra_strategies.sdk.scene import HintSeverity, MarkerKind, MarkerSide

N = 320
T0 = datetime(2024, 1, 1)


def _closes() -> list[int]:
    # trend + oscillation, deterministic, integers only
    return [1000 + (i * 3) // 2 + ((i * 37) % 41) - 20 + 15 * ((i // 40) % 2) for i in range(N)]


def _bars() -> list[Bar]:
    out = []
    for i, c in enumerate(_closes()):
        out.append(
            Bar(
                instrument="X",
                ts=T0 + timedelta(days=i),
                open=Decimal(c),
                high=Decimal(c + 5),
                low=Decimal(c - 5),
                close=Decimal(c + 1),
                volume=1000 + i,
            )
        )
    return out


def _project(eid: str, params: dict[str, object] | None = None, tail: int | None = None):
    reg = default_registry()
    bars = _bars()
    frame = reg.evaluate(eid, params or {}, bars)
    return frame_to_scene(reg.get(eid), frame, bars, symbol="X", timeframe="1d", tail=tail), frame


def test_predictive_ranges_bands_and_series() -> None:
    scene, _ = _project("ind.predictive-ranges", {"length": 20})
    assert scene.bands
    assert len(scene.bands) <= 400
    assert all(b.low <= b.high for b in scene.bands)
    names = {s.name for s in scene.indicators}
    assert "center" in names and "pane:center_step" in names
    assert "s1" not in names and "r2" not in names
    json.dumps(scene.to_dict())


def test_series_for_atr() -> None:
    scene, _ = _project("ind.atr")
    s = [x for x in scene.indicators if x.name == "atr"]
    assert len(s) == 1 and len(s[0].points) <= N
    assert not scene.bands


def test_tail_reindexes() -> None:
    scene, _ = _project("ind.atr", tail=50)
    pts = scene.indicators[0].points
    assert len(pts) <= 50
    assert min(p.x for p in pts) >= 0 and max(p.x for p in pts) <= 49


def test_event_markers_sides_and_kinds() -> None:
    scene, frame = _project("det.pr-zone-touch", {"length": 20})
    sup = sum(1 for v in frame.columns["support_touch"] if v)
    res = sum(1 for v in frame.columns["resistance_touch"] if v)
    assert len(scene.signals) == sup + res
    assert scene.signals, "expected some touches"
    assert all(s.kind == MarkerKind.RETEST for s in scene.signals)
    assert {s.side for s in scene.signals} <= {MarkerSide.BUY, MarkerSide.SELL}
    assert len(scene.hints) <= 100


def test_sweep_kind_and_side() -> None:
    from tantra_library.scene_projection import _kind, _side

    assert _kind("bear_sweep") == MarkerKind.SWEEP
    assert _side("bear_sweep") == MarkerSide.SELL
    assert _side("bull_sweep") == MarkerSide.BUY
    assert _kind("x_reversal") == MarkerKind.REVERSAL
    assert _kind("other") == MarkerKind.BREAKOUT


def test_study_scene() -> None:
    reg = default_registry()
    bars = _bars()
    res = signal_study(reg, "det.pr-zone-touch", {"length": 20}, bars, event_column="support_touch")
    scene = study_to_scene(res, bars, symbol="X", timeframe="1d")
    assert len(scene.signals) == min(res.event_count, 500)
    assert all(s.side == MarkerSide.BUY for s in scene.signals)
    if res.event_count:
        (hint,) = scene.hints
        assert len(hint.metrics) == 2 * len(res.horizons)
        longest = max(res.horizons, key=lambda h: h.horizon)
        want = HintSeverity.POSITIVE if longest.hit_rate > Decimal("0.5") else HintSeverity.WARNING
        assert hint.severity == want
        assert hint.detail == f"{len(scene.signals)} of {res.event_count} events shown"
    json.dumps(scene.to_dict())


def _rows() -> list[dict[str, object]]:
    return [
        {
            "ts": b.ts.isoformat(),
            "open": str(b.open),
            "high": str(b.high),
            "low": str(b.low),
            "close": str(b.close),
            "volume": b.volume,
        }
        for b in _bars()
    ]


def _call(name: str, args: dict[str, object]) -> tuple[bool, str]:
    resp = LibraryMcpServer().handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }
    )
    assert resp is not None
    res = resp["result"]
    return bool(res["isError"]), str(res["content"][0]["text"])  # type: ignore[index]


def test_mcp_compute_overlay_scene() -> None:
    base = {
        "id": "ind.predictive-ranges",
        "params": {"length": 20},
        "instrument": "X",
        "bars": _rows(),
        "tail": 100,
    }
    err, text = _call("tantra_indicator_compute", {**base, "overlay_scene": True})
    assert not err
    d = json.loads(text)
    assert d["overlay_scene"]["strategy_id"] == "ind.predictive-ranges"
    assert d["overlay_scene"]["bands"]
    err, text = _call("tantra_indicator_compute", base)
    assert not err and "overlay_scene" not in json.loads(text)
    err, _ = _call("tantra_indicator_compute", {**base, "overlay_scene": "yes"})
    assert err


def test_mcp_study_overlay_scene() -> None:
    args = {
        "id": "det.pr-zone-touch",
        "params": {"length": 20},
        "event_column": "support_touch",
        "instrument": "X",
        "bars": _rows(),
    }
    err, text = _call("tantra_signal_study", {**args, "overlay_scene": True})
    assert not err
    assert "signals" in json.loads(text)["overlay_scene"]
    err, _ = _call("tantra_signal_study", {**args, "overlay_scene": "yes"})
    assert err
