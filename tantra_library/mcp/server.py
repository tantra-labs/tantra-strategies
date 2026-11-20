"""Dependency-free MCP stdio server (newline-delimited JSON-RPC 2.0)."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import TextIO

from tantra_library import EntryKind, VolumeQuality, default_registry
from tantra_library.bar_source import BarSource, bar_source_from_env, bars_from_json
from tantra_library.errors import InvalidParam, LibraryError
from tantra_library.registry import Registry
from tantra_library.scene_projection import frame_to_scene, study_to_scene
from tantra_library.study import EventFilter, signal_study
from tantra_strategies.sdk.bar import Bar

MAX_LINE = 8 * 1024 * 1024
DEFAULT_PROTOCOL = "2025-06-18"

_BARS_PROPS: dict[str, object] = {
    "bars": {"type": "array", "items": {"type": "object"}, "maxItems": 5000},
    "bars_file": {"type": "string"},
    "instrument": {"type": "string"},
    "interval": {"type": "string", "default": "1d"},
    "volume_quality": {"type": "string", "enum": ["real", "tick", "none"], "default": "real"},
}


def _schema(props: Mapping[str, object], required: list[str]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": dict(props),
        "required": required,
        "additionalProperties": False,
    }


TOOLS: list[dict[str, object]] = [
    {
        "name": "tantra_library_search",
        "description": (
            "Search the concept & indicator library by text, kind or family "
            "(omit 'query' to list entries of a kind/family)."
        ),
        "inputSchema": _schema(
            {
                "query": {"type": "string", "default": ""},
                "kind": {"type": "string", "enum": [k.value for k in EntryKind]},
                "family": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 10},
            },
            [],
        ),
    },
    {
        "name": "tantra_library_describe",
        "description": "Describe a library entry as a markdown page or JSON.",
        "inputSchema": _schema(
            {
                "id": {"type": "string"},
                "format": {"type": "string", "enum": ["markdown", "json"], "default": "markdown"},
            },
            ["id"],
        ),
    },
    {
        "name": "tantra_indicator_compute",
        "description": "Compute an indicator over inline bars or a CSV under the data root.",
        "inputSchema": _schema(
            {
                "id": {"type": "string"},
                "params": {"type": "object"},
                **_BARS_PROPS,
                "tail": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 200},
                "overlay_scene": {"type": "boolean", "default": False},
            },
            ["id", "instrument"],
        ),
    },
    {
        "name": "tantra_signal_study",
        "description": "Forward-return study of a detector's events over the given bars.",
        "inputSchema": _schema(
            {
                "id": {"type": "string"},
                "params": {"type": "object"},
                "event_column": {"type": "string"},
                "direction": {"type": "integer", "enum": [1, -1], "default": 1},
                "horizons": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "maxItems": 10,
                },
                "filter": _schema(
                    {
                        "id": {"type": "string"},
                        "params": {"type": "object"},
                        "column": {"type": "string"},
                        "equals": {},
                    },
                    ["id", "column", "equals"],
                ),
                **_BARS_PROPS,
                "max_events": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
                "overlay_scene": {"type": "boolean", "default": False},
            },
            ["id", "event_column", "instrument"],
        ),
    },
]


def _default(o: object) -> str:
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(type(o).__name__)


def _bool_arg(args: Mapping[str, object], key: str) -> bool:
    v = args.get(key, False)
    if not isinstance(v, bool):
        raise InvalidParam(f"'{key}' must be a boolean")
    return v


def _dumps(o: object) -> str:
    return json.dumps(o, default=_default, separators=(",", ":"))


def _err(id_: object, code: int, msg: str) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": msg}}


def _str_arg(args: Mapping[str, object], key: str, default: str | None = None) -> str:
    v = args.get(key, default)
    if not isinstance(v, str):
        raise InvalidParam(f"'{key}' must be a string")
    return v


def _int_arg(args: Mapping[str, object], key: str, default: int, lo: int, hi: int) -> int:
    v = args.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise InvalidParam(f"'{key}' must be an integer in {lo}..{hi}")
    return v


def _obj_arg(args: Mapping[str, object], key: str) -> Mapping[str, object]:
    v = args.get(key, {})
    if not isinstance(v, Mapping):
        raise InvalidParam(f"'{key}' must be an object")
    return v


class LibraryMcpServer:
    def __init__(
        self, registry: Registry | None = None, bar_source: BarSource | None = None
    ) -> None:
        self._registry = registry if registry is not None else default_registry()
        if bar_source is None:
            bar_source = bar_source_from_env(os.environ)
        self._bars: BarSource | None = bar_source

    # ---- JSON-RPC ----
    def handle(self, message: Mapping[str, object]) -> dict[str, object] | None:
        method = message.get("method")
        id_ = message.get("id")
        is_notification = "id" not in message
        if not isinstance(method, str):
            return None if is_notification else _err(id_, -32600, "invalid request")
        if method.startswith("notifications/"):
            return None
        raw_params = message.get("params", {})
        if not isinstance(raw_params, Mapping):
            return _err(id_, -32602, "params must be an object")
        if method == "initialize":
            pv = raw_params.get("protocolVersion")
            result: dict[str, object] = {
                "protocolVersion": pv if isinstance(pv, str) else DEFAULT_PROTOCOL,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "tantra-library", "version": "0.1.0"},
                "instructions": (
                    "Concept & indicator library: describe a concept or indicator before "
                    "computing it. Decimal values are returned as strings."
                ),
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            name = raw_params.get("name")
            args = raw_params.get("arguments", {})
            if not isinstance(name, str) or not isinstance(args, Mapping):
                return _err(id_, -32602, "tools/call requires name and arguments object")
            result = self._call(name, args)
        else:
            return _err(id_, -32601, f"method not found: {method}")
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": id_, "result": result}

    def serve(self, stdin: TextIO, stdout: TextIO) -> None:
        for line in stdin:
            if not line.strip():
                continue
            if len(line) > MAX_LINE:
                resp: dict[str, object] | None = _err(None, -32600, "request too large")
            else:
                try:
                    msg = json.loads(line, parse_float=Decimal)
                except ValueError:
                    resp = _err(None, -32700, "parse error")
                else:
                    if isinstance(msg, Mapping):
                        resp = self.handle(msg)
                    else:
                        resp = _err(None, -32600, "invalid request")
            if resp is not None:
                stdout.write(_dumps(resp) + "\n")
                stdout.flush()

    # ---- tools ----
    def _call(self, name: str, args: Mapping[str, object]) -> dict[str, object]:
        try:
            text = self._dispatch(name, args)
            return {"content": [{"type": "text", "text": text}], "isError": False}
        except LibraryError as e:
            body = _dumps({"error": e.code, "message": str(e)})
        except Exception as e:
            print(f"tool {name} failed: {type(e).__name__}", file=sys.stderr)
            body = _dumps({"error": "internal_error", "message": type(e).__name__})
        return {"content": [{"type": "text", "text": body}], "isError": True}

    def _dispatch(self, name: str, args: Mapping[str, object]) -> str:
        reg = self._registry
        if name == "tantra_library_search":
            kind_s = args.get("kind")
            try:
                kind = EntryKind(str(kind_s)) if kind_s is not None else None
            except ValueError:
                raise InvalidParam(f"unknown kind {kind_s!r}") from None
            fam = args.get("family")
            if fam is not None and not isinstance(fam, str):
                raise InvalidParam("'family' must be a string")
            found = reg.search(
                _str_arg(args, "query", ""), kind, fam, _int_arg(args, "limit", 10, 1, 200)
            )
            return _dumps(
                [
                    {
                        "id": e.id,
                        "kind": e.kind.value,
                        "title": e.title,
                        "summary": e.summary,
                        "family": e.family,
                        "computable": e.computable,
                    }
                    for e in found
                ]
            )
        if name == "tantra_library_describe":
            eid = _str_arg(args, "id")
            fmt = _str_arg(args, "format", "markdown")
            if fmt == "markdown":
                return reg.describe_markdown(eid)
            if fmt == "json":
                return _dumps(reg.get(eid).to_dict())
            raise InvalidParam("format must be 'markdown' or 'json'")
        if name == "tantra_indicator_compute":
            want_scene = _bool_arg(args, "overlay_scene")
            bars, vq = self._load_bars(args)
            frame = reg.evaluate(
                _str_arg(args, "id"), _obj_arg(args, "params"), bars, source_volume_quality=vq
            )
            tail = _int_arg(args, "tail", 200, 1, 2000)
            d = frame.to_dict()
            total = len(bars)
            ts = d["timestamps"]
            cols = d["columns"]
            assert isinstance(ts, list) and isinstance(cols, dict)
            d["timestamps"] = ts[-tail:]
            d["columns"] = {k: v[-tail:] for k, v in cols.items()}
            d["total_rows"] = total
            if want_scene:
                d["overlay_scene"] = frame_to_scene(
                    reg.get(frame.entry_id),
                    frame,
                    bars,
                    symbol=_str_arg(args, "instrument"),
                    timeframe=_str_arg(args, "interval", "1d"),
                    tail=tail,
                ).to_dict()
            return _dumps(d)
        if name == "tantra_signal_study":
            want_scene = _bool_arg(args, "overlay_scene")
            bars, vq = self._load_bars(args)
            hz = args.get("horizons", [1, 3, 5, 10, 20])
            if not isinstance(hz, list) or not all(
                isinstance(h, int) and not isinstance(h, bool) for h in hz
            ):
                raise InvalidParam("'horizons' must be an array of integers")
            direction = args.get("direction", 1)
            if isinstance(direction, bool) or not isinstance(direction, int):
                raise InvalidParam("'direction' must be 1 or -1")
            flt: EventFilter | None = None
            raw_f = args.get("filter")
            if raw_f is not None:
                if not isinstance(raw_f, Mapping):
                    raise InvalidParam("'filter' must be an object")
                eq = raw_f.get("equals")
                if not isinstance(eq, (bool, int, str)):
                    raise InvalidParam("filter.equals must be a bool, integer or string")
                flt = EventFilter(
                    _str_arg(raw_f, "id"),
                    _obj_arg(raw_f, "params"),
                    _str_arg(raw_f, "column"),
                    eq,
                )
            res = signal_study(
                reg,
                _str_arg(args, "id"),
                _obj_arg(args, "params"),
                bars,
                event_column=_str_arg(args, "event_column"),
                direction=direction,
                horizons=hz,
                event_filter=flt,
                source_volume_quality=vq,
                max_events_listed=_int_arg(args, "max_events", 100, 1, 500),
            )
            out = res.to_dict()
            if want_scene:
                out["overlay_scene"] = study_to_scene(
                    res,
                    bars,
                    symbol=_str_arg(args, "instrument"),
                    timeframe=_str_arg(args, "interval", "1d"),
                ).to_dict()
            return _dumps(out)
        raise InvalidParam(f"unknown tool '{name}'")

    def _load_bars(self, args: Mapping[str, object]) -> tuple[list[Bar], VolumeQuality]:
        inst = _str_arg(args, "instrument")
        interval = _str_arg(args, "interval", "1d")
        try:
            vq = VolumeQuality(_str_arg(args, "volume_quality", "real"))
        except ValueError:
            raise InvalidParam("volume_quality must be real, tick or none") from None
        rows = args.get("bars")
        ref = args.get("bars_file")
        if (rows is None) == (ref is None):
            raise InvalidParam("exactly one of 'bars' or 'bars_file' is required")
        if rows is not None:
            if not isinstance(rows, list):
                raise InvalidParam("'bars' must be an array")
            return bars_from_json(rows, instrument=inst, interval=interval), vq
        if not isinstance(ref, str):
            raise InvalidParam("'bars_file' must be a string")
        if self._bars is None:
            raise InvalidParam(
                "no bar source configured (set TANTRA_LIBRARY_LAKEHOUSE_ROOT for the "
                "tantra-data lakehouse, or TANTRA_LIBRARY_DATA_ROOT for CSV files)"
            )
        return self._bars.load(ref, instrument=inst, interval=interval), vq


def main() -> None:
    LibraryMcpServer().serve(sys.stdin, sys.stdout)
