#!/usr/bin/env python3
"""Execute every catalog step deterministically (gap 0003).

For each ``catalog/**/step.toml`` manifest, load it, instantiate the strategy
with its declared parameter defaults, run it twice against deterministic daily
bars in a fresh :class:`SimulatedContext`, and verify both runs produce
identical order-event traces (research-live parity). Failures are reported as
``FAIL <path>: <error>`` lines and produce a non-zero exit code.

Run:  python tools/run_step.py [path ...]
"""

from __future__ import annotations

import importlib
import sys
import tomllib
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Make the strategy package importable when the tool runs from a source tree.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tantra_strategies.sdk.bar import Bar  # noqa: E402
from tantra_strategies.sdk.context import SimulatedContext  # noqa: E402
from tantra_strategies.sdk.order import OrderEvent  # noqa: E402
from tantra_strategies.sdk.strategy import Strategy  # noqa: E402

CATALOG_DIR = ROOT / "catalog"
DEFAULT_INSTRUMENT = "NSE:NIFTY50-INDEX"


def load_manifest(path: Path) -> dict[str, object]:
    """Load a catalog step manifest from TOML text."""
    return tomllib.loads(path.read_text())


def instruments_for(manifest: dict[str, object]) -> list[str]:
    """Collect the instruments a step trades from its param defaults.

    Handles ``instrument``, comma-separated ``instruments``, and the
    ``cash_instrument`` / ``futures_instrument`` pair (Arbitrage). Dedupes
    preserving order and falls back to ``DEFAULT_INSTRUMENT`` when empty.
    """
    params = manifest.get("params")
    if not isinstance(params, dict):
        return [DEFAULT_INSTRUMENT]
    instruments: list[str] = []
    for key in ("instrument", "instruments", "cash_instrument", "futures_instrument"):
        spec = params.get(key)
        if not isinstance(spec, dict):
            continue
        default = spec.get("default")
        if isinstance(default, str):
            for piece in default.split(","):
                cleaned = piece.strip()
                if cleaned and cleaned not in instruments:
                    instruments.append(cleaned)
    return instruments or [DEFAULT_INSTRUMENT]


def build_strategy(manifest: dict[str, object]) -> Strategy:
    """Instantiate the step's ``module:Class`` with its declared defaults."""
    strategy_ref = manifest.get("strategy")
    if not isinstance(strategy_ref, str):
        raise ValueError(f"step manifest has no 'strategy' string: {manifest}")
    module_name, _, class_name = strategy_ref.partition(":")
    strategy_class: type[Strategy] = getattr(importlib.import_module(module_name), class_name)
    params = manifest.get("params")
    if not isinstance(params, dict):
        raise ValueError(f"step manifest has no 'params' dict: {manifest}")
    kwargs: dict[str, object] = {}
    for name, spec in params.items():
        if not isinstance(spec, dict):
            raise ValueError(f"step param {name!r} is not a spec dict: {spec}")
        kwargs[name] = spec["default"]
    return strategy_class(**kwargs)  # type: ignore[arg-type]


def deterministic_bars(instrument: str) -> list[Bar]:
    """45 deterministic daily bars: 30 rising then 15 falling."""
    closes = [Decimal(100) + Decimal(i) for i in range(30)] + [
        Decimal(130) - Decimal(i) for i in range(15)
    ]
    return [
        Bar(
            instrument=instrument,
            ts=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=100_000,
            interval="1d",
        )
        for i, close in enumerate(closes)
    ]


def fingerprint(events: Sequence[OrderEvent]) -> tuple[object, ...]:
    """Collapse an event trace into a comparable fingerprint tuple."""
    return tuple(
        (event.order_id, event.status, event.price, event.filled_quantity) for event in events
    )


def run_step(manifest: dict[str, object]) -> tuple[tuple[object, ...], tuple[object, ...]]:
    """Run a step twice and return both event-trace fingerprints.

    Uses the bar path only (never ``run_ticks``). Any exception propagates;
    ``main`` turns it into a FAIL line.
    """
    traces: list[tuple[object, ...]] = []
    for _ in range(2):
        strategy = build_strategy(manifest)
        context = SimulatedContext()
        bars = [
            bar
            for instrument in instruments_for(manifest)
            for bar in deterministic_bars(instrument)
        ]
        context.run(strategy, bars)
        traces.append(fingerprint(context.events))
    return traces[0], traces[1]


def main(argv: list[str]) -> int:
    """Run every catalog step, or only the paths given on the command line."""
    raw_paths = [Path(arg) for arg in argv] if argv else sorted(CATALOG_DIR.rglob("*.toml"))
    paths = [path.resolve() for path in raw_paths]
    failures = 0
    for path in paths:
        try:
            first, second = run_step(load_manifest(path))
            if first != second:
                raise AssertionError("two runs produced different event traces")
        except Exception as error:  # gap 0003: a step failure is reported, not fatal
            failures += 1
            print(f"FAIL {path.relative_to(ROOT)}: {error}")
        else:
            print(f"ok   {path.relative_to(ROOT)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
