"""Every recipe entry points at a runnable catalog step registered in registry.json."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from tantra_library import default_registry
from tantra_library.model import EntryKind

ROOT = Path(__file__).resolve().parent.parent.parent


def _registered_step_ids() -> set[str]:
    data = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))
    ids: set[str] = set()
    for entry in data["strategies"]:
        manifest = tomllib.loads((ROOT / entry["path"] / "step.toml").read_text(encoding="utf-8"))
        ids.add(manifest["id"])
    return ids


def test_every_recipe_has_a_registered_runnable_step() -> None:
    registry = default_registry()
    recipes = registry.entries(EntryKind.RECIPE)
    assert recipes
    step_ids = _registered_step_ids()
    for recipe in recipes:
        assert recipe.runnable_step in step_ids, recipe.id


def test_runnable_step_is_serialized_and_described() -> None:
    registry = default_registry()
    entry = registry.get("recipe.pr-trend-pullback")
    assert entry.to_dict()["runnable_step"] == "signal.pr_trend_pullback"
    assert "Runnable step: `signal.pr_trend_pullback`" in registry.describe_markdown(entry.id)
