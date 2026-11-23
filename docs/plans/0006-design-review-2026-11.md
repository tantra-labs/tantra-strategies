# 0006 — Tantra-strategies design review (2026-11): live-context parity, idempotent orders & packaged library contracts

**Status**: Proposed (2026-11-23)
**Scope**: `tantra-strategies` · **Umbrella**: root `docs/plans/0021-workspace-design-review-2026-11.md`

## 0. Executive Summary & Objective

The strategy SDK and the `tantra_library` concept/indicator catalog are sound as research tooling, but the live path diverges from simulation: the wheel bridge runs strategies on a private `SimulatedContext`, `LiveContext` has no fill events, cancel or resync, orders carry no idempotency key, and parameters/prices are weakly validated. The library has a hidden SDK<->library import cycle, no machine-readable provenance, and the wheel omits its manifests and catalog.

Binding decisions (user, 2026-11-20): the indicator, concept and strategy-research library lives in THIS repo (Python `tantra_library`); Rust ports such as `tantra-market-indicators` are kept in sync through golden parity vectors (root gap 0016), not by moving the library. The project is non-commercial, so non-commercial third-party licences (for example LuxAlgo CC BY-NC-SA ideas) are acceptable with attribution; gap 0014 is about provenance and consistent labelling only.

Non-goals: Parameter unification onto the wheel and `l2_sim` file splitting (root plan 0019 P4.5, P3.5); the shared risk gate itself (root gap 0013).

## 1. Context & Gaps Covered

| Gap | Title | Kind | Severity |
|---|---|---|---|
| [0009](../gaps/0009-live-context-parity.md) | Wheel bridge and LiveContext break research/live parity | design-flaw | high |
| [0010](../gaps/0010-order-request-idempotency-key.md) | `OrderRequest` has no client order id | design-flaw | high |
| [0011](../gaps/0011-sizing-and-helper-duplication.md) | Duplicated sizing, percentile and IST helpers | duplication | medium |
| [0012](../gaps/0012-typed-validated-parameters.md) | Untyped/unvalidated `Parameter`, float laundering | design-flaw | medium |
| [0013](../gaps/0013-sdk-library-import-cycle.md) | `sdk` <-> `tantra_library` import cycle | refactor | medium |
| [0014](../gaps/0014-library-provenance-and-licensing.md) | Library provenance and licence labelling | design-flaw | medium |
| [0015](../gaps/0015-promotion-evidence-digest.md) | Promotion evidence not bound to code/params/data | design-flaw | medium |
| [0016](../gaps/0016-package-data-and-py-typed.md) | Manifests/catalog not packaged; no `py.typed` | deployment | medium |
| [0017](../gaps/0017-dependency-pins-and-wheel-contract.md) | Dependency pins and wheel contract | deployment | medium |
| [0018](../gaps/0018-simulated-context-fill-model.md) | `SimulatedContext` fill model (no tick/fees/slippage) | design-flaw | medium |

Plan-only items (no standalone gap doc):

- R1 — Library MCP server hardening — `tantra_library/mcp/server.py:~188-206` is a blocking single-reader stdio loop with no cancellation, no per-call CPU budget and an unvalidated echoed protocol version (`:~178`); the runtime client's 30 s timeout (`tantra-runtime-api-rest/src/library_client.rs:80`) just restarts the child, so one slow study stalls all callers.
- R2 — Manifest strategy loading — `tantra_strategies/manifest/strategy.py:93,102-104` imports a manifest-supplied dotted path guarded only by a prefix regex, with no `issubclass(cls, Strategy)` check before `instantiate()`.
- R3 — Registry/catalog drift — `tantra_library/catalog.py` (1,068 lines) builds entries in code, `default_registry` (`:1067`) rebuilds on every call, and no golden registry JSON pins the wire contract consumed by `tantra-runtime` `library_routes.rs` and `tantra-ui-charts`.

## 2. Component Specifications & Phases

### Phase A — Quick, low-risk fixes
1. Gap 0010: add deterministic `client_order_id` and the `LiveContext` duplicate guard.
2. Gap 0012: typed `Parameter`, unknown-override rejection, strict float rejection in `Bar`/`OrderRequest`.
3. Gap 0011: shared `sdk/sizing.py`, `sdk/clock.py` (`IST`), single percentile helper; golden vector vs `tantra-ffi` sizing.
4. R2: resolve manifest strategies through `registry.json` / entry points plus an `issubclass` check; raise a typed `ManifestError`.
5. R3: commit `tests/golden/library_registry.json` (`Registry.to_dict`), diff in test, check `registry.json` strategies against `recipe.*` ids by id, memoise `default_registry()`.
6. Gap 0014: provenance fields, `NOTICE`/`LICENSE`, validation test, MCP `describe` surface.

**Gate**: `ruff check .`, `ruff format --check .`, `mypy --strict`, `pytest -q tests/`.

### Phase B — Structural refactors
1. Gap 0013: break the import cycle, re-export legacy SDK indicator names, add the import-graph test; extend golden vectors to RSI/EMA/SMA/Bollinger.
2. Gap 0009: event-driven `StrategyContext` (acks, async fills), `submit_stop`/`cancel`/`replace`/`open_orders`, gateway `positions()`/`open_orders()` resync, retire or flag the private-sim path in `WheelSdkBridge`; parity test against `tantra-exec-paper`.
3. Gap 0018: `InstrumentSpec` with tick rounding, costs from the wheel, "logic-test only" docstring, cross-engine golden test.
4. Gap 0015: extend `PromotionRecord` with code/params/data/result digests, seed, versions; `promote()` recomputes and rejects mismatches; inject clock.

**Gate**: as Phase A plus `pytest -q tests/integration tests/manifests`.

### Phase C — Deployment readiness
1. Gap 0016: package data under `tantra_strategies/_data/` via `importlib.resources`, `py.typed`, validator console script, wheel-install smoke test.
2. Gap 0017: compatible-release bounds, committed constraints file, typed wheel-host contract test.
3. R1: worker pool or `concurrent.futures` with per-call deadlines and `notifications/cancelled`, validated protocol version, optional HTTP/Streamable transport behind the runtime `Caller` layer, composition documented in `docs/design/` (runtime-supervised child versus `tantra-agent-mcp` front), load test in `tests/library/test_mcp_server.py`.

**Gate**: clean-venv wheel install + `ruff check .`, `mypy --strict`, `pytest -q tests/`.

## 3. Relationship to Other Plans

- Not duplicated here: root plan 0019 P4.5 (Parameter/model unification onto the wheel) and P3.5 (file split of large modules).
- Feeds root plan 0022 (deployment: library MCP as a supervised child, one Python child per runtime replica) and root plan 0023 (wheel build, constraints, SBOM/notice).
- Root gaps: 0010 (idempotency), 0013 (risk gate), 0016 (indicator golden parity), 0018 (lakehouse commit pinning), 0021 (fill-model unification), 0025 (lockfiles), 0026 (licensing/attribution).
- Provider repos: `tantra-runtime` (`PythonStrategyActor` host contract), `tantra-ffi` (wheel host, `simulated.py`), `tantra-core` (`ClientOrderId`), `tantra-agent` (`tantra-agent-mcp`).

## 4. Exit Criteria

1. Replaying a bar yields identical `client_order_id`s and duplicate submits are no-ops.
2. One bar fixture produces the same order/fill trace in `SimulatedContext` and the `tantra-exec-paper` backed host.
3. `LiveContext` dispatches `on_order_event`, handles PARTIAL fills and resyncs positions on start.
4. No `sdk -> library` or `library -> strategies` import edges (import-graph test green).
5. Every third-party-derived catalog entry carries SPDX licence, attribution and entry version; `NOTICE`/`LICENSE` shipped.
6. A promotion cannot succeed when the strategy source, parameters or data snapshot differ from recorded digests.
7. A wheel installed into a clean venv runs manifest validation and `run_basket`; `py.typed` present.
8. R1–R3 landed or re-filed as gaps with numbers.
