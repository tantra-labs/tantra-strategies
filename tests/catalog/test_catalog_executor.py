"""In-repo catalog executor (gap 0003): every step runs deterministically."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tomllib
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
CATALOG_DIR = ROOT / "catalog"

STEPS = sorted(CATALOG_DIR.rglob("*.toml"))


def load_run_step() -> types.ModuleType:
    """Load ``tools/run_step.py`` by path (tools/ has no ``__init__.py``)."""
    spec = importlib.util.spec_from_file_location("run_step", ROOT / "tools" / "run_step.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("path", STEPS, ids=lambda p: p.relative_to(ROOT))
def test_step_runs_deterministically(path: Path) -> None:
    """A catalog step must run twice with identical event traces and no crash."""
    run_step = load_run_step()
    manifest = tomllib.loads(path.read_text())
    first, second = run_step.run_step(manifest)
    assert first == second
    assert len(first) == len(second)


def test_run_step_cli_smoke() -> None:
    """The executor CLI runs every catalog step and reports no failures."""
    result = subprocess.run(
        [sys.executable, "tools/run_step.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "FAIL" not in result.stdout


def test_run_step_cli_accepts_explicit_paths() -> None:
    """Explicit relative paths are accepted and reported relative to ROOT."""
    result = subprocess.run(
        [sys.executable, "tools/run_step.py", "catalog/trend/turtle_breakout.toml"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
