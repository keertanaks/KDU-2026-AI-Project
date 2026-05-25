# Technical Spec — budget-optimizer

> Fill every field before writing a single line of code.
> Reference real file paths from this repo — no generic placeholders.

---

## Pipeline Layers Affected

| Layer | File | Change Type | Description |
|-------|------|-------------|-------------|
| Layer 1 | pipeline/spatial_engine.py | none | Untouched |
| Layer 2 | pipeline/preprocessor.py | none | Untouched |
| Layer 2 | agents/prompt_parser.py | none | budget_target_gbp read from input_json directly |
| Layer 2 | agents/catalog_selector.py | none | Untouched |
| Layer 3 | pipeline/zone_planner.py | none | Untouched |
| Layer 3 | agents/layout_strategist.py | none | Untouched |
| Layer 4 | pipeline/placement_engine.py | none | Untouched |
| NKBA | pipeline/nkba_validator.py | none | Called again after substitution (no code change) |
| Layer 5b | pipeline/budget_optimizer.py | add | New module: estimation + substitution |
| Layer 5 | pipeline/output_generator.py | none | Untouched (budget_optimization in DTO) |
| Graph | graph/kitchen_graph.py | modify | New `budget_optimization` node + state field |
| DTOs | dtos/contracts.py | modify | New DTOs + optional field on VariantSummaryDTO |
| MCP | mcp_server/server.py | modify | Add get_substitute_skus() |
| UI | ui/components/budget_display.py | add | New display component |
| UI | ui/app.py | modify | Integrate budget_display in Tab 1 variant cards |

---

## DTO / Data Contract Changes

Define all changes to dtos/contracts.py FIRST.

```python
# Proposed changes to dtos/contracts.py:

# --- New DTOs ---

@dataclass
class BudgetItemEstimate:
    """Estimated cost for one placed SKU. Never a real price."""
    sku_id: str
    name: str
    category: str
    price_tier: str                  # "low" | "mid" | "high"
    estimated_cost_gbp: float        # labeled "Estimated Cost" everywhere


@dataclass
class BudgetEstimateDTO:
    """Estimated total cost for one variant. All figures are estimates."""
    variant_id: str
    total_estimated_cost_gbp: float  # labeled "Estimated Cost"
    items: list[BudgetItemEstimate]
    currency: str = "GBP"


@dataclass
class SubstitutionDTO:
    """One accepted SKU swap: original (higher-tier) → substitute (lower-tier)."""
    original_sku_id: str
    substitute_sku_id: str
    original_tier: str
    substitute_tier: str
    original_cost_gbp: float         # Estimated Cost
    substitute_cost_gbp: float       # Estimated Cost
    cost_delta_gbp: float            # negative = savings
    color_preserved: bool
    continuity_ok: bool
    nkba_score_before: float
    nkba_score_after: float
    warnings: list[str] = field(default_factory=list)


@dataclass
class BudgetOptimizationDTO:
    """Result of budget optimization for one variant."""
    variant_id: str
    target_budget_gbp: float | None
    original_estimate: BudgetEstimateDTO
    optimized_estimate: BudgetEstimateDTO | None    # None if no subs performed
    substitutions: list[SubstitutionDTO]
    within_budget: bool
    nkba_score_delta: float
    warnings: list[str] = field(default_factory=list)


# --- Modifications to existing DTOs ---

# VariantSummaryDTO: add optional field (default None — backward compatible)
#   budget_optimization: BudgetOptimizationDTO | None = None

# KitchenGraphState: add optional budget_target_gbp field
#   budget_target_gbp: float | None
```

---

## Estimated Price Map (documented in code)

```python
# pipeline/budget_optimizer.py — named constants, never bare numbers
# These are ESTIMATED approximate mid-market prices per cabinet/appliance unit.
# They are NOT real retail prices and MUST be labeled "Estimated Cost" in output.
ESTIMATED_PRICE_MAP: dict[str, float] = {
    "low":  500.0,   # Estimated Cost per low-tier unit (GBP)
    "mid":  1_200.0, # Estimated Cost per mid-tier unit (GBP)
    "high": 2_800.0, # Estimated Cost per high-tier unit (GBP)
}
```

---

## MCP / Catalog Changes

**`mcp_server/server.py`** — add one new function:

```python
def get_substitute_skus(
    category: str,
    max_tier: str,
    width_mm: float,
    width_tolerance_mm: float = 50.0,
) -> list[dict[str, Any]]:
    """Return catalog SKUs of given category at or below max_tier,
    with width within ±width_tolerance_mm of the target width.
    Used by budget_optimizer to find cheaper, dimension-compatible substitutes.
    """
```

**`mcp_server/color_resolver.py`** — no changes (used as-is for color preservation).

---

## Agent Changes

No agent changes. `budget_target_gbp` is read from
`input_json["preferences"]["budget_target_gbp"]` in the graph node.

---

## LangGraph State and Graph Changes

```python
# Proposed KitchenGraphState additions:
class KitchenGraphState(TypedDict):
    ...
    budget_target_gbp: float | None   # new — from input_json["preferences"]
```

**New node in `graph/kitchen_graph.py`:**

```python
graph.add_node("budget_optimization", self._node_budget_optimization)
# Inserted between validation and output:
# validation → budget_optimization → output
```

`_node_budget_optimization(self, state)`:
- Reads `budget_target_gbp` from state (or parses from `input_json["preferences"]`)
- Runs `BudgetOptimizer.optimize_variant()` for each validated variant
- Returns `{"validated_variants": [...updated with budget_optimization field...]}`

---

## UI Changes

**New file `ui/components/budget_display.py`:**
- `render_budget_panel(variant: VariantSummaryDTO | dict) -> None`
- Displays "Estimated Cost: £X,XXX" (always labeled as estimate)
- Shows substitution table (original SKU → substitute, cost delta, NKBA delta)
- Shows ✅ Within Budget / ⚠️ Over Budget badge
- NO business logic — reads pre-computed `budget_optimization` field only

**`ui/app.py` changes:**
- Sidebar: add `st.number_input("Budget target (£)", ...)` → stored in
  `input_json["preferences"]["budget_target_gbp"]`
- Tab 1 (My Kitchen): after each `render_variant_card(v, i)`, call
  `render_budget_panel(v)` if `budget_optimization` is present
- Import `from components.budget_display import render_budget_panel`

---

## Rendering / Output Changes

No rendering changes. `PlacedItem` coordinates are NOT modified by the optimizer
(only SKU IDs in `VariantSummaryDTO.budget_optimization.substitutions`).
`render.py` and `layout.py` are untouched.

---

## Validation Requirements

No new NKBA rules. `pipeline/nkba_validator.py` is called unchanged after each
substitution via `NKBAValidator().validate(placed, spatial, preprocessing)`.

The budget optimizer accepts a substitution only if
`nkba_score_after >= nkba_score_before - SCORE_DROP_TOLERANCE` where
`SCORE_DROP_TOLERANCE: float = 0.05`.

---

## Logging / Observability Requirements

All logging via `utils/logger.py`:
```python
logger.info("Budget optimizer: variant %s, estimated cost £%.0f", v_id, cost)
logger.info("Substitution accepted: %s → %s, saving £%.0f", orig, sub, delta)
logger.warning("No substitute found for SKU %s (category=%s)", sku_id, cat)
```

---

## Testing Requirements

| Test File | Test Name | What It Tests |
|-----------|-----------|---------------|
| tests/unit/test_budget_optimizer.py | test_estimated_cost_calculation | Sum of ESTIMATED_PRICE_MAP values matches total |
| tests/unit/test_budget_optimizer.py | test_substitute_preserves_continuity | No gap > 50mm after sub |
| tests/unit/test_budget_optimizer.py | test_no_sub_when_within_budget | Optimizer returns 0 subs if already under target |
| tests/unit/test_budget_optimizer.py | test_color_preservation_attempted | Substitution prefers same-color SKU |
| tests/unit/test_budget_optimizer.py | test_substitution_rejected_on_score_drop | Sub rejected if NKBA drops > 0.05 |
| tests/unit/test_nkba_validator.py | test_revalidation_after_substitution | Score recalculated after substitution |

---

## Relevant Skills

- [x] skills/catalog.md — ESTIMATED_PRICE_MAP, no direct catalog.json reads
- [x] skills/color-resolution.md — color_resolver.py for color preservation
- [x] skills/constraint-validation.md — re-run nkba_validator after substitution
- [x] skills/continuous-run.md — gap check after width substitution
- [x] skills/dto-contracts.md — new DTOs defined first
- [x] skills/testing-strategy.md — unit tests, no fake SKUs
- [x] skills/ui-integration.md — budget_display.py has no business logic
- [x] skills/variant-generation.md — optimization per-variant, parallel pattern preserved
- [x] skills/rendering.md — render.py untouched, coordinates unchanged

---

## Files Expected to Change

- `features/active/budget-optimizer/01-product-spec.md` (new)
- `features/active/budget-optimizer/02-technical-spec.md` (new)
- `features/active/budget-optimizer/03-implementation-plan.md` (new)
- `dtos/contracts.py` (modify — new DTOs + VariantSummaryDTO field + KitchenGraphState field)
- `mcp_server/server.py` (modify — add get_substitute_skus())
- `pipeline/budget_optimizer.py` (new)
- `graph/kitchen_graph.py` (modify — new node)
- `ui/components/budget_display.py` (new)
- `ui/app.py` (modify — sidebar input + Tab 1 display)
- `tests/unit/test_budget_optimizer.py` (new)
- `tests/unit/test_nkba_validator.py` (modify — add revalidation test)

---

## Files That MUST NOT Be Touched

- render.py
- layout.py
- catalog.json
- CLAUDE.md
- CODING_STANDARDS.md
- input1.json, input2.json, input3.json
- output.json, latest_run.json
- AGENT_SPECS.md

---

## Review Criteria

- All Estimated Cost outputs labeled (not bare numbers)
- `ESTIMATED_PRICE_MAP` documented with "not real prices" comment
- Every substitution re-validates NKBA (checked by test)
- No SKU invented — only IDs from `get_substitute_skus()` which reads real catalog
- No `catalog.json` reads outside of `mcp_server/catalog_loader.py`
- `budget_display.py` imports only `VariantSummaryDTO`; no pipeline imports
