# 0014 — `tantra_library` provenance and licence are optional free text; no LICENSE file

**Status**: open
**Filed**: 2026-11-23 — workspace design review (root plan 0021) · **Kind**: design-flaw · **Severity**: medium
**Plan**: [0006](../plans/0006-design-review-2026-11.md)

## What's stubbed or hardcoded

- `tantra_library/model.py:148-154` `Provenance(origin, reference_url, notes)` has no `license`, `attribution_required` or `non_commercial` field.
- `tantra_library/model.py:182` `provenance: Provenance | None = None`. `tantra_library/catalog.py` has only 8 `provenance=` sites. The LuxAlgo entry (`catalog.py:254-258`) says only "open-source on TradingView ... non-commercial research" without naming CC BY-NC-SA 4.0.
- `pyproject.toml:9` declares `license = { text = "MIT" }`. There is no `LICENSE` file in the repo root, and package-data omits any notice file.
- `Entry` has no `version` or `schema_version`. The MCP `serverInfo.version` is hard-coded `"0.1.0"` (`tantra_library/mcp/server.py:~181`).

## Why

The project is non-commercial, so non-commercial third-party licences (for example LuxAlgo CC BY-NC-SA ideas) are acceptable with attribution. The gap is provenance and consistent labelling, not a licensing blocker: clean-room implementations derived from LuxAlgo, BigBeluga and Skyrexio scripts ship under an MIT label with no machine-readable record of which entries carry NC/SA terms or what attribution they need, and a recipe result cannot be tied to an entry revision.

## How to close it

1. Add `license_spdx`, `attribution`, `commercial_use: bool` and `entry_version` to `Provenance` / `Entry`.
2. Make provenance mandatory for any entry derived from third-party material, enforced by a registry validation test.
3. Surface it in the MCP `describe` output and in `OverlayScene` metadata.
4. Add a `NOTICE` / `LICENSE` file listing third-party attributions, state the mixed-licence reality in `pyproject.toml`, and derive `serverInfo.version` from the package version.

**Verification**: registry validation test (every third-party-derived entry has SPDX id + attribution); golden `describe` output; `ruff check .`, `mypy --strict`, `pytest -q tests/library`.

## Related

- Root gap 0026 (licensing and third-party attribution across the workspace).
- [0015](0015-promotion-evidence-digest.md) (entry versions can be recorded in promotion evidence).
