# Product Spec — color-fallback

> Fill every field before writing a single line of code.

---

## Feature Name
color-fallback

## User / Persona
All four tabs (Designer / Homeowner / Builder / PM) — any user who specifies a color that is
not in the catalog's exact keyword set.

## User Problem
When a user requests a color like "dark grey" that has no exact entry in the `COLOR_KEYWORD_HEX`
table, the system silently substitutes the nearest available color without telling the user.
The user has no idea their color request was not honoured. Worse, if `color_resolver.py` ever
falls through to `_FALLBACK_HEX = "808080"` — a neutral grey not backed by any catalog SKU
reference — the resolved color could be mis-applied, wasting layout time and eroding trust.

## Use Case
1. User types "I want dark grey cabinets" into the Streamlit input.
2. Agent 1 (PromptParser) extracts `color_keyword="dark grey"`.
3. The color is not in `COLOR_KEYWORD_HEX`; closest keyword in `_COLOR_TABLE` is "grey" (#9CA3AF).
4. System substitutes "#9CA3AF" and matches it to the nearest catalog SKU.
5. **NEW**: a warning is generated: "Requested color 'dark grey' not available — using nearest
   match: Soft Grey Cabinet (#9CA3AF) SKU: SKU-BC-SG-01"
6. Warning appears in `VariantSummaryDTO.warnings[]` for every generated variant.
7. Warning is displayed in the Streamlit UI on each variant card.

## Success Criteria
1. System never crashes on an unrecognised color keyword.
2. A human-readable warning appears in `VariantSummaryDTO.warnings[]` whenever a
   nearest-color substitution is made.
3. The resolved color always maps to a real catalog SKU (verified by test).

## Non-Goals
- Does not expand the `COLOR_KEYWORD_HEX` / `_COLOR_TABLE` dictionaries (that is a separate
  content task).
- Does not change the NKBA scoring formula for color mismatches.
- Does not create a user-facing color picker or preview swatch.

## Inputs
- `intent.color_keyword` — the raw color string from the user prompt.
- `intent.color_hex` — the hex code resolved by PromptParser (may be a partial/fallback match).
- `mcp_server/_CATALOG` — loaded catalog with SKU hex colors for delta-E matching.

## Outputs
- `PreprocessingOutput.color_warnings: list[str]` — new field; non-empty when a substitution occurs.
- `VariantSummaryDTO.warnings[]` — color warning appended by NKBA validator.
- Streamlit UI — variant card displays warnings in amber ⚠️ style.

## Existing Workflow Affected
- Layer 1 (spatial_engine.py): [x] NOT touched
- Layer 2 (preprocessor.py / agents): [x] touched — catalog_selector.py generates warning
- Layer 3 (zone_planner.py / layout_strategist.py): [x] NOT touched
- Layer 4 (placement_engine.py): [x] NOT touched
- NKBA Validator (nkba_validator.py): [x] touched — merges color_warnings into variant warnings
- Layer 5 (output_generator.py): [x] NOT touched
- Graph wiring (kitchen_graph.py): [x] NOT touched
- UI (ui/app.py, ui/components/): [x] touched — variant_card.py renders warnings

## Acceptance Criteria
- [ ] `keyword_to_hex("dark grey")` does not raise any exception
- [ ] `resolve_color_keyword("dark grey")` returns `exact_match=False`
- [ ] Warning string contains original keyword, matched hex, and real SKU ID
- [ ] Warning present in `VariantSummaryDTO.warnings[]` (not just in logs)
- [ ] UI variant card shows warnings in amber style
- [ ] All 4 required tests pass in `tests/unit/test_color_resolver.py`
- [ ] render.py, layout.py, catalog.json untouched

## Edge Cases
- Keyword exactly in table → no warning generated (happy path)
- Keyword resolves via prefix match → warning generated ("dark grey" matches "grey")
- Keyword has no partial match → fallback hex used + warning generated
- Empty/None color_keyword → no warning generated
- Case variations ("Dark Grey", "DARK GREY") → treated identically to "dark grey"

## Risks
- `PreprocessingOutput.color_warnings` field addition may break existing callers that
  construct `PreprocessingOutput` positionally — mitigated by using `field(default_factory=list)`.
- `nkba_validator.py` now accepts `preprocessing` parameter (already present) — no breaking change.

## Relevant Skills to Read Before Coding
- [x] skills/color-resolution.md
- [x] skills/catalog.md
- [x] skills/testing-strategy.md

## Expected Eval Case
`evals/harness/case-05-color-fallback/`
