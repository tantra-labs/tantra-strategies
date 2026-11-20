#!/usr/bin/env python3
"""Execute every strategy manifest deterministically (gap 0003).

For each ``manifests/strategies/*.toml`` manifest, load it, instantiate the strategy
with its declared parameter defaults, run it twice against deterministic daily
bars in a fresh :class:`SimulatedContext`, and verify both runs produce
identical order-event traces (research-live parity). Failures are reported as
``FAIL <path>: <error>`` lines and produce a non-zero exit code.

Run:  python tools/run_step.py [path ...]
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Make the strategy package importable when the tool runs from a source tree.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tantra_strategies.manifest.strategy import StrategyManifest  # noqa: E402
from tantra_strategies.sdk.bar import Bar  # noqa: E402
from tantra_strategies.sdk.context import SimulatedContext  # noqa: E402
from tantra_strategies.sdk.order import OrderEvent  # noqa: E402
from tantra_strategies.sdk.strategy import Strategy  # noqa: E402

MANIFEST_DIR = ROOT / "manifests" / "strategies"
DEFAULT_INSTRUMENT = "NSE:NIFTY50-INDEX"


def load_manifest(path: Path) -> StrategyManifest:
    """Load a strategy manifest from TOML."""
    return StrategyManifest.load_toml(path)


def instruments_for(manifest: StrategyManifest) -> list[str]:
    """Return the manifest's explicit target instruments.

    Falls back to ``DEFAULT_INSTRUMENT`` when the selector is rule-based.
    """
    return list(manifest.target_instruments.instruments) or [DEFAULT_INSTRUMENT]


def build_strategy(manifest: StrategyManifest) -> Strategy:
    """Instantiate the manifest's strategy with its declared defaults."""
    return manifest.instantiate()


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


def run_step(manifest: StrategyManifest) -> tuple[tuple[object, ...], tuple[object, ...]]:
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
    """Run every strategy manifest, or only the paths given on the command line."""
    raw_paths = [Path(arg) for arg in argv] if argv else sorted(MANIFEST_DIR.rglob("*.toml"))
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
