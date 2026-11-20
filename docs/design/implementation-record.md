# `tantra-strategies` — Implementation Record

Dismantled from the former `docs/roadmap/` (`roadmap.md` +
`migration-verification.md`). Completed milestones are recorded here; remaining
future work moved to [`docs/gaps/`](../gaps/README.md) and
[`docs/plans/`](../plans/README.md).

## Migration: `honba-strategies` → `tantra-strategies` (Tier 6C)

| Milestone | Status | Commit |
|-----------|--------|--------|
| `pyproject.toml` fixed (invalid `rust_decimal` removed) | Complete | `af20843` |
| Strategy SDK implemented (`sdk/`) | Complete | `af20843` |
| Strategy families ported (`strategies/`) | Complete | `af20843` |
| Declarative `catalog/` step manifests + schema | Complete | `af20843` |
| Manifest tooling (`tools/validate_catalog.py`) | Complete | `af20843` |
| Legacy `catalog/` migrated into `manifests/strategies/` (2026-11-20); `validate_catalog.py` retired | Complete | - |
| Tests in `tests/` (parallel to package, no inline tests) | Complete | `af20843` |

The source `honba-strategies` tree was unavailable, so the tier was implemented
fresh from the sub-guide contracts — see
[`code-migration-map.md`](code-migration-map.md) for the layout mapping.

## Subsequent landings

| Landing | Commit |
|---------|--------|
| Plan 0001 Layer 3: `StrategyManifest` / `BasketManifest` / promotion workflow (`manifest/`), POC sidecars (`manifests/strategies/`, `manifests/baskets/`), `schema/strategy-manifest.schema.json`, `schema/basket-manifest.schema.json`, `tools/validate_manifests.py`, 42 tests in `tests/manifests/` | `207a70c` |
| Docs: code reference docs (`code-sdk.md`, `code-strategies.md`, `code-manifest.md`, `code-migration-map.md`) | `a5076c2` |
| Docs: plans index cleanup (plan 0001 → Implemented) | `a838b16` |
| Docs: `docs/roadmap/` dismantled into `docs/design/` + `docs/gaps/` + `docs/plans/` | this change |
| T8 track (gaps 0001–0005): `Tick` model + `Strategy.run_ticks` / `SimulatedContext.run_ticks` tick dispatch; feed/gateway-backed `LiveContext` (`sdk/live.py`); catalog step executor (`tools/run_step.py`); basket run loop (`manifest/basket_run.py` + `optimize_allocations`); 31 new tests (164 total) | this change |

## Verification (recorded green gate, 2026-11-06, plan 0001)

```bash
pytest -q              # 119 tests, all passing
ruff check .           # clean
ruff format --check .  # clean
mypy tantra_strategies  # clean
python tools/validate_manifests.py  # 2 strategy + 1 basket manifest ok
```

- Test distribution (computed from `tests/` incl. parametrization): SDK 18,
  strategies 26, manifests 42, catalog 32, `test_init` 1 — total **119**
  (matches the Layer 3 handoff gate).
- Zero inline tests in `tantra_strategies/` (tests live in `tests/` only).
- Zero-floats gate: all prices/quantities/weights use `decimal.Decimal`
  (string literals; `Decimal(<float>)` is rejected by ruff RUF032).

## Migration status

Migration is **complete**. No outstanding migration work remains; the open items
below are future features, not unfinished port work.

## Open future work

The T8 track (2026-11-14) closed gaps 0001–0005: tick dispatch (`on_tick` +
`Strategy.run_ticks` / `SimulatedContext.run_ticks`), the feed/gateway-backed
`LiveContext` parity seam, the in-repo catalog step executor
(`tools/run_step.py`), the `BasketManifest` run loop (`basket_run.run_basket`),
and the `RiskBudget` allocation optimizer (`optimize_allocations`). Remaining
open items now live in [`docs/gaps/`](../gaps/README.md) and
[`docs/plans/`](../plans/README.md): the EE+ SDK stop-protection surface
(`0006`) and the EE+ strategy plan (`0001`).
