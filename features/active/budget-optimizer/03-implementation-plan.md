# Implementation Plan — budget-optimizer

> **Do not write any code until this plan is fully filled out and reviewed.**

---

## Pre-Implementation Checklist
- [x] Read AGENTS.md (AGENT_SPECS.md at repo root)
- [x] Read CLAUDE.md
- [x] Read CODING_STANDARDS.md (referenced via CLAUDE.md)
- [x] Filled 01-product-spec.md
- [x] Filled 02-technical-spec.md
- [x] Identified relevant skills (listed below)
- [x] Read every relevant skill file and checked last_verified date (all 2026-05-24)
- [x] Inspected existing code in all files I plan to touch

## Relevant Skills Read
- [x] skills/catalog.md
- [x] skills/color-resolution.md
- [x] skills/constraint-validation.md
- [x] skills/continuous-run.md
- [x] skills/dto-contracts.md
- [x] skills/testing-strategy.md
- [x] skills/ui-integration.md
- [x] skills/variant-generation.md
- [x] skills/rendering.md

## Files I Will Inspect Before Writing
- [x] dtos/contracts.py (lines 1–224) — existing DTOs
- [x] pipeline/nkba_validator.py (lines 1–280) — validate() signature and constants
- [x] graph/kitchen_graph.py (lines 1–210) — existing node wiring
- [x] mcp_server/server.py (lines 1–186) — existing MCP tools
- [x] mcp_server/color_resolver.py — delta_e, match_catalog_color
- [x] ui/app.py (lines 1–300) — existing sidebar and Tab 1 structure
- [x] ui/components/variant_card.py — render_variant_card pattern
- [x] tests/unit/test_nkba_validator.py — existing test helpers

---

## Step 1 — Confirm Scope and Re-Read Relevant Skills
- Skills re-read: all 9 listed above
- Sections focused on: catalog "never read catalog.json directly", 
  constraint-validation "WORKFLOW-03 = 3962mm", continuous-run "gap > 50mm trigger"
- Ambiguity resolved: budget_target_gbp comes from input_json["preferences"], not from agent

## Step 2 — Inspect Existing Code Before Adding New Code
- `dtos/contracts.py` lines 1–224: SKU has price_tier; VariantSummaryDTO has layout dict;
  KitchenGraphState is a TypedDict. No budget fields exist yet.
- `pipeline/nkba_validator.py` lines 125–280: validate(placed, spatial, preprocessing) → VariantSummaryDTO
- `graph/kitchen_graph.py` lines 70–210: nodes validation → output; _node_validation returns validated_variants
- `mcp_server/server.py`: get_skus_by_price_tier() and get_skus_by_category() exist; no substitute helper

## Step 3 — Update DTOs First
- File: `dtos/contracts.py`
- Changes:
  ```python
  # Add after PlacedItem:
  @dataclass class BudgetItemEstimate (sku_id, name, category, price_tier, estimated_cost_gbp)
  @dataclass class BudgetEstimateDTO (variant_id, total_estimated_cost_gbp, items, currency="GBP")
  @dataclass class SubstitutionDTO (original_sku_id, substitute_sku_id, tiers, costs, deltas, flags, warnings)
  @dataclass class BudgetOptimizationDTO (variant_id, target_budget_gbp, original_estimate,
                                          optimized_estimate, substitutions, within_budget,
                                          nkba_score_delta, warnings)
  # Modify VariantSummaryDTO: add budget_optimization: BudgetOptimizationDTO | None = None
  # Modify KitchenGraphState: add budget_target_gbp: float | None
  ```
- Impact on existing callers: `budget_optimization=None` default is backward compatible;
  `budget_target_gbp` in state defaults to None if not set in initial state.

## Step 4 — Update Catalog / MCP Layer
- File: `mcp_server/server.py`
- New function: `get_substitute_skus(category, max_tier, width_mm, width_tolerance_mm=50.0)`
  - Calls `_get_catalog()` (already loaded), filters by category + tier ≤ max_tier + width ≈ target
  - Tier order: "low" < "mid" < "high"
  - Returns list of dicts (same shape as other MCP tools)
- No changes to catalog_loader.py or color_resolver.py

## Step 5 — No Agent Changes
- No agent modules touched (prompt_parser, catalog_selector, layout_strategist)

## Step 6 — Create Pipeline Module pipeline/budget_optimizer.py
- Named constants at module top:
  ```python
  ESTIMATED_PRICE_MAP: dict[str, float] = {"low": 500.0, "mid": 1_200.0, "high": 2_800.0}
  CONTINUITY_GAP_TOLERANCE_MM: float = 50.0
  SCORE_DROP_TOLERANCE: float = 0.05
  TIER_ORDER: list[str] = ["low", "mid", "high"]
  ```
- Class `BudgetOptimizer(validator: NKBAValidator)`
- `estimate_cost(placed, skus) → BudgetEstimateDTO`
  - For each item in placed.positioned_items, look up sku_id in skus dict
  - If not found, try mcp get_catalog_items() fallback
  - Return BudgetEstimateDTO with list of BudgetItemEstimate
- `_find_substitutes(sku_id, skus, intent, target_tier) → list[dict]`
  - Calls `get_substitute_skus(category, max_tier, width_mm)`
  - Sorts by color match (delta_e via color_resolver), then style match
- `_check_continuity(placed, item_name, new_width_mm) → bool`
  - Reads item neighbors by x-position on same wall
  - Returns True if gap ≤ CONTINUITY_GAP_TOLERANCE_MM
- `optimize_variant(variant, placed, target_budget_gbp, spatial, preprocessing) → BudgetOptimizationDTO`
  - Estimate original cost
  - If no target or under target → return no-op DTO (within_budget=True, 0 subs)
  - Sort items by estimated_cost_gbp descending
  - For each over-budget item: try substitutes; first that passes continuity + score check → accept
  - Re-validate NKBA after each accepted sub
  - Return BudgetOptimizationDTO

## Step 7 — Update Graph Wiring in graph/kitchen_graph.py
- New node: `budget_optimization` → `_node_budget_optimization(state)`
- New import: `from pipeline.budget_optimizer import BudgetOptimizer`
- In `__init__`: `self._budget_optimizer = BudgetOptimizer(self._validator)`
- In `_build()`:
  - `graph.add_node("budget_optimization", self._node_budget_optimization)`
  - Change `validation` → `budget_optimization` → `output`
  - Remove direct `validation` → `output` edge; add two new edges
- `_node_budget_optimization(state)`:
  - Reads `budget_target_gbp` from `input_json["preferences"]`
  - Calls `optimize_variant()` for each (variant, placed) pair
  - Returns `{"validated_variants": enriched_variants}`
- `KitchenGraphState` updated in dtos/contracts.py (step 3)
- `initial` dict in `run()`: add `"budget_target_gbp": None`

## Step 8 — Update UI
- File: `ui/components/budget_display.py`
  - `render_budget_panel(variant: VariantSummaryDTO | dict) -> None`
  - Reads `budget_optimization` field from variant (safe getattr/dict.get)
  - Displays: "💰 Estimated Cost" header, total cost metric, within/over badge
  - Shows substitutions table: SKU, Tier change, Savings, NKBA delta
  - Shows disclaimer: "Costs are estimates only — not real prices"
  - Zero business logic — pure display
- File: `ui/app.py`
  - Import `render_budget_panel` from `components.budget_display`
  - Sidebar: add `budget_target = st.number_input(...)` after the budget radio
  - In "generate" block: set `input_json["preferences"]["budget_target_gbp"] = budget_target or None`
  - Tab 1: after `render_variant_card(v, i)` call `render_budget_panel(v)`

## Step 9 — Add / Update Unit and Integration Tests
- Unit test file: `tests/unit/test_budget_optimizer.py`
  - `test_estimated_cost_calculation` — verifies sum(ESTIMATED_PRICE_MAP[tier]) == total
  - `test_substitute_preserves_continuity` — swap a 600mm item for another 600mm item; gap == 0
  - `test_no_sub_when_within_budget` — target > total cost → 0 substitutions, within_budget=True
  - `test_color_preservation_attempted` — substitute list sorted by color closeness
  - `test_substitution_rejected_on_score_drop` — mock validator returns low score → sub rejected
- `tests/unit/test_nkba_validator.py`: add `test_revalidation_after_substitution`
  - Build a PlacementEngineOutput, run validate(), change a SKU tier, run validate() again
  - Assert second score is re-calculated independently
- Fixture data: use `tests/fixtures/sample_inputs.py` helpers; no inline fake SKUs

## Step 10 — Lint and Unit Test Gate
```bash
ruff format . && ruff check . && mypy . && pytest tests/unit/ -v
```
- Expected outcome: all pass
- New code uses `from __future__ import annotations`, full type annotations, no bare numbers

## Step 11 — Harness Eval Comparison
- Eval case: `evals/harness/case-01-budget-optimizer/`
- Compare output to `expected.md`
- Fill `result-notes.md`

## Step 12 — Review
- Run `/review-impl` and confirm all checklist items in `checklists/pre-commit-checklist.md`

## Step 13 — Sign-Off Gate

- [x] Is this plan fully reviewed and approved? YES
- [x] Does every step match the product/technical specs? YES
- [x] Are all protected files (render.py, layout.py, catalog.json) untouched? YES
- [x] Are all relevant skills referenced? YES — all 9 skills read

---

## Risk Register
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| SKU substitute not found for a category | Medium | Low | Skip + warn; return original |
| NKBA score drops after substitution | Medium | Medium | Reject if drop > 0.05 |
| Substitution creates gap > 50mm | Low | Medium | Width-tolerance check before accepting |
| Estimated prices mislead user | Low | High | Clear "Estimated Cost" label everywhere |

## Open Questions
- All resolved before coding starts.
