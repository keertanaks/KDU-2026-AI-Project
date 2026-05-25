---
name: rendering
description: Use when producing output JSON consumed by render.py or layout.py, adding new PlacedItem fields, or debugging visual rendering issues. render.py and layout.py are PROTECTED — never modify them.
version: 1.0.0
last_verified: 2026-05-24
applies_to:
  - pipeline/output_generator.py
  - dtos/contracts.py
  - render.py
  - layout.py
  - tests/unit/test_output_generator.py
tool_risk: high
---

# Rendering Skill

## Purpose
Ensure output JSON produced by `pipeline/output_generator.py` exactly matches what `render.py` and `layout.py` expect. Rendering problems are always fixed in data, never in the renderer.

## When to Use
Any time code serializes `PlacedItem` or `FinalOutput` to JSON, adds new output fields, or investigates visual rendering artifacts.

## Existing Repo Pattern

**Protected files**: `render.py` and `layout.py` are in CLAUDE.md's NEVER MODIFY list. Do not touch them.

**Coordinate system**: all coordinates in mm, origin at south-west corner of the room.

**`PlacedItem` in `dtos/contracts.py`** — key fields consumed by `render.py`:
- `id`: str (SKU ID)
- `name`: str
- `x`, `y`, `z`: float (mm from origin)
- `width_mm`, `depth_mm`, `height_mm`: float
- `wall`: str (wall name, e.g., "north", "south", "east", "west")
- `category`: str
- `color_hex`: str

**`FinalOutput` in `dtos/contracts.py`** — top-level structure serialized by `output_generator.py`.

**Rendering problems must be diagnosed in data**: if items appear in wrong positions, stacked incorrectly, or with gaps → fix the `PlacedItem` coordinates in `placement_engine.py` or `output_generator.py`, not in `render.py`.

## Rules
1. **Never modify `render.py` or `layout.py`** under any circumstances
2. **All coordinates are mm** — no unit conversion at the render boundary
3. **Origin is south-west corner** — positive x goes east, positive y goes north, positive z goes up
4. **Do not create alternate rendering formats** unless the technical spec explicitly requires it
5. **Rendering artifacts (wrong positions, overlaps, gaps) are data bugs** — fix in placement engine or output generator

## Bad Example
```python
# WRONG — modifies render.py to work around bad data
# (in render.py)
item_x = item["x"] + 50  # hack offset to fix positioning

# WRONG — coordinates in metres, not mm
placed_item = PlacedItem(x=1.2, y=0.6, ...)  # should be x=1200, y=600
```

## Good Example
```python
# CORRECT — fix data in placement_engine.py
placed_item = PlacedItem(
    x=resolved_x_mm,   # integer mm from south-west origin
    y=wall_depth_mm,   # north wall items sit at y=wall_depth
    z=0.0,             # base cabinet, z=0
    ...
)
# CORRECT — output_generator serializes without transforming coordinates
```

## Common Failure Modes
- Coordinates produced in metres → items rendered at 1/1000 scale (invisible or misplaced)
- Z-axis ignored for wall cabinets → hood and wall cabinets render at floor level
- New field added to `PlacedItem` not accounted for in `output_generator.py` serializer

## Must Not Do
- Never modify `render.py` or `layout.py`
- Never produce coordinates outside the mm coordinate system
- Never add a field to `PlacedItem` without updating `output_generator.py` serialization

## Completion Checklist
- [ ] `render.py` and `layout.py` untouched
- [ ] All coordinates are mm, origin south-west
- [ ] `PlacedItem` fields match `dtos/contracts.py` definition
- [ ] `output_generator.py` serializes all new fields
- [ ] Rendering issues fixed in data, not renderer
