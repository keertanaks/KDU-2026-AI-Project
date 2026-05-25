# Product Spec — budget-optimizer

> Fill every field before writing a single line of code.
> Leave no field blank — write "N/A" with a reason if truly not applicable.

---

## Feature Name
`budget-optimizer`

## User / Persona
**Homeowner** (Tab 1 — My Kitchen) and **Designer** (Tab 2 — Designer View).
Both personas need to see Estimated Cost per variant and know which items to swap
to hit a stated target budget.

## User Problem
A homeowner designs a dream kitchen but has no idea whether the generated layout
will cost £8,000 or £30,000. Without a cost signal, they cannot make trade-off
decisions. The optimizer surfaces a clearly-labeled *Estimated Cost* for every
variant and, when the user sets a target budget, automatically proposes cheaper
SKU swaps (staying within the real catalog) with re-checked NKBA scores—so the
homeowner can confidently pick the right variant.

## Use Case
1. User sets a target budget in the sidebar (e.g., "£15,000") and clicks
   **✨ Generate Layouts**.
2. The pipeline generates 3–5 variants as normal.
3. After NKBA validation, the `budget_optimization` graph node runs for each
   variant, estimates its Estimated Cost, and—if over target—proposes substitutions.
4. Each substitution: find the same-category, dimension-compatible, lower-tier SKU
   closest in color/style to the original; re-validate NKBA; accept if score delta ≥ −0.05.
5. The Streamlit UI (Tab 1 and Tab 2) shows:
   - Estimated Cost (labeled clearly as Estimated, not real prices)
   - Cost delta after optimization
   - NKBA score impact
   - Whether the variant is within target budget

## Success Criteria
1. Every variant shows "Estimated Cost: £X,XXX" labeled as an estimate in the UI.
2. When a budget target is set, at least one substitution is attempted for any
   variant over target and the result (savings + NKBA delta) is surfaced.
3. NKBA validation re-runs after every SKU substitution — unit test proves it.
4. Cabinet run continuity is maintained after substitution (no new gap > 50mm).
5. No invented SKUs — only real catalog entries appear as substitutes.

## Non-Goals
- Does NOT integrate with real pricing APIs or retailer data.
- Does NOT modify `catalog.json` — estimated prices are a separate code constant.
- Does NOT re-run placement geometry (positions unchanged; only SKU IDs swapped).
- Does NOT allow substituting appliances with cabinets or vice versa (category preserved).

## Inputs
- `input_json["preferences"]["budget_target_gbp"]` — optional float; if absent,
  estimation runs but no substitutions are attempted.
- `input_json["preferences"]["budget_tier"]` — existing field ("low"/"mid"/"high")
  used as fallback when numeric target is absent.
- `PreprocessingOutput.skus` — source of `price_tier` per SKU.
- `PlacementEngineOutput.positioned_items` — items to cost and potentially swap.
- `IntentDTO.color_keyword`, `IntentDTO.style` — for color/style preservation.

## Outputs
- `BudgetOptimizationDTO` per variant (new DTO in `dtos/contracts.py`).
- `VariantSummaryDTO.budget_optimization` — new optional field on existing DTO.
- UI: "Estimated Cost" panels in Tab 1 (variant card) and Tab 2 (designer view).

## Existing Workflow Affected
- Layer 1 (spatial_engine.py): [x] NOT touched
- Layer 2 (preprocessor.py / agents): [x] NOT touched
- Layer 3 (zone_planner.py / layout_strategist.py): [x] NOT touched
- Layer 4 (placement_engine.py): [x] NOT touched
- NKBA Validator (nkba_validator.py): [x] called again after each substitution
- Layer 5 (output_generator.py): [x] NOT touched (budget_optimization carries new data)
- Graph wiring (kitchen_graph.py): [x] new `budget_optimization` node inserted
  between `validation` and `output`
- UI (ui/app.py, ui/components/): [x] new `budget_display.py` component; Tab 1
  and Tab 2 updated

## Acceptance Criteria
- [ ] All Estimated Cost figures labeled "Estimated Cost" in UI and DTO field names
- [ ] `ESTIMATED_PRICE_MAP` constant in `pipeline/budget_optimizer.py` documented
- [ ] NKBA validation re-runs after every substitution (unit test `test_revalidation_after_substitution`)
- [ ] No gap > 50mm after substitution — checked in `test_substitute_preserves_continuity`
- [ ] Only real catalog SKU IDs appear as substitutes — no invented IDs
- [ ] `mcp_server/server.py` used for SKU lookups, never catalog.json directly
- [ ] `mcp_server/color_resolver.py` used for color preservation

## Edge Cases
- No budget target set: estimation still runs; substitution loop is skipped.
- No cheaper substitute exists for an item: skip that item, log a warning.
- Substitution creates a gap > 50mm: reject substitution, try next candidate.
- Substitution lowers NKBA score by more than 0.05: reject substitution.
- All items already at "low" tier: return original estimate with 0 substitutions.
- `budget_target_gbp = 0.0` or negative: treat as "no target" (None).

## Risks
- Estimated prices are approximations and may mislead users if not clearly labeled.
  Mitigation: every UI element shows "Estimated Cost" label; docstring in code.
- Substitution could theoretically worsen a layout if color/style changes are jarring.
  Mitigation: color preservation via `color_resolver.py`; style match attempted.

## Relevant Skills to Read Before Coding
- [x] skills/catalog.md
- [x] skills/color-resolution.md
- [x] skills/constraint-validation.md
- [x] skills/continuous-run.md
- [x] skills/variant-generation.md
- [x] skills/rendering.md
- [x] skills/ui-integration.md
- [x] skills/testing-strategy.md
- [x] skills/dto-contracts.md

## Expected Eval Case
`evals/harness/case-01-budget-optimizer/`
