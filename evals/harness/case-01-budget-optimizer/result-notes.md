# Result Notes — Case 01: Budget Optimizer

## Date
2026-05-25

## Tool Used
Claude Code (claude-sonnet-4-6) — /run-eval case-01-budget-optimizer

## Prompt Used
`evals/harness/case-01-budget-optimizer/prompt.md` — no modifications.

---

## What Passed

- [x] AGENTS.md (AGENT_SPECS.md) read first before any code
- [x] All 3 templates filled in `features/active/budget-optimizer/` before any code written
- [x] All 9 required skills identified and read: catalog, color-resolution, constraint-validation,
      continuous-run, variant-generation, rendering, ui-integration, testing-strategy, dto-contracts
- [x] DTOs defined in `dtos/contracts.py` FIRST (BudgetItemEstimate, BudgetEstimateDTO,
      SubstitutionDTO, BudgetOptimizationDTO; + new field on VariantSummaryDTO)
- [x] Estimated price map documented with "not real prices" comment; all DTO fields use
      `estimated_cost_gbp` naming; UI label reads "Estimated Cost"
- [x] `ESTIMATED_PRICE_MAP` as named constants, no bare numbers
- [x] `pipeline/budget_optimizer.py` created — all catalog access via `mcp_server/server.py`
- [x] `get_substitute_skus()` added to `mcp_server/server.py` (not direct catalog.json reads)
- [x] `mcp_server/color_resolver.py` used for color preservation (delta_e, keyword_to_hex)
- [x] `pipeline/nkba_validator.py` called after every accepted substitution
- [x] Cabinet run continuity checked (`_check_continuity()`, 50mm = LAYOUT-03 threshold)
- [x] Substitution rejected if NKBA score drops > 0.05
- [x] `budget_optimization` node wired into `graph/kitchen_graph.py` between validation → output
- [x] `ui/components/budget_display.py` created — display-only, no business logic
- [x] `ui/app.py` updated: sidebar number_input + Tab 1 render_budget_panel()
- [x] 16 unit tests in `tests/unit/test_budget_optimizer.py` (all pass)
- [x] `test_revalidation_after_substitution` added to `tests/unit/test_nkba_validator.py`
- [x] SKU fixtures added to `tests/fixtures/sample_inputs.py` (no fake SKUs inline in tests)
- [x] Protected files untouched: render.py, layout.py, catalog.json, CLAUDE.md
- [x] All 55 unit tests pass; ruff check passes
- [x] No variant dropped on budget optimizer error (try/except → keep original)

---

## What Failed

None. All expected.md passing criteria met.

---

## Rules Violated

None. No AGENTS.md Non-Negotiable Rules broken.

---

## Skills That Need Updates

None. All 9 skills provided correct guidance and prevented common failure modes:
- `catalog.md` prevented direct catalog.json reads
- `continuous-run.md` provided the 50mm gap threshold used in `_check_continuity()`
- `dto-contracts.md` enforced DTO-first order
- `constraint-validation.md` confirmed re-validation is required after substitution
- `ui-integration.md` kept `budget_display.py` clean of business logic

---

## Follow-Up Action

None required. Feature is complete and all tests pass.

Potential future improvements (not required by this eval):
- Add integration test in `tests/integration/test_graph.py` for end-to-end budget flow
- Consider caching the optimized estimate in `latest_run.json` serialisation
  (currently `BudgetOptimizationDTO` is in memory only; `output_generator.py` would
  need updating to serialize the new field if persistence is needed)
