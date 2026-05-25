---
name: layout-typology
description: Use when writing code that selects kitchen shapes (L/U/I/island), implements variant seed differentiation, or handles Mode A (user-specified shape) vs Mode B (layout_family=null) logic in pipeline/zone_planner.py and agents/layout_strategist.py.
version: 1.0.0
last_verified: 2026-05-24
applies_to:
  - agents/layout_strategist.py
  - pipeline/zone_planner.py
  - dtos/contracts.py
tool_risk: medium
---

# Layout Typology Skill

## Purpose
Govern how kitchen shapes are selected and how variant seeds enforce meaningful diversity across the 3–5 generated layouts.

## When to Use
Any feature touching layout shape selection, variant seeding, Mode A/B logic, or the `layout_family` field.

## Existing Repo Pattern

**Shapes** (from `agents/layout_strategist.py`): `SHAPES = ["L", "U", "I"]`
- "island" is a `special_request`, never a `layout_family`
- G-shape is not yet implemented

**Mode A** (user specifies shape via `input_json.preferences.layout_family`):
- All variants use that shape; seeds only change zone/item placement strategy

**Mode B** (`layout_family=null`):
- `MODE_B_SHAPES = {1: "L", 2: "U", 3: "I"}` in `layout_strategist.py`
- Capacity overrides: `MODE_B_SHAPES_CAPACITY_L` and `MODE_B_SHAPES_CAPACITY_I` when room can't support U

**Variant seeds** (from `CLAUDE.md` and `AGENT_SPECS.md`):
| Variant | Strategy Suffix |
|---------|----------------|
| 1 | Prefer L-shape, maximise counter run, fridge at far end |
| 2 | Prefer U-shape, tight work triangle, dishwasher opposite sink wall |
| 3 | Prefer I-shape or island, minimise cost, narrower SKUs |
| 4 | Maximise storage, tall cabinets and wall cabinets |
| 5 | Accessibility focus, wide aisles, no tall cabinets blocking circulation |

**Variant IDs**: Mode A uses `{v1, v2, v3}`; Mode B uses `{vA, vB, vC}` (from `layout_strategist.py`)

## Rules
1. **Never default all variants to the same shape** in Mode B — the seed table above determines shape
2. **Never conflict with existing zone planning logic** in `pipeline/zone_planner.py` — the ZonePlanner wraps LayoutStrategist, don't bypass it
3. **Mode A does NOT override seeds** — shape is fixed by user but placement strategies still differ per seed
4. Capacity constraints must use the existing `MODE_B_SHAPES_CAPACITY_L/I` fallback maps from `layout_strategist.py`
5. `layout_family` values must be exactly `"L"`, `"U"`, `"I"`, or `null` — no other strings

## Bad Example
```python
# WRONG — all variants get same shape regardless of seed
for variant_id in range(1, 4):
    shape = user_shape or "L"  # always L in Mode B

# WRONG — skips ZonePlanner, calls LayoutStrategist directly from graph node
result = await layout_strategist.run(...)  # bypasses pipeline/zone_planner.py
```

## Good Example
```python
# CORRECT — Mode B shape comes from seed map
shape = MODE_B_SHAPES[variant_index]  # → L, U, or I per slot
# CORRECT — ZonePlanner is the layer 3 entry point
variants = await zone_planner.run(preprocessing, spatial, input_json, retry_context)
```

## Common Failure Modes
- Treating "island" as a `layout_family` value — it is a `special_request`
- All 3 variants assigned "L" in Mode B because seed differentiation was not applied
- New variant seed added that conflicts with an existing seed's shape assignment

## Must Not Do
- Never create a 4th or 5th shape type without an ADR
- Never assign shape purely randomly — shapes must be deterministic per seed/mode

## Completion Checklist
- [ ] Mode A and Mode B handled separately
- [ ] Mode B uses `MODE_B_SHAPES` (or capacity fallbacks)
- [ ] Seeds produce meaningfully different shapes and placements
- [ ] `layout_family` values are only "L", "U", "I", or null
- [ ] ZonePlanner is the Layer 3 entry point — not called around
