# Expected — Case 01: Budget Optimizer

## Expected Files Touched

**New files:**
- `features/active/budget-optimizer/01-product-spec.md`
- `features/active/budget-optimizer/02-technical-spec.md`
- `features/active/budget-optimizer/03-implementation-plan.md`
- `pipeline/budget_optimizer.py` (or similar; new pipeline module)
- `dtos/contracts.py` — new `BudgetOptimizationDTO` or new fields on existing DTOs
- `ui/components/budget_display.py` (or updates to `variant_card.py`)
- `tests/unit/test_budget_optimizer.py`

**Modified files:**
- `dtos/contracts.py` — new DTO fields or new dataclass
- `graph/kitchen_graph.py` — new node wired in
- `ui/app.py` — budget display integrated

**Must NOT be touched:**
- `render.py`, `layout.py`, `catalog.json`, `CLAUDE.md`, `CODING_STANDARDS.md`

## Skills That Should Be Used

- [ ] `skills/catalog.md` — price_tier lookup, no real prices, estimated price map required
- [ ] `skills/color-resolution.md` — preserve color when substituting SKUs
- [ ] `skills/constraint-validation.md` — re-run NKBA after substitution
- [ ] `skills/continuous-run.md` — substitution must not create cabinet run gaps
- [ ] `skills/variant-generation.md` — substitution applied per-variant
- [ ] `skills/rendering.md` — output shape unchanged for render.py
- [ ] `skills/ui-integration.md` — budget display in UI, no business logic in component
- [ ] `skills/testing-strategy.md` — unit tests for optimizer logic
- [ ] `skills/dto-contracts.md` — new DTOs before writing node code

## Required Workflow Steps

1. AGENTS.md read first
2. `features/active/budget-optimizer/` created
3. All three templates filled
4. Estimated price map documented in technical spec AND in code (as named constants)
5. `dtos/contracts.py` updated before node code written
6. `pipeline/nkba_validator.py` called after every SKU substitution
7. `graph/kitchen_graph.py` wired with new node
8. `mcp_server/server.py` used for SKU lookups (not catalog.json directly)
9. `mcp_server/color_resolver.py` used for color preservation
10. Tests written (unit for budget math, integration for full flow)

## Rules That Must Be Followed

- All cost output labeled "Estimated Cost"
- Documented estimated price map using price_tier (low/mid/high) — never claimed as real prices
- No invented SKUs — only real catalog entries as substitutes
- NKBA validation re-run after every substitution
- Cabinet run continuity re-checked after substitution (LAYOUT-03)
- No business logic in `ui/components/budget_display.py`

## Tests That Must Be Added

- `test_budget_optimizer.py::test_estimated_cost_calculation` — verify cost sum matches price_tier map
- `test_budget_optimizer.py::test_substitute_preserves_continuity` — verify no gap > 50mm after swap
- `test_nkba_validator.py::test_revalidation_after_substitution` — verify score recalculated
- At minimum one test of color preservation behavior

## Forbidden Mistakes

- Using real prices or unlabeled costs
- Inventing SKUs that don't exist in catalog.json
- Skipping NKBA re-validation after a substitution
- Reading catalog.json directly (must use mcp_server/server.py)
- Placing budget calculation logic in ui/components/

## Passing Criteria

- [ ] All three templates filled before any code written
- [ ] Estimated price map documented and labeled "Estimated Cost"
- [ ] NKBA validation re-runs after substitution (tests prove it)
- [ ] Cabinet continuity maintained after substitution
- [ ] No catalog.json direct reads
- [ ] No invented SKUs
- [ ] Tests added for optimizer logic
- [ ] Budget display in UI surfacing "Estimated Cost" label
