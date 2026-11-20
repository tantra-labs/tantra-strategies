"""schema/step.schema.json describes every runnable catalog_steps/**/step.toml."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((ROOT / "schema" / "step.schema.json").read_text(encoding="utf-8"))
STEPS = sorted((ROOT / "catalog_steps").rglob("step.toml"))


def test_there_are_step_manifests() -> None:
    assert len(STEPS) >= 5


@pytest.mark.parametrize("path", STEPS, ids=lambda p: str(p.relative_to(ROOT)))
def test_step_manifest_conforms_to_step_schema(path: Path) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    manifest = tomllib.loads(path.read_text(encoding="utf-8"))
    errors = sorted(e.message for e in jsonschema.Draft7Validator(SCHEMA).iter_errors(manifest))
    assert errors == []


def test_step_schema_rejects_unknown_param_type() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    manifest = tomllib.loads(STEPS[0].read_text(encoding="utf-8"))
    manifest["params"] = {"x": {"type": "double", "default": "1"}}
    assert list(jsonschema.Draft7Validator(SCHEMA).iter_errors(manifest))
