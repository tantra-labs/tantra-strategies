"""LakehouseBarSource: tantra-data Lakehouse v3 bars feed tantra_library (closes data gap 0026)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tantra_library.bar_source import (
    CsvBarSource,
    LakehouseBarSource,
    bar_source_from_env,
)
from tantra_library.errors import InvalidParam, LimitExceeded
from tantra_library.mcp.server import LibraryMcpServer


@dataclass(frozen=True)
class _Row:
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True)
class _Pinned:
    commit_sha: str
    bars: tuple[_Row, ...]


class _FakeReader:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self._error = error

    def read_closed_bars(
        self, instrument: str, *, interval: str = "1d", ref: str = "main"
    ) -> _Pinned:
        self.calls.append((instrument, interval, ref))
        if self._error is not None:
            raise self._error
        rows = tuple(
            _Row(
                datetime(2024, 1, d, tzinfo=UTC),
                Decimal(100 + d),
                Decimal(105 + d),
                Decimal(99 + d),
                Decimal("104.5") + d,
                1000 * d,
            )
            for d in (1, 2, 3)
        )
        return _Pinned("ab" * 32, rows)


class UnknownRef(Exception):  # same class names as tantra_data.service.library_bars
    pass


class BarLimitExceeded(Exception):
    pass


def test_maps_closed_bars_and_records_pinned_commit() -> None:
    reader = _FakeReader()
    source = LakehouseBarSource(Path("/unused"), reader=reader)
    bars = source.load("pin-1", instrument="NSE:RELIANCE-EQ", interval="1d")
    assert reader.calls == [("NSE:RELIANCE-EQ", "1d", "pin-1")]
    assert [b.close for b in bars] == [Decimal("105.5"), Decimal("106.5"), Decimal("107.5")]
    assert all(isinstance(b.open, Decimal) for b in bars)
    assert bars[0].instrument == "NSE:RELIANCE-EQ" and bars[0].interval == "1d"
    assert source.last_commit_sha == "ab" * 32


def test_reader_errors_map_to_library_errors() -> None:
    with pytest.raises(InvalidParam, match="UnknownRef"):
        LakehouseBarSource(Path("/x"), reader=_FakeReader(UnknownRef("nope"))).load(
            "nope", instrument="X", interval="1d"
        )
    with pytest.raises(LimitExceeded):
        LakehouseBarSource(Path("/x"), reader=_FakeReader(BarLimitExceeded("big"))).load(
            "main", instrument="X", interval="1d"
        )


def test_env_selection_prefers_lakehouse(tmp_path: Path) -> None:
    assert bar_source_from_env({}) is None
    assert isinstance(
        bar_source_from_env({"TANTRA_LIBRARY_DATA_ROOT": str(tmp_path)}), CsvBarSource
    )
    both = {
        "TANTRA_LIBRARY_DATA_ROOT": str(tmp_path),
        "TANTRA_LIBRARY_LAKEHOUSE_ROOT": str(tmp_path),
    }
    assert isinstance(bar_source_from_env(both), LakehouseBarSource)


def test_mcp_indicator_compute_reads_from_the_lakehouse_source() -> None:
    reader = _FakeReader()
    server = LibraryMcpServer(bar_source=LakehouseBarSource(Path("/x"), reader=reader))
    reply = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "tantra_indicator_compute",
                "arguments": {
                    "id": "ind.atr",
                    "params": {"period": 2},
                    "instrument": "NSE:RELIANCE-EQ",
                    "bars_file": "pin-1",
                },
            },
        }
    )
    assert reply is not None
    result = reply["result"]
    assert isinstance(result, dict) and result["isError"] is False, result
    body = json.loads(result["content"][0]["text"])
    assert body["total_rows"] == 3
    assert reader.calls == [("NSE:RELIANCE-EQ", "1d", "pin-1")]


def test_real_tantra_data_lakehouse_end_to_end(tmp_path: Path) -> None:
    pl = pytest.importorskip("polars")
    pytest.importorskip("tantra_data.service.library_bars")
    from tantra_data.adapters.cas_store import write_cas_object
    from tantra_data.adapters.manifest_store import SCHEMA_VERSION, ManifestStore
    from tantra_data.domain.lakehouse import InstrumentAlias, ManifestEntry

    uid, days = "INE002A01018", [1, 2, 3]
    df = pl.DataFrame(
        {
            "instrument_uid": [uid] * 3,
            "ts": [datetime(2024, 1, d, tzinfo=UTC) for d in days],
            "open": [f"{100 + d}.0000" for d in days],
            "high": [f"{105 + d}.0000" for d in days],
            "low": [f"{99 + d}.0000" for d in days],
            "close": [f"{104 + d}.5000" for d in days],
            "volume": [1000 * d for d in days],
        }
    ).with_columns(pl.col(c).cast(pl.Decimal(18, 4)) for c in ("open", "high", "low", "close"))
    store = ManifestStore(tmp_path)
    try:
        store.write_alias(InstrumentAlias("NSE", "RELIANCE", "EQ", date(2020, 1, 1), None, uid))
        sha = write_cas_object(df, sort_key=["instrument_uid", "ts"], root=tmp_path)
        store.commit(
            "bars",
            as_of_ist=date(2024, 1, 2),  # day 3 is after the commit boundary: excluded
            schema_version=SCHEMA_VERSION,
            parent=None,
            entries=[
                ManifestEntry(
                    domain="market",
                    dataset="bars",
                    exchange="NSE",
                    asset_class="EQ",
                    timeframe="1d",
                    time_bucket="year=2024",
                    object_sha=sha,
                    min_ts=datetime(2024, 1, 1, tzinfo=UTC),
                    max_ts=datetime(2024, 1, 3, tzinfo=UTC),
                    row_count=3,
                    sort_key="(instrument_uid, ts)",
                )
            ],
        )
    finally:
        store.close()

    source = LakehouseBarSource(tmp_path)
    bars = source.load("main", instrument="NSE:RELIANCE-EQ", interval="1d")
    assert [b.close for b in bars] == [Decimal("105.5000"), Decimal("106.5000")]
    assert source.last_commit_sha is not None
    again = source.load(source.last_commit_sha, instrument="NSE:RELIANCE-EQ", interval="1d")
    assert again == bars
