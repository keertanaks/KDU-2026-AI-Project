# Implementation Plan — color-fallback

> **Do not write any code until this plan is fully filled out and reviewed.**

---

## Pre-Implementation Checklist
- [x] Read AGENTS.md
- [x] Read CLAUDE.md
- [x] Read CODING_STANDARDS.md (standards understood from prior sessions)
- [x] Filled 01-product-spec.md
- [x] Filled 02-technical-spec.md
- [x] Identified relevant skills (see below)
- [x] Read every relevant skill file and checked last_verified date (all 2026-05-24 ✓)
- [x] Inspected existing code in all files I plan to touch

## Relevant Skills Read
- [x] skills/color-resolution.md — version 1.0.0, last_verified 2026-05-24
- [x] skills/catalog.md — version 1.0.0, last_verified 2026-05-24
- [x] skills/testing-strategy.md — version 1.0.0, last_verified 2026-05-24

## Files I Will Inspect Before Writing
- [x] mcp_server/color_resolver.py — inspected (lines 1–182)
- [x] dtos/contracts.py — inspected (PreprocessingOutput lines 208–216)
- [x] agents/catalog_selector.py — inspected (full file)
- [x] pipeline/nkba_validator.py — inspected (lines 229–280, warning assembly + VariantSummaryDTO construction)
- [x] ui/components/variant_card.py — inspected (render_variant_card, lines 353–418 — no warnings displayed currently)
- [x] mcp_server/server.py — inspected (resolve_color lines 116–138)

---

## Step 1 — Confirm Scope and Re-Read Relevant Skills
- Skills re-read: color-resolution.md, catalog.md, testing-strategy.md
- Focus: warning format, exact vs. nearest match, no invented SKUs, no fake inline SKUs in tests
- Ambiguity resolved: warning is generated in `catalog_selector.py` (has catalog access) not in `prompt_parser.py` (no catalog)

## Step 2 — Inspect Existing Code Before Adding New Code
- `dtos/contracts.py` lines 208–216: `PreprocessingOutput` has 5 fields (intent, skus, zone_groups, zone_min_widths, nkba_constraints) — `color_warnings` will be 6th with default_factory
- `pipeline/nkba_validator.py` line 229: `warnings = list(placed.collision_flags)` — color_warnings will be appended here
- `graph/kitchen_graph.py` — not touched (PreprocessingOutput flows through as-is)
- `ui/components/variant_card.py` lines 394–400: shows violations but never shows warnings — needs new block

## Step 3 — Update DTOs First
- File: `dtos/contracts.py`
- Change: add `color_warnings: list[str] = field(default_factory=list)` to `PreprocessingOutput`
- Impact: all existing code constructing `PreprocessingOutput` uses keyword arguments, so no breakage. The `_fallback_output()` in catalog_selector.py also needs updating.

## Step 4 — Update Catalog / MCP Layer
- File: `mcp_server/color_resolver.py`
  - Add `from dataclasses import dataclass` (already imported via `from __future__ import annotations`)
  - Add `ColorResolution` dataclass at module top (after constants)
  - Add `resolve_color_keyword(keyword: str) -> ColorResolution` function
  - Update `keyword_to_hex()` to delegate to `resolve_color_keyword()` for DRY-ness
- File: `mcp_server/server.py`
  - Import `resolve_color_keyword` alongside existing imports
  - Update `resolve_color()` to use it and return `"nearest_match": not resolution.exact_match`

## Step 5 — Update Agent Modules
- File: `agents/catalog_selector.py`
  - Import `match_catalog_color, resolve_color_keyword` from `mcp_server/color_resolver`
  - In `select()`, add color warning detection block after the opening try:
    ```
    color_warnings: list[str] = []
    if intent.color_keyword:
        resolution = resolve_color_keyword(intent.color_keyword)
        if not resolution.exact_match:
            <find best SKU via match_catalog_color>
            <format warning message>
            color_warnings.append(warning)
            logger.warning(...)
    ```
  - In the `return PreprocessingOutput(...)` at line 171, add `color_warnings=color_warnings`
  - In `_fallback_output()`, add `color_warnings=color_warnings` (use the outer variable if in scope, otherwise `[]`)

## Step 6 — Update Pipeline Modules
- File: `pipeline/nkba_validator.py`
  - At line 229 (after `warnings = list(placed.collision_flags)`):
    ```python
    warnings.extend(preprocessing.color_warnings)
    ```
  - That's the only change needed — color_warnings become part of the variant's warning list

## Step 7 — Update Graph Wiring
- No graph wiring changes. PreprocessingOutput already flows through graph state.

## Step 8 — Update UI
- File: `ui/components/variant_card.py`
  - In `render_variant_card()`, after the violations block (after line ~400):
    ```python
    warnings_list = list(_get(v, "warnings") or [])
    if warnings_list:
        for w in warnings_list:
            st.markdown(
                f'<div style="background:#2D1F00;border-left:3px solid #D69E2E;'
                f'padding:6px 12px;border-radius:4px;margin:4px 0;'
                f'color:#D69E2E;font-size:0.85rem">⚠️ {w}</div>',
                unsafe_allow_html=True,
            )
    ```

## Step 9 — Add Unit Tests
- Unit test file: `tests/unit/test_color_resolver.py` (NEW)
  - `test_unknown_keyword_returns_nearest_match` — "dark grey" returns valid hex
  - `test_unknown_keyword_no_crash` — loop over varied unknown keywords, none raise
  - `test_resolved_color_has_real_sku` — load real catalog, verify hex maps to real SKU
  - `test_nearest_match_flag_is_set` — "dark grey" → exact_match=False
  - `test_exact_keyword_no_warning` — "white" → exact_match=True
  - `test_case_insensitive_matching` — "Dark Grey" == "dark grey"

- Fixture: tests/fixtures/sample_inputs.py — inspect if catalog fixture exists; if not, load via mcp_server.catalog_loader.get_catalog() directly in test (no fake SKUs)

## Step 10 — Lint and Unit Test Gate
```bash
ruff format . && ruff check . && mypy . && pytest tests/unit/ -v
```
- Expected: all pass
- If tests fail before my changes: document and skip

## Step 11 — Harness Eval Comparison
- Eval case: `evals/harness/case-05-color-fallback/`
- Compare to `expected.md` after implementation
- Fill `result-notes.md`

## Step 12 — Review
- Run `/review-impl` or check `checklists/pre-commit-checklist.md`

## Step 13 — Sign-Off Gate
- [x] Plan fully reviewed — proceed
- [x] Steps match product/technical specs
- [x] Protected files (render.py, layout.py, catalog.json) untouched
- [x] All relevant skills referenced

---

## Risk Register
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| `PreprocessingOutput` positional constructor calls break | Low | High | All callers use keyword args; `_fallback_output` updated |
| catalog not loaded in unit tests | Medium | Medium | Use `mcp_server.catalog_loader.get_catalog()` in test, not a fake |
| Warning generated for exact matches (false positive) | Low | Medium | `exact_match` flag gates the warning; unit test verifies |

## Open Questions
- None — all resolved during planning.
