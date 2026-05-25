# Expected — Case 02: Style Transfer

## Expected Files Touched

**New files:**
- `features/active/style-transfer/01-product-spec.md`
- `features/active/style-transfer/02-technical-spec.md`
- `features/active/style-transfer/03-implementation-plan.md`
- `agents/style_mapper.py` OR logic added to `agents/prompt_parser.py`
- `ui/components/style_rationale.py` (new component)
- `tests/unit/test_style_mapper.py` or `test_prompt_parser.py`

**Modified files:**
- `dtos/contracts.py` — `IntentDTO` extended or new `StyleDTO`
- `agents/catalog_selector.py` — style constraint applied to SKU selection

**Must NOT be touched:**
- `render.py`, `layout.py`, `catalog.json`

## Skills That Should Be Used

- [ ] `skills/color-resolution.md` — keyword → hex → SKU mapping
- [ ] `skills/catalog.md` — SKU retrieval by style/color
- [ ] `skills/layout-typology.md` — style applied across all variant seeds
- [ ] `skills/ui-integration.md` — style rationale displayed in UI, not computed there
- [ ] `skills/dto-contracts.md` — IntentDTO extension before coding

## Required Workflow Steps

1. AGENTS.md read first
2. `features/active/style-transfer/` created, templates filled
3. Style → keyword map documented (deterministic, not ad-hoc LLM call)
4. `mcp_server/color_resolver.py` used for all color resolution
5. `mcp_server/server.py` used for all catalog queries
6. Nearest-color fallback adds `warnings[]` entry
7. `dtos/contracts.py` updated before agent code
8. Style rationale prepared in pipeline, displayed (not computed) in UI

## Rules That Must Be Followed

- Every resolved color must map to a real catalog SKU
- Nearest-color fallback must surface a warning in `VariantSummaryDTO.warnings`
- No catalog.json direct reads
- Style rationale in UI component is display-only (no resolution logic)
- No fake SKUs

## Tests That Must Be Added

- Test that "Scandinavian minimalist" resolves to expected color keywords
- Test that color keywords resolve to real catalog SKUs via MCP
- Test nearest-color fallback adds a warning
- Test that style constraint filters SKU selection correctly

## Forbidden Mistakes

- Color keyword mapping done with an ad-hoc LLM call instead of a documented map
- Resolved color that has no matching catalog SKU
- Style rationale computed in UI component (must be computed in pipeline, displayed in UI)
- Silently dropping the nearest-color warning

## Passing Criteria

- [ ] Templates filled before coding
- [ ] Style → keyword map is documented and deterministic
- [ ] All color resolution via mcp_server/color_resolver.py
- [ ] Fallback adds visible warning in UI
- [ ] No catalog.json direct reads
- [ ] Tests for mapping, resolution, and fallback
