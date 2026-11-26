from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from tantra_library.bar_source import CsvBarSource
from tantra_library.errors import InvalidParam
from tantra_library.mcp.server import LibraryMcpServer


def _rows(n: int = 30) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    d0 = date(2024, 1, 1)
    for i in range(n):
        c = 100 + (i * 7) % 11 + i // 3
        out.append(
            {
                "ts": (d0 + timedelta(days=i)).isoformat() + "T00:00:00",
                "open": str(c),
                "high": str(c + 2),
                "low": str(c - 2),
                "close": str(c + 1),
                "volume": 1000 + i,
            }
        )
    return out


def _call(srv: LibraryMcpServer, name: str, args: dict[str, object]) -> tuple[bool, str]:
    resp = srv.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }
    )
    assert resp is not None
    res = resp["result"]
    assert isinstance(res, dict)
    return bool(res["isError"]), str(res["content"][0]["text"])  # type: ignore[index]


@pytest.fixture
def srv() -> LibraryMcpServer:
    return LibraryMcpServer()


def test_initialize_and_list(srv: LibraryMcpServer) -> None:
    r = srv.handle({"id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}})
    assert r is not None and r["result"]["protocolVersion"] == "2024-11-05"  # type: ignore[index]
    r = srv.handle({"id": 2, "method": "tools/list"})
    assert r is not None
    tools = r["result"]["tools"]  # type: ignore[index]
    assert len(tools) == 4 and all("inputSchema" in t for t in tools)


def test_notification_and_unknown(srv: LibraryMcpServer) -> None:
    assert srv.handle({"method": "notifications/initialized"}) is None
    r = srv.handle({"id": 3, "method": "nope"})
    assert r is not None and r["error"]["code"] == -32601  # type: ignore[index]


def test_search_describe(srv: LibraryMcpServer) -> None:
    err, text = _call(srv, "tantra_library_search", {"query": "predictive"})
    assert not err and json.loads(text)[0]["id"] == "ind.predictive-ranges"
    err, text = _call(srv, "tantra_library_describe", {"id": "ind.predictive-ranges"})
    assert not err and "# Predictive Ranges" in text
    err, text = _call(srv, "tantra_library_describe", {"id": "nope.x"})
    assert err and json.loads(text)["error"] == "unknown_entry"


def test_compute_tail(srv: LibraryMcpServer) -> None:
    err, text = _call(
        srv,
        "tantra_indicator_compute",
        {"id": "ind.atr", "bars": _rows(), "instrument": "X", "tail": 5},
    )
    assert not err, text
    d = json.loads(text)
    assert d["total_rows"] == 30 and len(d["timestamps"]) == 5


def test_float_and_both_sources(srv: LibraryMcpServer) -> None:
    rows = _rows()
    rows[0]["close"] = 1.5
    err, text = _call(
        srv, "tantra_indicator_compute", {"id": "ind.atr", "bars": rows, "instrument": "X"}
    )
    assert err and json.loads(text)["error"] == "invalid_param"
    err, _ = _call(
        srv,
        "tantra_indicator_compute",
        {"id": "ind.atr", "bars": _rows(), "bars_file": "a.csv", "instrument": "X"},
    )
    assert err
    err, text = _call(
        srv, "tantra_indicator_compute", {"id": "ind.atr", "bars_file": "a.csv", "instrument": "X"}
    )
    assert err and "no bar source configured" in text


def test_signal_study(srv: LibraryMcpServer) -> None:
    err, text = _call(
        srv,
        "tantra_signal_study",
        {
            "id": "det.pr-center-step",
            "params": {"length": 3, "factor": 1},
            "event_column": "step_up",
            "bars": _rows(),
            "instrument": "X",
            "horizons": [1, 2],
        },
    )
    assert not err, text
    assert "event_count" in json.loads(text)


def test_csv_source(tmp_path: Path) -> None:
    (tmp_path / "a.csv").write_text(
        "ts,open,high,low,close,volume\n2024-01-01T00:00:00,1.10,1.20,1.00,1.15,5\n"
    )
    src = CsvBarSource(tmp_path)
    bars = src.load("a.csv", instrument="X", interval="1d")
    assert bars[0].close == Decimal("1.15")
    with pytest.raises(InvalidParam):
        src.load("../escape.csv", instrument="X", interval="1d")
    (tmp_path / "a.txt").write_text("x")
    with pytest.raises(InvalidParam):
        src.load("a.txt", instrument="X", interval="1d")


def test_subprocess_smoke() -> None:
    inp = (
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        + "\n"
    )
    p = subprocess.run(
        [sys.executable, "-m", "tantra_library.mcp"],
        input=inp,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    lines = [json.loads(x) for x in p.stdout.splitlines() if x.strip()]
    assert [m["id"] for m in lines] == [1, 2]


def test_search_lists_by_kind_without_query() -> None:
    """Agents/runtime list entries by kind without a text query (tantra-agent-core contract)."""
    reply = LibraryMcpServer().handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "tantra_library_search",
                "arguments": {"kind": "composite", "limit": 200},
            },
        }
    )
    assert reply is not None
    result = cast(dict[str, Any], reply["result"])
    assert result["isError"] is False, result
    items = json.loads(result["content"][0]["text"])
    assert {i["kind"] for i in items} == {"composite"}
    assert any(i["id"] == "ind.predictive-ranges" for i in items)
