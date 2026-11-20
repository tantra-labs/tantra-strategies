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
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


_RUNNABLE = [
    "equal_weight",
    "alpha30_factor",
    "elephant_edge_v3",
    "pr_trend_pullback",
    "pr_vidya_breakout",
]


def _registry() -> dict[str, dict[str, str]]:
    data = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))
    return {entry["name"]: entry for entry in data["strategies"]}


@pytest.mark.parametrize("name", _RUNNABLE)
def test_registry_entry_points_at_a_runnable_directory(name: str) -> None:
    directory = ROOT / _registry()[name]["path"]
    assert (directory / "strategy.py").is_file()
    assert (directory / "config.toml").is_file()
    assert (directory / "step.toml").is_file()


@pytest.mark.parametrize("name", _RUNNABLE)
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


def _validate_chain_module():
    spec = importlib.util.spec_from_file_location(
        "_validate_chain_dec", ROOT / "tools" / "validate_chain.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_elephant_edge_v3_sl_buffer_is_a_strict_decimal_param() -> None:
    vc = _validate_chain_module()
    directory = ROOT / _registry()["elephant_edge_v3"]["path"]
    manifest = tomllib.loads((directory / "step.toml").read_text(encoding="utf-8"))
    spec = manifest["params"]["sl_buffer_atr"]
    assert spec["type"] == "decimal"
    assert vc.schema_errors(manifest) == []
    assert vc._check_param_value("s", "sl_buffer_atr", "0.5", spec) == []
    assert vc._check_param_value("s", "sl_buffer_atr", 1, spec) == []


def test_decimal_param_rejects_float_and_out_of_range() -> None:
    vc = _validate_chain_module()
    spec = {"type": "decimal", "min": "0", "max": "1", "default": "0.25"}
    assert vc._check_param_value("s", "p", 0.5, spec)  # float rejected
    assert vc._check_param_value("s", "p", "nan", spec)  # non-finite rejected
    assert any("above max" in e for e in vc._check_param_value("s", "p", "1.5", spec))
    assert any("below min" in e for e in vc._check_param_value("s", "p", "-0.1", spec))
    bad = {"id": "signal.x", "kind": "signal", "params": {"p": {**spec, "min": 0.1}}}
    assert any("min must be a decimal" in e for e in vc.schema_errors(bad))


def _pr_wheel_run(name: str, params: dict[str, object], closes: list[float]):
    from tantra.bar import Bar as WheelBar
    from tantra.context import LedgerContext
    from tantra.instrument import InstrumentId
    from tantra.money import Currency, Money

    loaded = _load_named(name)
    strategy = loaded.instantiate()
    for key, value in params.items():
        setattr(strategy, key, value)
    ctx = LedgerContext(cash=Money.from_major(1_000_000, Currency.INR))
    strategy.bind(ctx)
    strategy.on_start()
    iid = InstrumentId("NIFTY50-INDEX", "NSE")
    start = dt.datetime(2026, 5, 4, 9, 15, tzinfo=dt.UTC)
    prev = closes[0]
    for i, close in enumerate(closes):
        ts = start + dt.timedelta(minutes=i)
        hi = max(prev, close) + 0.5
        lo = min(prev, close) - 0.5
        strategy.on_bar(WheelBar(iid, ts, prev, hi, lo, close, 100_000 + (i % 7) * 10_000))
        prev = close
    return strategy, ctx


def _wavy_series(n: int = 400) -> list[float]:
    import math

    return [round(100 + i * 0.05 + 6 * math.sin(i / 7.0), 2) for i in range(n)]


@pytest.mark.parametrize(
    ("name", "scene_id", "params"),
    [
        ("pr_trend_pullback", "recipe.pr-trend-pullback", {"length": 20, "factor": "2"}),
        (
            "pr_vidya_breakout",
            "recipe.pr-vidya-breakout",
            {"length": 20, "factor": "2", "vidya_atr_length": 20, "delta_threshold": "0"},
        ),
    ],
)
def test_pr_steps_run_on_the_wheel_ledger(
    name: str, scene_id: str, params: dict[str, object]
) -> None:
    strategy, ctx = _pr_wheel_run(name, params, _wavy_series())
    assert getattr(strategy, "name", None) == name
    assert strategy.emit_scene().strategy_id == scene_id
    intents = ctx.drain_intents()
    if name == "pr_vidya_breakout":
        # deterministic wavy series triggers at least one breakout entry
        assert intents
        assert all(intent.quantity > 0 for intent in intents)
    # pr_trend_pullback: no entry on this series (its 0.5-wick bars can never print a
    # strictly-lower reversal low); the full entry path is pinned by the engine test below.
    strategy.on_stop()


def _pullback_bars() -> list[object]:
    """One NSE session of 1m bars: an up-trend with sine pullbacks.

    The first up bar after a down leg carries a 2-point hammer wick, so the
    ``ReversalBars`` low prints strictly below the prior lows inside the PR S1 zone.
    """
    import math

    from tantra.bar import Bar as WheelBar
    from tantra.instrument import InstrumentId

    iid = InstrumentId("NIFTY50-INDEX", "NSE")
    open_ns = int(dt.datetime(2026, 5, 4, 3, 45, tzinfo=dt.UTC).timestamp()) * 1_000_000_000
    half, hammer = Decimal("0.5"), Decimal(2)
    closes = [
        Decimal(100) + Decimal("0.4") * i + Decimal(str(round(4 * math.sin(i / 9), 2)))
        for i in range(60)
    ]
    bars: list[object] = []
    prev, prev_up = closes[0], True
    for i, close in enumerate(closes):
        up = close > prev
        low = min(prev, close) - half - (hammer if up and not prev_up else 0)
        ts = open_ns + i * 60_000_000_000
        bars.append(WheelBar(iid, ts, prev, max(prev, close) + half, low, close, 100_000))
        prev, prev_up = close, up
    return bars


def test_pr_trend_pullback_enters_and_exits_through_the_wheel_engine() -> None:
    """End-to-end: PR regime + S1 touch + reversal bar -> filled long -> bracket target exit."""
    pytest.importorskip("tantra_examples.backtest")
    from tantra_examples.backtest import run_portfolio_backtest

    strategy = _load_named("pr_trend_pullback").instantiate()
    strategy.length, strategy.factor = 20, "1"
    day = dt.date(2026, 5, 4)
    run = run_portfolio_backtest(
        strategy, _pullback_bars(), test_start=day, test_end=day, capital_minor=100_000_000
    )

    assert run.rejections == 0
    assert [(f.side, f.quantity) for f in run.fills] == [
        ("buy", Decimal(1)),
        ("sell", Decimal(1)),
    ]
    entry, exit_ = run.fills
    assert entry.price == Decimal("111.28")  # next-open fill after the reversal trigger
    assert exit_.price > entry.price  # bracket target leg, not the stop
    assert run.final_positions == {}

    scene = strategy.emit_scene().to_dict()
    assert [(s["kind"], s["index"]) for s in scene["signals"]] == [
        ("retest", 35),
        ("target_hit", 36),
    ]
    assert {stop["kind"] for stop in scene["stops"]} == {"initial", "target"}
    assert scene["hints"][0]["title"] == "PR pullback long"
