# OpenSpec: Placement Engine
## File: `pipeline/placement_engine.py`
## Branch: `feature/placement-engine`
## Design Doc: §3.1 Layer 4, §8

---

## Goal
Translate Agent 3's semantic strategy into exact mm coordinates.
Pure Python math only. Zero LLM calls.

## Input
```python
zone_plan: ZonePlannerOutput
preprocessing: PreprocessingOutput
spatial: SpatialEngineOutput
```

## Output
```python
PlacementEngineOutput  # from dtos.contracts
```

---

## Class Structure

```python
class PlacementEngine:
    COLLISION_WHITELIST = {
        frozenset({"hood", "stove"}),
        frozenset({"tap", "sink"}),
        frozenset({"wall_cab", "base_cab"}),
        frozenset({"dishwasher", "base_cab"}),
    }

    def place(self, zone_plan: ZonePlannerOutput,
              preprocessing: PreprocessingOutput,
              spatial: SpatialEngineOutput) -> PlacementEngineOutput:
        positioned = {}
        spillover_log = []
        collision_flags = []

        # Step 1: Landing area allocation
        reserved_space = self._allocate_landing_areas(zone_plan, preprocessing, spatial)

        # Step 2: Anchored items first (sink, fridge, stove)
        # Step 3: Dependent items (hood, dishwasher)
        # Step 4: Fill items (base cabs, wall cabs, tall cabs)
        # Step 5: Collision detection

        return PlacementEngineOutput(
            variant_id=zone_plan.variant_id,
            positioned_items=positioned,
            spillover_log=spillover_log,
            collision_flags=collision_flags,
        )
```

---

## Semantic → Coordinate Resolution

```python
def _resolve_position(self, term: str, wall: Wall, item: SKU,
                      spatial: SpatialEngineOutput) -> tuple[float, float, float]:
    """Returns (x, y, z) all in mm."""
    wall_length = wall.length_mm
    wall_depth = wall.thickness_mm
    item_w = item.width_mm
    item_d = item.depth_mm
    item_h = item.height_mm

    # z=0 for floor items, z=900 for wall cabinets (above counter height)
    z_floor = 0.0
    z_wall_cab = 900.0  # standard counter height + small gap

    if "north-west corner" in term:
        return (0.0, wall_depth, z_floor)
    elif "north-east corner" in term:
        return (wall_length - item_w, wall_depth, z_floor)
    elif "south-west corner" in term:
        return (0.0, 0.0, z_floor)
    elif "south-east corner" in term:
        return (wall_length - item_w, 0.0, z_floor)
    elif "near" in term and "window" in term:
        window = self._find_window_on_wall(wall, spatial.exclusions)
        if window:
            cx = window.offset_mm + window.width_mm / 2
            x = cx - item_w / 2
            x = self._clamp_to_free_segment(x, item_w, wall.name, spatial)
            return (x, wall_depth, z_floor)
        else:
            return self._resolve_position("centre of " + wall.name, wall, item, spatial)
    elif "centre of" in term:
        return ((wall_length - item_w) / 2, wall_depth, z_floor)
    elif "left end of" in term:
        seg = spatial.free_segments.get(wall.name, [])
        x = seg[0].start_mm if seg else 0.0
        return (x, wall_depth, z_floor)
    elif "right end of" in term:
        seg = spatial.free_segments.get(wall.name, [])
        x = (seg[-1].end_mm - item_w) if seg else (wall_length - item_w)
        return (x, wall_depth, z_floor)
    elif "above" in term:
        ref_name = term.replace("above ", "").strip()
        ref = self._positioned.get(ref_name)
        if ref:
            cx = ref.position_mm["x"] + ref.dimensions_mm["width"] / 2 - item_w / 2
            return (cx, ref.position_mm["y"], ref.position_mm["z"] + ref.dimensions_mm["height"])
        return (0.0, wall_depth, z_wall_cab)
    elif "next to" in term:
        ref_name = term.replace("next to ", "").strip()
        ref = self._positioned.get(ref_name)
        if ref:
            x = ref.position_mm["x"] + ref.dimensions_mm["width"]
            return (x, ref.position_mm["y"], ref.position_mm["z"])
        return (0.0, wall_depth, z_floor)
    else:  # fallback
        return (0.0, wall_depth, z_floor)
```

---

## Landing Area Allocator

Zone weights: cooling=1.0, cleaning=1.0, cooking=0.9, prep=0.7, storage=0.4

```python
def _allocate_landing_areas(self, zone_plan, preprocessing, spatial) -> dict[str, float]:
    """Returns reserved counter mm per zone per wall."""
    total_available = sum(
        sum(s.length_mm for s in segs)
        for segs in spatial.free_segments.values()
    )
    total_needed = sum(preprocessing.zone_min_widths.values())

    if total_needed <= total_available:
        return preprocessing.zone_min_widths.copy()
    else:
        # Weighted proportional allocation
        weights = {"cooling": 1.0, "cleaning": 1.0, "cooking": 0.9, "preparation": 0.7, "storage": 0.4}
        total_weight = sum(weights.values())
        return {z: (weights[z] / total_weight) * total_available
                for z in weights}
```

---

## Spillover Handler

```python
def _handle_spillover(self, item: SKU, wall: Wall, spatial: SpatialEngineOutput,
                      positioned: dict, spillover_log: list) -> tuple[Wall, float] | None:
    """Returns (overflow_wall, x_position) or None if item dropped."""
    # Try adjacent wall
    adjacent = self._get_adjacent_wall(wall, spatial.walls)
    if adjacent and self._has_space(adjacent, item, spatial):
        return (adjacent, self._next_free_x(adjacent, item, spatial))

    # No space on adjacent wall either
    if item.category == "wall_cabinet":
        spillover_log.append(f"Dropped {item.sku_id} (wall_cabinet): no space on any wall")
        return None
    elif item.category == "island":
        spillover_log.append(f"Dropped {item.sku_id} (island): no space")
        return None
    else:
        # Appliance or tall cabinet: never drop
        # Log constraint violation, place at nearest corner
        spillover_log.append(f"CONSTRAINT_VIOLATION: {item.sku_id} forced to corner (no free space)")
        corner_x = 0.0  # nearest corner
        return (wall, corner_x)
```

---

## Collision Detector

```python
def _detect_collisions(self, positioned: dict) -> list[str]:
    flags = []
    items = list(positioned.items())
    for i, (name_a, item_a) in enumerate(items):
        for name_b, item_b in items[i+1:]:
            if self._is_whitelisted(item_a, item_b):
                continue
            if self._boxes_overlap_3d(item_a, item_b):
                flags.append(f"COLLISION: {name_a} overlaps {name_b}")
    return flags

def _boxes_overlap_3d(self, a: PlacedItem, b: PlacedItem) -> bool:
    """3D AABB overlap check — all in mm."""
    def overlap_1d(a_start, a_size, b_start, b_size):
        return a_start < b_start + b_size and b_start < a_start + a_size
    return (
        overlap_1d(a.position_mm["x"], a.dimensions_mm["width"],  b.position_mm["x"], b.dimensions_mm["width"])  and
        overlap_1d(a.position_mm["y"], a.dimensions_mm["depth"],  b.position_mm["y"], b.dimensions_mm["depth"])  and
        overlap_1d(a.position_mm["z"], a.dimensions_mm["height"], b.position_mm["z"], b.dimensions_mm["height"])
    )

def _is_whitelisted(self, a: PlacedItem, b: PlacedItem) -> bool:
    pair = frozenset({a.category, b.category})
    return pair in self.COLLISION_WHITELIST
```

---

## Output Format for render.py

Each positioned item must be formatted as render.py expects:
```python
{
    "is_wall": False,
    "product_id": item.sku_id,
    "position_mm": {"x": float, "y": float, "z": float},
    "dimensions_mm": {"width": float, "depth": float, "height": float},
    "rotation_z_deg": 0,
    "anchor_wall": wall_name,
    "zone_type": zone_name,
}
```

---

## Validation
```bash
python -c "
from pipeline.placement_engine import PlacementEngine
# Run on a mock ZonePlannerOutput
# Assert: all positioned_items have position_mm with x, y, z
# Assert: no unlisted collision_flags
# Assert: spillover_log is list
"
```
