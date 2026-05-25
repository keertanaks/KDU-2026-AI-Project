# Result Notes — Case 05: Color Fallback

## Date
2026-05-25

## Tool Used
Claude Code — claude-sonnet-4-6 (Sonnet 4.6)

## Prompt Used
`evals/harness/case-05-color-fallback/prompt.md` — no modifications

## Overall Status
✅ **PASS** — all passing criteria from expected.md satisfied

---

## What Passed

- [x] AGENTS.md read first (before any code written)
- [x] All 3 templates filled in `features/active/color-fallback/` before coding
- [x] `skills/color-resolution.md`, `skills/catalog.md`, `skills/testing-strategy.md` read
- [x] `mcp_server/color_resolver.py` inspected for existing behavior on unknown keywords
- [x] Fallback path implemented: `ColorResolution.exact_match=False` returned for unknown keywords
- [x] `resolve_color_keyword()` added — never crashes, always returns valid 6-char hex
- [x] `keyword_to_hex()` backward-compatible (delegates to new function)
- [x] `server.py:resolve_color()` returns `nearest_match: True` when not exact
- [x] Warning format exactly: "Requested color '{keyword}' not available — using nearest match: {name} (#{hex}) SKU: {sku_id}"
- [x] Warning in `PreprocessingOutput.color_warnings[]` → merged into `VariantSummaryDTO.warnings[]` by nkba_validator
- [x] UI component (`variant_card.py`) displays warnings in amber ⚠️ style (was silently swallowed before)
- [x] Tests added: `test_unknown_keyword_no_crash` (9 parametrised cases)
- [x] Tests added: `test_unknown_keyword_returns_nearest_match`
- [x] Tests added: `test_resolved_color_has_real_sku` (uses real catalog, no fake SKUs)
- [x] Tests added: `test_nearest_match_flag_is_set`
- [x] Tests added: `test_exact_keyword_no_warning` (6 known keywords)
- [x] Tests added: `test_case_insensitive_matching` (5 case variants)
- [x] Tests added: `test_dark_grey_variants_are_nearest_match` (5 spelling variants)
- [x] 28 new tests pass; 83 total unit tests pass (0 regressions)
- [x] render.py / layout.py / catalog.json untouched
- [x] No invented SKUs anywhere
- [x] All new functions have full type annotations + `from __future__ import annotations`
- [x] No `print()` — `logger.*` used throughout

## What Failed

None.

## Rules Violated

None. All AGENTS.md Non-Negotiable Rules observed:
- No hard-coded model strings
- No `print()` calls
- No direct `catalog.json` reads
- No invented SKUs
- Business logic in pipeline/agents, not UI

## Skills That Need Updates

None. All three skills (`color-resolution.md`, `catalog.md`, `testing-strategy.md`) guided
the implementation correctly. The color-resolution skill already described:
- the `nearest_match: true` warning flag pattern (Good Example section)
- the warning format
- the rule that resolved colors must map to real SKUs

## Follow-Up Action

None required. Eval passed cleanly on first attempt.
