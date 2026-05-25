# Expected — Case 05: Color Fallback

## Expected Files Touched

**New files:**
- `features/active/color-fallback/01-product-spec.md`
- `features/active/color-fallback/02-technical-spec.md`
- `features/active/color-fallback/03-implementation-plan.md`

**Modified files:**
- `mcp_server/color_resolver.py` — ensure `match_catalog_color()` handles unknown keywords gracefully
- `agents/catalog_selector.py` OR `agents/prompt_parser.py` — add warning to VariantSummaryDTO.warnings
- `tests/unit/test_color_resolver.py` OR appropriate test file — new fallback tests

**Must NOT be touched:**
- `render.py`, `layout.py`, `catalog.json`

## Skills That Should Be Used

- [ ] `skills/color-resolution.md` — the core skill for this case
- [ ] `skills/catalog.md` — every resolved color must map to a real SKU
- [ ] `skills/testing-strategy.md` — test unknown color, test warning presence

## Required Workflow Steps

1. AGENTS.md read first
2. Templates filled (even for this small change — templates enforce planning)
3. `mcp_server/color_resolver.py` inspected for existing behavior on unknown keywords
4. Fallback path: return nearest match with `nearest_match: True` flag
5. Warning message format: "Requested color '{keyword}' not available — using nearest match: {name} ({hex}) SKU: {sku_id}"
6. Warning added to `VariantSummaryDTO.warnings[]`
7. UI component (`variant_card.py`) confirmed to display warnings
8. Tests added: unknown keyword → no crash, returns nearest match, warning present

## Rules That Must Be Followed

- Never crash on unrecognized color keyword
- Resolved color must map to a real catalog SKU (verified by tests)
- Warning must be in `VariantSummaryDTO.warnings[]`, not just logged
- No invented SKUs
- Case-insensitive matching verified

## Tests That Must Be Added

- `test_color_resolver.py::test_unknown_keyword_returns_nearest_match`
- `test_color_resolver.py::test_unknown_keyword_no_crash`
- `test_color_resolver.py::test_resolved_color_has_real_sku`
- `test_color_resolver.py::test_nearest_match_flag_is_set`
- Warning appears in `VariantSummaryDTO.warnings` (integration or pipeline test)

## Forbidden Mistakes

- Returning `None` on unknown keyword
- Raising `KeyError` or `ValueError` instead of falling back
- Warning swallowed (logged but not surfaced in VariantSummaryDTO)
- Resolved hex that doesn't map to any real SKU
- "dark grey" hardcoded fix instead of general unknown-keyword handling

## Passing Criteria

- [ ] Templates filled before coding
- [ ] Unknown color keyword never crashes
- [ ] Nearest match returned with warning flag
- [ ] Warning in VariantSummaryDTO.warnings[]
- [ ] Resolved color maps to real SKU (test verifies)
- [ ] Case-insensitive handling verified in tests
