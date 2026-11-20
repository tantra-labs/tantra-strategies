"""Bar sources for the library MCP server.

* :class:`LakehouseBarSource` — tantra-data Lakehouse v3 (pinned commit, closed bars,
  Decimal prices) via ``tantra_data.service.library_bars.LakehouseBarReader``.
* :class:`CsvBarSource` — CSV files confined to a data root (tests / ad-hoc files).
* :func:`bars_from_json` — inline JSON rows.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

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


class _ClosedBar(Protocol):
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class _PinnedBars(Protocol):
    commit_sha: str
    bars: Sequence[_ClosedBar]


class _BarReader(Protocol):
    def read_closed_bars(
        self, instrument: str, *, interval: str = ..., ref: str = ...
    ) -> _PinnedBars: ...


def _default_reader(root: Path, max_rows: int) -> _BarReader:
    try:
        from tantra_data.service.library_bars import LakehouseBarReader
    except ImportError as exc:  # optional dependency (pip install tantra-strategies[lakehouse])
        raise InvalidParam(
            "lakehouse bar source needs the tantra-data package (tantra-strategies[lakehouse])"
        ) from exc
    reader: _BarReader = LakehouseBarReader(root, max_rows=max_rows)
    return reader


class LakehouseBarSource:
    """Reads closed bars from a tantra-data Lakehouse v3 root at a pinned ``ref``.

    ``ref`` is a branch, tag or commit sha; the commit it resolved to is kept in
    :attr:`last_commit_sha` so a study can be reproduced by passing it back as ``ref``.
    """

    def __init__(
        self, root: Path, *, max_rows: int = MAX_ROWS, reader: _BarReader | None = None
    ) -> None:
        self._reader = reader if reader is not None else _default_reader(root, max_rows)
        self.last_commit_sha: str | None = None

    def load(self, ref: str, *, instrument: str, interval: str) -> list[Bar]:
        try:
            pinned = self._reader.read_closed_bars(instrument, interval=interval, ref=ref)
        except Exception as exc:
            raise _map_reader_error(exc) from exc
        bars = [
            Bar(
                instrument=instrument,
                ts=row.ts,
                open=_price(row.open, "open"),
                high=_price(row.high, "high"),
                low=_price(row.low, "low"),
                close=_price(row.close, "close"),
                volume=row.volume,
                interval=interval,
            )
            for row in pinned.bars
        ]
        self.last_commit_sha = pinned.commit_sha
        return bars


def _map_reader_error(exc: Exception) -> Exception:
    name = type(exc).__name__
    if name == "BarLimitExceeded":
        return LimitExceeded(str(exc))
    if name in {"UnknownRef", "NonDecimalBars"}:
        return InvalidParam(f"{name}: {exc}")
    return exc


def bar_source_from_env(env: Mapping[str, str]) -> Any:
    """``TANTRA_LIBRARY_LAKEHOUSE_ROOT`` (preferred) or ``TANTRA_LIBRARY_DATA_ROOT`` (CSV)."""
    lake = env.get("TANTRA_LIBRARY_LAKEHOUSE_ROOT")
    if lake:
        return LakehouseBarSource(Path(lake))
    root = env.get("TANTRA_LIBRARY_DATA_ROOT")
    return CsvBarSource(Path(root)) if root else None
