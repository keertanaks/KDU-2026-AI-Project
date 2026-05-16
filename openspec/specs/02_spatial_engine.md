# OpenSpec: Spatial Engine
## File: `pipeline/spatial_engine.py`
## Branch: `feature/spatial-engine`
## Design Doc: §3.1 Layer 1, §8

---

## Goal
Parse raw input JSON into `SpatialEngineOutput` — walls, free segments, flow order, exclusions, layout capacity.
Pure Python math only. Zero LLM calls. Zero network calls.

## Input
```python
input_json: dict  # raw input1.json / input2.json / input3.json structure
```

## Output
```python
SpatialEngineOutput  # from dtos.contracts
```

---

## Class Structure

```python
class SpatialEngine:
    def parse(self, input_json: dict) -> SpatialEngineOutput:
        walls = self._parse_walls(input_json["environment"]["wall"])
        exclusions = self._parse_openings(input_json["environment"].get("openings", []))
        free_segments = self._compute_free_segments(walls, exclusions)
        flow_order = self._compute_flow_order(walls)
        layout_capacity = self._determine_layout_capacity(walls)
        return SpatialEngineOutput(
            walls=walls,
            free_segments=free_segments,
            flow_order=flow_order,
            exclusions=exclusions,
            layout_capacity=layout_capacity,
        )
```

---

## Method: `_parse_walls`

Extract from each wall dict:
- `name` = wall["name"]
- `anchor` = wall["anchor"]
- `length_mm` = wall["dimensions"]["length_mm"]
- `height_mm` = wall["dimensions"]["height"]
- `thickness_mm` = wall["thickness_mm"]
- `has_cabinets` = wall["has_cabinets"]
- `points` = wall["points"]

Return only walls where `has_cabinets = true`.

---

## Method: `_parse_openings`

For each opening:

**Door:**
```
blocked_start = opening["offset_mm"]
blocked_end = opening["offset_mm"] + opening["width_mm"] + opening["width_mm"]
# footprint (width_mm) + swing arc (also width_mm when swing_direction=in)
```

**Window:**
```
blocked_start = opening["offset_mm"]
blocked_end = opening["offset_mm"] + opening["width_mm"]
# only for wall_cabinet placement — base cabs allowed if cab_height <= sill_mm
```

Store both `blocked_start_mm` and `blocked_end_mm` on the Opening DTO.
Also store `sill_mm` from opening (0 for doors).

Map opening to its wall using `opening["wall"]` anchor string.

---

## Method: `_compute_free_segments`

For each cabinet wall:
1. Collect all blocked ranges from openings on that wall
2. Merge overlapping ranges
3. Subtract blocked ranges from [0, wall_length_mm]
4. Return remaining ranges as list of Segment(start_mm, end_mm)
5. Drop any segment shorter than 100mm (too small to place anything)

```python
def _compute_free_segments(self, walls: list[Wall], exclusions: list[Opening]) -> dict[str, list[Segment]]:
    result = {}
    for wall in walls:
        wall_openings = [e for e in exclusions if e.wall == wall.anchor]
        blocked = [(e.blocked_start_mm, e.blocked_end_mm) for e in wall_openings]
        free = subtract_ranges(0, wall.length_mm, blocked)
        result[wall.name] = [Segment(s, e) for s, e in free if (e - s) >= 100]
    return result
```

---

## Method: `_compute_flow_order`

Return `has_cabinets` wall names sorted by `length_mm` descending (longest wall gets cabinets first).

---

## Method: `_determine_layout_capacity`

```python
cabinet_walls = [w for w in walls if w.has_cabinets]
n = len(cabinet_walls)
if n >= 3:
    return "U"
elif n == 2:
    # Check if adjacent (L) — share a corner point
    return "L"
else:
    return "I"
```

To check adjacency: two walls share an anchor if their anchor names are adjacent (north+east, east+south, south+west, west+north). Order doesn't matter.

---

## Test Cases

### input1.json (3600×3200mm, no openings, north+east walls cabinet)
```
Expected:
  layout_capacity = "L"
  free_segments["north_wall"] = [Segment(0, 4200)]  ← wait, input1 is 3600×3200
  Actually input1: north_wall length=3600, east_wall length=3200
  free_segments["north_wall"] = [Segment(0, 3600)]
  free_segments["east_wall"]  = [Segment(0, 3200)]
  flow_order = ["north_wall", "east_wall"]  (3600 > 3200)
```

### input3.json (4200×3000mm, door on south + 2 windows, north+east cabinet)
```
north_wall: window at offset=1500, width=1200 → blocked [1500, 2700] for wall_cabs
  free_segments["north_wall"] = [Segment(0, 1500), Segment(2700, 4200)]
east_wall: window at offset=600, width=800 → blocked [600, 1400] for wall_cabs
  free_segments["east_wall"] = [Segment(0, 600), Segment(1400, 3000)]
south_wall: door but has_cabinets=false → not in free_segments
flow_order = ["north_wall", "east_wall"]  (4200 > 3000)
```

---

## Validation
```bash
python -c "
from pipeline.spatial_engine import SpatialEngine
import json
with open('input3.json') as f: data = json.load(f)
result = SpatialEngine().parse(data)
print('capacity:', result.layout_capacity)
print('segments:', {k: [(s.start_mm, s.end_mm) for s in v] for k, v in result.free_segments.items()})
print('flow:', result.flow_order)
print('exclusions:', [(e.id, e.blocked_start_mm, e.blocked_end_mm) for e in result.exclusions])
"
```
