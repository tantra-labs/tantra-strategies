# Tantra Strategies (`tantra-strategies`)

**Bounded Context**: Production Strategy SDK & Declarative Step Catalog (Tier 6C)

`tantra-strategies` is the canonical quantitative strategy repository for the
Tantra Labs ecosystem. It follows a Jesse-style Python strategy authoring
model (`on_start` / `on_bar` / `on_tick` / `on_order_event` / `on_stop`) with
declarative `Parameter(default=..., min=..., max=..., step=...)` hyperparameters
and strict research-live parity — the exact same strategy class runs against
historical bars and live WebSocket feeds.

## Included Strategy Families

| Family | Module | Manifest |
| :--- | :--- | :--- |
| Quoting | `tantra_strategies.strategies.quoting` | `manifests/strategies/` |
| Cash–Futures Arbitrage | `tantra_strategies.strategies.arbitrage` | `manifests/strategies/cash_futures_arbitrage.toml` |
| Market Making | `tantra_strategies.strategies.market_making` | `manifests/strategies/market_making.toml` |
| Mean Reversion (Bollinger) | `tantra_strategies.strategies.mean_reversion` | `manifests/strategies/bollinger_mean_reversion.toml` |
| Turtle Breakout | `tantra_strategies.strategies.turtle` | `manifests/strategies/turtle_breakout.toml` |
| Risk Parity | `tantra_strategies.strategies.risk_parity` | `manifests/strategies/risk_parity.toml` |
| TWAP / VWAP Slicers | `tantra_strategies.strategies.execution` | `manifests/strategies/{twap_slicer,vwap}.toml` |

## Layout (4-Zone Clean Package)

```
tantra-strategies/
├── tantra_strategies/   # Zone 1: strategy SDK + strategies + manifest models
├── catalog_steps/        # Zone 2: runnable pipeline steps (+ registry.json)
├── manifests/            # Zone 2: versioned strategy & basket manifests (plan 0001)
│   ├── strategies/       #   StrategyManifest sidecars (turtle_breakout, twap_slicer, ...)
│   └── baskets/          #   BasketManifest groupings
├── tests/                # Zone 3: unit / parity / catalog schema validation
├── schema/               # Zone 4: step + strategy/basket manifest JSON schemas
├── tools/                # Zone 4: manifest linters
└── docs/                 # Zone 4: architecture & migration guides
```

## Versioned Strategy Manifests & Baskets

Every strategy can carry a versioned, promotable manifest (plan 0001, Layer 3):
`name`, semver `version`, `module:Class` reference, parameter defaults, target
instruments, and a capital allocation (absolute `Money` amount or weight). A
`BasketManifest` groups several strategy versions under one combined capital and
risk budget. Promotion follows `draft → backtested → paper → live`, each step
requiring a justifying evidence reference.

```python
from tantra_strategies import BasketManifest, PromotionStatus, StrategyManifest

turtle = StrategyManifest.load_toml("manifests/strategies/turtle_breakout.toml")
turtle.promote(PromotionStatus.BACKTESTED, "backtest:run/2026-01-05/bt-123")

basket = BasketManifest.load_toml("manifests/baskets/turtle_twap_basket.toml")
for member in basket.member_strategies:  # weights are exact Decimal fractions
    print(member.name, member.weight)
```

Validate every manifest sidecar with:

```bash
python tools/validate_manifests.py   # schema + model + strategy class + basket refs
```

## Quick Start

```python
from tantra_strategies import TurtleBreakout
from tantra_strategies.sdk import SimulatedContext

strategy = TurtleBreakout(entry_period=20, exit_period=10)
context = SimulatedContext("NSE:NIFTY50-INDEX", seed=42)
strategy.run(context)
```

## Development

```bash
make test      # pytest -q
make lint      # ruff check .
make check     # lint + format-check + type-check + tests
```

## Verification Gate

```bash
pytest -q
ruff check .
```
