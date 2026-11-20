#!/usr/bin/env python3
"""Validate pipeline step manifests and whole step chains for the examples runner.

The tantra-examples chain runner loads this module from the tantra-strategies
checkout (``tantra_examples.catalog.load_catalog_tool("validate_chain")``) and calls:

* ``schema_errors(manifest)`` - structural errors in one step manifest; empty
  means valid.
* ``validate_chain(manifests)`` - errors for a full chain of step manifests
  (each carries the chain file's ``with`` and ``report`` on top of the manifest);
  empty means valid.

A step manifest is the ``step.toml`` / pipeline ``describe()`` shape::

    {
      "schema": 1, "id": "size.equal_weight", "kind": "size", "title": "...",
      "params": {"name": {"type": "float", "min": 0.0, "max": 100.0, ...}},
      "consumes": {"shape": "candidates", "columns": ["symbol"]},
      "emits": {"shape": "weights", "adds": [], "report": [], "reportable": []},
    }

Kinds run in the order screen, filter, signal, size, risk, execute; repeats are
allowed and going backwards is not. Shapes progress ``universe -> candidates ->
weights -> orders``; ``consumes.shape`` may be a list of accepted shapes.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

__all__ = ["schema_errors", "validate_chain"]

KIND_ORDER = ("screen", "filter", "signal", "size", "risk", "execute")
KINDS = frozenset(KIND_ORDER)
SHAPES = frozenset({"universe", "candidates", "weights", "orders", "result", "none"})
REQUIRED_KEYS = (
    "schema",
    "id",
    "kind",
    "title",
    "description",
    "tags",
    "version",
    "strategy_api_version",
    "params",
    "requires",
    "consumes",
    "emits",
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BASE_COLUMN = "symbol"


def _as_list(value: object) -> list[str]:
    """Normalise a shape field (string or list) to a list of strings."""
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def schema_errors(manifest: dict[str, Any]) -> list[str]:
    """Structural errors in one step manifest (``describe()`` / ``step.toml``)."""
    errors: list[str] = []
    for key in REQUIRED_KEYS:
        if key not in manifest:
            errors.append(f"missing required key {key!r}")

    sid = manifest.get("id")
    kind = manifest.get("kind")
    if sid is not None and kind is not None:
        if "." not in str(sid):
            errors.append(f"id {sid!r} must be '<kind>.<name>'")
        elif str(sid).split(".", 1)[0] != str(kind):
            errors.append(f"id {sid!r} does not match kind {kind!r}")
        if str(kind) not in KINDS:
            errors.append(f"kind {kind!r} must be one of {sorted(KINDS)}")

    params = manifest.get("params")
    if params is not None and not isinstance(params, dict):
        errors.append("'params' must be an object")
    elif isinstance(params, dict):
        for name, spec in params.items():
            if not isinstance(spec, dict):
                errors.append(f"param {name!r} must be an object")
                continue
            if "type" not in spec:
                errors.append(f"param {name!r} requires a 'type'")
            if "description" not in spec:
                errors.append(f"param {name!r} requires a 'description'")
            if not spec.get("optional") and "default" not in spec:
                errors.append(f"param {name!r} requires a 'default'")
            if spec.get("type") == "enum" and not spec.get("choices"):
                errors.append(f"param {name!r} of type 'enum' requires 'choices'")
            is_decimal = spec.get("type") == "decimal"
            if is_decimal and "default" in spec and _as_decimal(spec["default"]) is None:
                errors.append(f"param {name!r} default must be a decimal string or int")
            for bound in ("min", "max", "step"):
                if bound not in spec:
                    continue
                if is_decimal:
                    if _as_decimal(spec[bound]) is None:
                        errors.append(f"param {name!r} {bound} must be a decimal string or int")
                elif not isinstance(spec[bound], (int, float)):
                    errors.append(f"param {name!r} {bound} must be a number")

    for label in ("consumes", "emits"):
        section = manifest.get(label)
        if section is None:
            continue
        if not isinstance(section, dict):
            errors.append(f"'{label}' must be an object")
            continue
        errors.extend(_shape_errors(section, label))

    emits = manifest.get("emits")
    if isinstance(emits, dict):
        for key in ("adds", "report", "reportable"):
            value = emits.get(key)
            if value is not None and not _is_string_list(value):
                errors.append(f"'emits.{key}' must be a list of strings")
        report = emits.get("report") or []
        reportable = set(emits.get("reportable") or [])
        for column in report:
            if column not in reportable:
                errors.append(f"'emits.report' column {column!r} is not in 'emits.reportable'")
    return errors


def _shape_errors(section: dict[str, Any], label: str) -> list[str]:
    errors: list[str] = []
    shape = section.get("shape")
    if shape is None:
        errors.append(f"'{label}' requires a 'shape'")
    elif not isinstance(shape, str) and not (isinstance(shape, list) and shape):
        errors.append(f"'{label}' shape must be a string or a non-empty list")
    else:
        for value in _as_list(shape):
            if value not in SHAPES:
                errors.append(f"'{label}' shape {value!r} is not one of {sorted(SHAPES)}")
    if label == "consumes":
        columns = section.get("columns")
        if columns is not None and not _is_string_list(columns):
            errors.append("'consumes.columns' must be a list of strings")
    return errors


def _emitted_columns(manifest: dict[str, Any]) -> set[str]:
    emits = manifest.get("emits")
    adds = emits.get("adds") if isinstance(emits, dict) else None
    return {_BASE_COLUMN, *(str(column) for column in (adds or []))}


def _param_errors(sid: str, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    params = manifest.get("params")
    if not isinstance(params, dict):
        params = {}
    with_val = manifest.get("with")
    if with_val is None:
        return errors
    if not isinstance(with_val, dict):
        errors.append(f"{sid}: 'with' must be an object")
        return errors
    for name, value in with_val.items():
        spec = params.get(str(name))
        if spec is None:
            errors.append(f"unknown param {name!r} for {sid}")
            continue
        if not isinstance(spec, dict) or value is None:
            continue
        errors.extend(_check_param_value(sid, str(name), value, spec))
    return errors


def _check_param_value(sid: str, name: str, value: object, spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    ptype = str(spec.get("type", "str"))
    if not _type_ok(ptype, value):
        errors.append(f"{sid} {name}: expected {ptype}, got {type(value).__name__}")
        return errors
    if ptype == "decimal":
        dec = _as_decimal(value)
        low = _as_decimal(spec.get("min")) if "min" in spec else None
        high = _as_decimal(spec.get("max")) if "max" in spec else None
        if dec is not None and low is not None and dec < low:
            errors.append(f"{sid} {name}: {value} below min")
        if dec is not None and high is not None and dec > high:
            errors.append(f"{sid} {name}: {value} above max")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = spec.get("min")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(f"{sid} {name}: {value} below min")
        maximum = spec.get("max")
        if isinstance(maximum, (int, float)) and value > maximum:
            errors.append(f"{sid} {name}: {value} above max")
    choices = spec.get("choices")
    if choices is not None and value not in choices:
        errors.append(f"{sid} {name}: {value!r} not in choices {choices}")
    pattern = spec.get("pattern")
    if pattern and isinstance(value, str) and re.fullmatch(str(pattern), value) is None:
        errors.append(f"{sid} {name}: {value!r} does not match pattern {pattern!r}")
    return errors


def _as_decimal(value: object) -> Decimal | None:
    """Finite ``Decimal`` from a str or int (never float/bool), else ``None``."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    try:
        dec = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    return dec if dec.is_finite() else None


def _type_ok(ptype: str, value: object) -> bool:
    if ptype == "decimal":
        return _as_decimal(value) is not None
    if ptype in ("int", "window"):
        return isinstance(value, int) and not isinstance(value, bool)
    if ptype == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if ptype == "bool":
        return isinstance(value, bool)
    if ptype in ("str", "symbols"):
        return isinstance(value, str)
    if ptype == "date":
        return isinstance(value, str) and _DATE_RE.match(value) is not None
    if ptype == "enum":
        return isinstance(value, str)
    return True


def _report_errors(sid: str, manifest: dict[str, Any]) -> list[str]:
    emits = manifest.get("emits")
    if not isinstance(emits, dict):
        return []
    reportable = list(emits.get("reportable") or [])
    report = manifest.get("report")
    if report is None:
        return []
    if not _is_string_list(report):
        return [f"{sid}: 'report' must be a list of column names"]
    errors: list[str] = []
    for column in report:
        if column not in reportable:
            shown = ", ".join(reportable) or "nothing"
            errors.append(
                f"{sid} cannot report {column!r} (not in emits.reportable); may report: {shown}"
            )
    return errors


def _kind_errors(manifest: dict[str, Any], previous: dict[str, Any] | None) -> list[str]:
    if previous is None:
        return []
    kind = str(manifest.get("kind"))
    prev_kind = str(previous.get("kind"))
    if kind not in KINDS or prev_kind not in KINDS:
        return []
    if KIND_ORDER.index(kind) < KIND_ORDER.index(prev_kind):
        return [f"{manifest.get('id')} cannot follow {prev_kind!r}"]
    return []


def _shape_handoff_errors(manifest: dict[str, Any], previous: dict[str, Any] | None) -> list[str]:
    if previous is None:
        return []
    errors: list[str] = []
    consumes = manifest.get("consumes")
    prev_emits = previous.get("emits")
    if isinstance(consumes, dict) and isinstance(prev_emits, dict):
        own_shapes = _as_list(consumes.get("shape"))
        prev_shape = prev_emits.get("shape")
        if prev_shape is not None and own_shapes and str(prev_shape) not in own_shapes:
            message = (
                f"{manifest.get('id')} consumes shape {consumes.get('shape')!r} "
                f"but {previous.get('id')} emits {prev_shape!r}"
            )
            if str(previous.get("kind")) == "signal":
                message += "; insert a screen or filter step between them"
            errors.append(message)
        for column in consumes.get("columns") or []:
            if column not in _emitted_columns(previous):
                adds = prev_emits.get("adds") or []
                errors.append(
                    f"{manifest.get('id')} consumes column {column!r} but "
                    f"{previous.get('id')} does not emit it (emits adds {adds!r})"
                )
    return errors


def _first_step_errors(manifest: dict[str, Any]) -> list[str]:
    consumes = manifest.get("consumes")
    if not isinstance(consumes, dict):
        return []
    shapes = _as_list(consumes.get("shape"))
    if shapes and not (set(shapes) & {"universe", "none"}):
        return [
            f"{manifest.get('id')}: first step must consume 'universe' "
            f"(a screen or signal); it consumes {consumes.get('shape')!r}"
        ]
    return []


def validate_chain(manifests: list[dict[str, Any]]) -> list[str]:
    """Errors for a full chain of step manifests (empty when the chain is valid)."""
    errors: list[str] = []
    for index, manifest in enumerate(manifests):
        sid = str(manifest.get("id") or f"<step {index + 1}>")
        errors.extend(_param_errors(sid, manifest))
        errors.extend(_report_errors(sid, manifest))
        if index == 0:
            errors.extend(_first_step_errors(manifest))
        else:
            previous = manifests[index - 1]
            errors.extend(_kind_errors(manifest, previous))
            errors.extend(_shape_handoff_errors(manifest, previous))
    return errors


def main() -> int:
    """Validate manifest JSON files passed on the command line (single or chain)."""
    import json
    import sys

    for path in sys.argv[1:]:
        with open(path) as handle:
            data = json.load(handle)
        problems = schema_errors(data) if isinstance(data, dict) else validate_chain(data)
        for problem in problems:
            print(f"{path}: {problem}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
