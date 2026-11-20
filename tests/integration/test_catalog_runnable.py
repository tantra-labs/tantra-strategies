"""Gap 0007 + Track T21.2 closure: catalog steps are runnable, not just declarative.

Verifies the harness-loader layout the ``tantra-examples`` runner expects:

* ``registry.json`` registers ``equal_weight``, ``alpha30_factor``, and
  ``elephant_edge_v3`` to directories that ship ``strategy.py`` +
  ``config.toml`` + ``step.toml``.
* each ``step.toml`` still passes the chain validator's ``schema_errors``.
* ``load_named(...)`` resolves each strategy (when the ``tantra_examples``
  harness is importable) and ``instantiate()`` builds a ``tantra.base.Strategy``
  that submits order intents through a wheel ``LedgerContext``.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


def _registry() -> dict[str, dict[str, str]]:
    data = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))
    return {entry["name"]: entry for entry in data["strategies"]}


@pytest.mark.parametrize("name", ["equal_weight", "alpha30_factor", "elephant_edge_v3"])
def test_registry_entry_points_at_a_runnable_directory(name: str) -> None:
    directory = ROOT / _registry()[name]["path"]
    assert (directory / "strategy.py").is_file()
    assert (directory / "config.toml").is_file()
    assert (directory / "step.toml").is_file()


@pytest.mark.parametrize("name", ["equal_weight", "alpha30_factor", "elephant_edge_v3"])
def test_step_manifest_is_schema_valid(name: str) -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(
        "_validate_chain", ROOT / "tools" / "validate_chain.py"
    )
    assert spec is not None and spec.loader is not None
    validate_chain = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validate_chain)

    directory = ROOT / _registry()[name]["path"]
    manifest = tomllib.loads((directory / "step.toml").read_text(encoding="utf-8"))
    assert validate_chain.schema_errors(manifest) == []


def test_alpha30_step_keeps_the_declarative_orders_contract() -> None:
    directory = ROOT / _registry()["alpha30_factor"]["path"]
    manifest = tomllib.loads((directory / "step.toml").read_text(encoding="utf-8"))
    assert manifest["id"] == "signal.alpha30_factor"
    assert manifest["emits"]["shape"] == "orders"
    assert manifest["params"] == {}


def _load_named(name: str):
    """``load_named`` through the tantra-examples harness (skips without it)."""
    pytest.importorskip("tantra")
    pytest.importorskip("tantra_examples")
    from tantra_examples.catalog import load_named

    return load_named(name, strategies_dir=ROOT)


@pytest.mark.parametrize("name", ["equal_weight", "alpha30_factor"])
def test_load_named_resolves_and_instantiates(name: str) -> None:
    loaded = _load_named(name)
    assert loaded.name == name
    strategy = loaded.instantiate()
    assert getattr(strategy, "name", None) == name
    assert loaded.config.params.get("universe") == "nifty200_alpha_30"


def test_load_named_resolves_elephant_edge_v3() -> None:
    loaded = _load_named("elephant_edge_v3")
    assert loaded.name == "elephant_edge_v3"
    strategy = loaded.instantiate()
    assert getattr(strategy, "name", None) == "elephant_edge_v3"
    assert loaded.config.params.get("sl_mode") == "outer_atr_buffer"


def _alpha30_universe() -> list[str]:
    from tantra.markets.india.universes import resolve_universe

    return [iid.symbol for iid in resolve_universe("nifty200_alpha_30", exchange="NSE")]


def _feed_sessions(strategy: object, symbols: list[str], sessions: int) -> None:
    """Feed one deterministic daily bar per member per session through ``on_bar``."""
    from tantra.bar import Bar
    from tantra.instrument import InstrumentId
    from tantra_examples.synthetic import session_ts

    start = dt.date(2026, 5, 4)
    for session in range(sessions):
        day = start + dt.timedelta(days=session)
        for i, symbol in enumerate(symbols):
            price = 100.0 + session + i
            strategy.on_bar(  # type: ignore[attr-defined]
                Bar(
                    InstrumentId(symbol, "NSE"),
                    session_ts(day),
                    price,
                    price,
                    price,
                    price,
                    1000,
                )
            )


def test_equal_weight_submits_intents_through_the_wheel_ledger() -> None:
    from tantra.context import LedgerContext
    from tantra.money import Currency, Money

    loaded = _load_named("equal_weight")
    strategy = loaded.instantiate()
    ctx = LedgerContext(cash=Money.from_major(1_000_000, Currency.INR))
    strategy.bind(ctx)
    strategy.on_start()

    _feed_sessions(strategy, _alpha30_universe(), 2)
    intents = ctx.drain_intents()
    assert intents, "equal_weight should submit buy intents once the basket is priced"
    assert all(intent.quantity > 0 for intent in intents)


def test_alpha30_factor_submits_intents_once_factor_history_is_ready() -> None:
    from tantra.context import LedgerContext
    from tantra.money import Currency, Money

    loaded = _load_named("alpha30_factor")
    strategy = loaded.instantiate()
    ctx = LedgerContext(cash=Money.from_major(1_000_000, Currency.INR))
    strategy.bind(ctx)
    strategy.on_start()

    _feed_sessions(strategy, _alpha30_universe(), 40)
    intents = ctx.drain_intents()
    assert intents, "alpha30_factor should submit orders once ROC history is ready"
    assert all(intent.quantity > 0 for intent in intents)


def test_elephant_edge_v3_submits_intents_and_emits_scene_via_wheel_ledger() -> None:
    from tantra.bar import Bar as WheelBar
    from tantra.context import LedgerContext
    from tantra.instrument import InstrumentId
    from tantra.money import Currency, Money

    loaded = _load_named("elephant_edge_v3")
    strategy = loaded.instantiate()
    ctx = LedgerContext(cash=Money.from_major(1_000_000, Currency.INR))
    strategy.bind(ctx)
    strategy.on_start()

    iid = InstrumentId("NIFTY50-INDEX", "NSE")
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    # 2 prior daily sessions establish empirical S1/S2/R1/R2 bands, then day 3 intraday entry
    for day in (11, 12):
        for minute_idx in range(25):
            ts = dt.datetime(2026, 5, day, 9, 15, tzinfo=ist) + dt.timedelta(minutes=minute_idx)
            lo = "94.0" if minute_idx == 10 else "99.0"
            hi = "106.0" if minute_idx == 12 else "101.0"
            strategy.on_bar(WheelBar(iid, ts, 100.0, float(hi), float(lo), 100.0, 100_000))

    # Day 13: open 100 -> S1 at 100 - 6 = 94, R1 at 100 + 6 = 106; feed warmup then hammer at S1=94
    for minute_idx in range(15):
        ts = dt.datetime(2026, 5, 13, 9, 15, tzinfo=ist) + dt.timedelta(minutes=minute_idx)
        strategy.on_bar(WheelBar(iid, ts, 100.0, 101.0, 99.0, 100.0, 100_000))

    # Hammer reversal at S1 (low 92.5, close 94.2, high 94.4, volume spike)
    t_sig = dt.datetime(2026, 5, 13, 9, 32, tzinfo=ist)
    strategy.on_bar(WheelBar(iid, t_sig, 94.1, 94.4, 92.5, 94.2, 400_000))

    intents = ctx.drain_intents()
    assert intents, "elephant_edge_v3 should submit entry order intents to wheel LedgerContext"
    assert intents[0].quantity > 0

    scene = strategy.emit_scene()
    assert scene.strategy_id == "elephant_edge_v3"
    assert scene.signals
    assert scene.bands
    assert scene.stops
    assert scene.hints
    assert scene.hedges
