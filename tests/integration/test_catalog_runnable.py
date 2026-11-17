"""Gap 0007 closure: catalog steps are runnable, not just declarative.

Verifies the harness-loader layout the ``tantra-examples`` runner expects:

* ``registry.json`` registers ``equal_weight`` and ``alpha30_factor`` to
  directories that ship ``strategy.py`` + ``config.toml`` + ``step.toml``.
* each ``step.toml`` still passes the chain validator's ``schema_errors``.
* ``load_named(...)`` resolves each strategy (when the ``tantra_examples``
  harness is importable) and ``instantiate()`` builds a ``tantra.base.Strategy``
  that submits order intents through a wheel ``LedgerContext``.

The end-to-end backtest proof lives in tantra-examples
``tests/integration/test_07_alpha30_backtest.py`` (un-skipped by this catalog).
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


@pytest.mark.parametrize("name", ["equal_weight", "alpha30_factor"])
def test_registry_entry_points_at_a_runnable_directory(name: str) -> None:
    directory = ROOT / _registry()[name]["path"]
    assert (directory / "strategy.py").is_file()
    assert (directory / "config.toml").is_file()
    assert (directory / "step.toml").is_file()


@pytest.mark.parametrize("name", ["equal_weight", "alpha30_factor"])
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
    # Config params survived instantiation and drive the declarative parameters.
    assert loaded.config.params.get("universe") == "nifty200_alpha_30"


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

    # One full session prices all-but-one member -> the first rebalance fires.
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

    # lookback=30 needs 31 closes per member; 40 sessions guarantee a rebalance.
    _feed_sessions(strategy, _alpha30_universe(), 40)
    intents = ctx.drain_intents()
    assert intents, "alpha30_factor should submit orders once ROC history is ready"
    assert all(intent.quantity > 0 for intent in intents)
