"""Bar sources for the library MCP server (CSV files under a data root, inline JSON rows).

The lakehouse (tantra-data Parquet v3) source is not wired yet:
# stand-in for tantra-data/docs/gaps/<TBD>-strategies-lakehouse-bar-source.md
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol

from tantra_library.errors import InvalidParam, LimitExceeded
from tantra_strategies.sdk.bar import Bar

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_ROWS = 200_000
MAX_INLINE_ROWS = 5_000


class BarSource(Protocol):
    def load(self, ref: str, *, instrument: str, interval: str) -> list[Bar]: ...


def _price(value: object, name: str) -> Decimal:
    if isinstance(value, (bool, float)):
        raise InvalidParam(f"{name} must be a string, integer or Decimal, not float/bool")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (str, int)):
        try:
            return Decimal(value)
        except InvalidOperation:
            raise InvalidParam(f"{name} is not a valid decimal: {value!r}") from None
    raise InvalidParam(f"{name} must be a string, integer or Decimal")


def _row_to_bar(row: Mapping[str, object], *, instrument: str, interval: str) -> Bar:
    try:
        ts_raw = row["ts"]
        if not isinstance(ts_raw, str):
            raise InvalidParam("ts must be an ISO-8601 string")
        ts = datetime.fromisoformat(ts_raw)
        vol_raw = row.get("volume", 0)
        if isinstance(vol_raw, str):
            vol_raw = int(vol_raw) if vol_raw.strip() else 0
        if isinstance(vol_raw, bool) or not isinstance(vol_raw, int):
            raise InvalidParam("volume must be an integer")
        return Bar(
            instrument=instrument,
            ts=ts,
            open=_price(row["open"], "open"),
            high=_price(row["high"], "high"),
            low=_price(row["low"], "low"),
            close=_price(row["close"], "close"),
            volume=vol_raw,
            interval=interval,
        )
    except KeyError as exc:
        raise InvalidParam(f"bar row missing field {exc.args[0]}") from None
    except ValueError as exc:
        raise InvalidParam(f"invalid bar row: {exc}") from None


def bars_from_json(
    rows: Sequence[Mapping[str, object]], *, instrument: str, interval: str
) -> list[Bar]:
    if len(rows) > MAX_INLINE_ROWS:
        raise LimitExceeded(f"at most {MAX_INLINE_ROWS} inline bars allowed")
    out: list[Bar] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise InvalidParam("each bar row must be an object")
        out.append(_row_to_bar(row, instrument=instrument, interval=interval))
    return out


class CsvBarSource:
    """Reads ``ts,open,high,low,close,volume`` CSV files confined to ``root``."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def load(self, ref: str, *, instrument: str, interval: str) -> list[Bar]:
        path = (self._root / ref).resolve()
        if not path.is_relative_to(self._root):
            raise InvalidParam("path escapes data root")
        if path.suffix.lower() != ".csv":
            raise InvalidParam("only .csv files are supported")
        if not path.is_file():
            raise InvalidParam(f"bars file not found: {ref}")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise LimitExceeded("bars file exceeds 64 MiB")
        bars: list[Bar] = []
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if len(bars) >= MAX_ROWS:
                    raise LimitExceeded(f"bars file exceeds {MAX_ROWS} rows")
                bars.append(_row_to_bar(row, instrument=instrument, interval=interval))
        return bars
