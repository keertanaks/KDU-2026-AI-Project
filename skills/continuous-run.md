---
name: continuous-run
description: Use when placing cabinets, swapping SKUs, or modifying placement results. Ensures base cabinet runs are flush and gap-free per wall, with explicit corner handling and no hidden gaps in rendered output.
version: 1.0.0
last_verified: 2026-05-24
applies_to:
  - pipeline/placement_engine.py
  - pipeline/nkba_validator.py
  - dtos/contracts.py
  - tests/unit/test_placement_engine.py
tool_risk: medium
---

# Continuous-Run Skill

## Purpose
Ensure base cabinet runs are flush, gap-free, and corner-complete. Problems are fixed in placement data, never hidden in rendering.

## When to Use
Any time code places base cabinets, swaps a SKU for a different-width alternative, handles wall corners, or validates cabinet continuity.

## Existing Repo Pattern

**Rule LAYOUT-03** in `pipeline/nkba_validator.py`: gap > 50mm between adjacent base cabinets is a violation.

**Placement is resolved in `pipeline/placement_engine.py`**: semantic terms from Agent 3 are converted to exact x/y/z mm coordinates. Cabinet positions on a wall must be contiguous — each unit's `x + width_mm` equals the next unit's `x`.

**Corner handling**: blind corner, carousel, or filler cabinet must be explicitly placed at L/U-shape corners — the placement engine does not auto-generate corners.

## Rules
1. **No unexplained gaps between adjacent base cabinets** — gaps > 50mm trigger LAYOUT-03
2. **Corner handling is explicit**: when two cabinet-bearing walls meet, one of the following must be placed at the corner: blind corner cabinet, carousel, or filler
3. **After any SKU swap or new placement, re-run continuity/flush validation** BEFORE calling placement complete
4. **Continuity issues are fixed in placement data** — never hidden with a rendering workaround
5. **Do NOT reduce gap check threshold below 50mm** without an ADR — it's the LAYOUT-03 definition in `nkba_validator.py`

## Bad Example
```python
# WRONG — gaps left between cabinets after SKU swap
original_sku = items[2]  # 600mm wide
new_sku = catalog_selector.pick_cheaper(original_sku)  # 500mm wide
items[2] = new_sku  # 100mm gap created — no revalidation

# WRONG — gap hidden in rendering by scaling cabinet image
render_width = wall_segment / len(cabinets)  # stretches items visually
```

## Good Example
```python
# CORRECT — revalidate continuity after swap
items[2] = new_sku
filler_mm = original_sku.width_mm - new_sku.width_mm
if filler_mm > 0:
    items.insert(3, FillerCabinet(width_mm=filler_mm))
validate_continuity(items)  # re-check before returning
```

## Common Failure Modes
- SKU substitution (e.g., narrower budget alternative) leaves a gap that is never filled or flagged
- L/U corners missing blind corner or carousel — gap appears at the corner in rendered output
- Continuity check skipped after mid-wall insertion — first item recomputed but rest not shifted

## Must Not Do
- Never ship a layout with unexplained gaps between base cabinets
- Never work around a gap by modifying `render.py` — fix the placement data
- Never skip continuity validation after a SKU swap

## Completion Checklist
- [ ] No gap > 50mm between adjacent base cabinets on any wall
- [ ] All L/U corners have explicit blind corner, carousel, or filler
- [ ] Continuity re-validated after every SKU swap or insertion
- [ ] No rendering workarounds for placement gaps
- [ ] LAYOUT-03 unit test covers the new scenario
