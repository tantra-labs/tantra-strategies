"""Data model: entries, parameter specs, outputs, frames."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Protocol

from tantra_library.errors import InvalidParam
from tantra_strategies.sdk.bar import Bar


class EntryKind(StrEnum):
    FAMILY = "family"
    CONCEPT = "concept"
    PRIMITIVE = "primitive"
    INDICATOR = "indicator"
    COMPOSITE = "composite"
    DETECTOR = "detector"
    RECIPE = "recipe"


class Determinism(StrEnum):
    CLOSED_BAR_STABLE = "closed-bar-stable"
    REPAINTS_LIVE = "repaints-live"


class InputKind(StrEnum):
    NONE = "none"
    OHLC = "ohlc"
    OHLCV = "ohlcv"


class VolumeQuality(StrEnum):
    REAL = "real"
    TICK = "tick"
    NONE = "none"


class ParamType(StrEnum):
    INT = "int"
    DECIMAL = "decimal"
    ENUM = "enum"
    BOOL = "bool"


class OutputUnit(StrEnum):
    PRICE = "price"
    RATIO = "ratio"
    PERCENT = "percent"
    STATE = "state"
    EVENT = "event"
    VOLUME = "volume"


ParamValue = int | Decimal | str | bool
Value = Decimal | int | bool | None


def _json_param(v: ParamValue) -> object:
    return str(v) if isinstance(v, Decimal) else v


@dataclass(frozen=True, slots=True)
class ParamSpec:
    name: str
    type: ParamType
    default: ParamValue
    description: str
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    choices: tuple[str, ...] = ()

    def _fail(self, msg: str) -> InvalidParam:
        return InvalidParam(f"parameter '{self.name}': {msg}")

    def coerce(self, raw: object) -> ParamValue:
        if isinstance(raw, float):
            raise self._fail("floats are not accepted; pass a string")
        value: ParamValue
        if self.type is ParamType.INT:
            if isinstance(raw, bool):
                raise self._fail("expected int, got bool")
            if isinstance(raw, int):
                value = raw
            elif isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
                value = int(raw.strip())
            else:
                raise self._fail(f"expected int, got {raw!r}")
        elif self.type is ParamType.DECIMAL:
            if isinstance(raw, bool):
                raise self._fail("expected decimal, got bool")
            if isinstance(raw, Decimal):
                dec = raw
            elif isinstance(raw, int | str):
                try:
                    dec = Decimal(raw.strip() if isinstance(raw, str) else raw)
                except InvalidOperation:
                    raise self._fail(f"invalid decimal {raw!r}") from None
            else:
                raise self._fail(f"expected decimal, got {type(raw).__name__}")
            if not dec.is_finite():
                raise self._fail("decimal must be finite")
            value = dec
        elif self.type is ParamType.BOOL:
            if not isinstance(raw, bool):
                raise self._fail(f"expected bool, got {raw!r}")
            value = raw
        else:
            if not isinstance(raw, str) or raw not in self.choices:
                raise self._fail(f"expected one of {list(self.choices)}, got {raw!r}")
            value = raw
        if self.type in (ParamType.INT, ParamType.DECIMAL):
            num = Decimal(value) if isinstance(value, int) else value
            assert isinstance(num, Decimal)
            if self.minimum is not None and num < self.minimum:
                raise self._fail(f"{num} is below minimum {self.minimum}")
            if self.maximum is not None and num > self.maximum:
                raise self._fail(f"{num} is above maximum {self.maximum}")
        return value

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "type": self.type.value,
            "default": _json_param(self.default),
            "description": self.description,
            "minimum": None if self.minimum is None else str(self.minimum),
            "maximum": None if self.maximum is None else str(self.maximum),
            "choices": list(self.choices),
        }


@dataclass(frozen=True, slots=True)
class OutputSpec:
    name: str
    unit: OutputUnit
    description: str

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "unit": self.unit.value, "description": self.description}


@dataclass(frozen=True, slots=True)
class Provenance:
    origin: str
    reference_url: str | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        return {"origin": self.origin, "reference_url": self.reference_url, "notes": self.notes}


class StreamingComputation(Protocol):
    def update(self, bar: Bar) -> Mapping[str, Value]: ...

    def reset(self) -> None: ...


Factory = Callable[[Mapping[str, ParamValue]], StreamingComputation]


@dataclass(frozen=True, slots=True)
class Entry:
    id: str
    kind: EntryKind
    title: str
    summary: str
    family: str | None = None
    concepts: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    params: tuple[ParamSpec, ...] = ()
    outputs: tuple[OutputSpec, ...] = ()
    inputs: InputKind = InputKind.NONE
    volume_quality: VolumeQuality = VolumeQuality.NONE
    determinism: Determinism = Determinism.CLOSED_BAR_STABLE
    aliases: tuple[str, ...] = ()
    related: tuple[str, ...] = ()
    provenance: Provenance | None = None
    body_md: str = ""
    factory: Factory | None = field(default=None, compare=False, repr=False)

    @property
    def computable(self) -> bool:
        return self.factory is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "title": self.title,
            "summary": self.summary,
            "family": self.family,
            "concepts": list(self.concepts),
            "depends_on": list(self.depends_on),
            "params": [p.to_dict() for p in self.params],
            "outputs": [o.to_dict() for o in self.outputs],
            "inputs": self.inputs.value,
            "volume_quality": self.volume_quality.value,
            "determinism": self.determinism.value,
            "aliases": list(self.aliases),
            "related": list(self.related),
            "provenance": None if self.provenance is None else self.provenance.to_dict(),
            "body_md": self.body_md,
            "computable": self.computable,
        }


def _json_value(v: Value) -> object:
    return str(v) if isinstance(v, Decimal) else v


@dataclass(slots=True)
class Frame:
    entry_id: str
    params: dict[str, ParamValue]
    timestamps: list[datetime]
    columns: dict[str, list[Value]]

    def to_dict(self) -> dict[str, object]:
        return {
            "entry_id": self.entry_id,
            "params": {k: _json_param(v) for k, v in self.params.items()},
            "timestamps": [t.isoformat() for t in self.timestamps],
            "columns": {k: [_json_value(v) for v in col] for k, col in self.columns.items()},
        }
