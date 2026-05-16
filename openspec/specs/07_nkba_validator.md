# OpenSpec: NKBA Validator + Scoring
## File: `pipeline/nkba_validator.py`
## Branch: `feature/nkba`
## Design Doc: §9, §11

---

## Goal
Validate all 31 NKBA rules against placed items. Pure math — zero LLM calls.
Return score and violations per variant.

## Input
```python
placement: PlacementEngineOutput
spatial: SpatialEngineOutput
```

## Output
```python
VariantSummaryDTO  # partial — score + violations only (no rationale yet)
```

---

## Class Structure

```python
class NKBAValidator:
    RULE_WEIGHTS = {
        "WORKFLOW-03": 0.15,
        "NKBA-CL-01":  0.10,
        "NKBA-CL-02":  0.10,
        "WORKFLOW-01": 0.10,
        "WORKFLOW-02": 0.10,
        "LAYOUT-01":   0.08,
        "LAYOUT-02":   0.08,
        "LAYOUT-03":   0.08,
        "LAYOUT-04":   0.08,
        "LAYOUT-05":   0.07,
        "LAYOUT-06":   0.06,
    }

    TOTAL_RULES = 31

    def validate(self, placement: PlacementEngineOutput,
                 spatial: SpatialEngineOutput) -> VariantSummaryDTO:
        violations = []
        passed = 0
        items = placement.positioned_items

        # Run all 31 checks
        violations += self._check_project_rules(items, spatial)
        violations += self._check_official_nkba(items, spatial)

        passed = self.TOTAL_RULES - len(violations)
        score = self._compute_score(passed, self.TOTAL_RULES,
                                    len(placement.spillover_log),
                                    len(placement.collision_flags),
                                    [v["rule_id"] for v in violations])

        return VariantSummaryDTO(
            variant_id=placement.variant_id,
            family="",  # filled by zone_planner output merger
            score=score,
            placement_count=len(items),
            nkba_compliance_pct=passed / self.TOTAL_RULES,
            spillover_count=len(placement.spillover_log),
            warnings=placement.spillover_log,
            violations=violations,
            rationale=[],  # filled by Agent 4
            layout={},     # filled by output_generator
            environment={},
        )
```

---

## Score Formula

```python
def _compute_score(self, passed: int, total: int, spillover: int,
                   adjacency: int, violation_ids: list[str]) -> float:
    score = (1.0
             + (passed / total) * 0.30
             - spillover * 0.05
             - adjacency * 0.05
             - sum(self.RULE_WEIGHTS.get(v, 0) for v in violation_ids))
    return max(0.0, min(1.3, score))  # clamp to [0, 1.3]
```

---

## Project Rules (11)

### NKBA-CL-01 — Fridge door swing
```python
fridge = items.get("fridge") or next((v for v in items.values() if "fridge" in v.sku_id.lower()), None)
if fridge:
    # Check 1067mm clear space in front of fridge door
    if clear_space_in_front(fridge, items) < 1067:
        violations.append({"rule_id": "NKBA-CL-01", "message": f"Fridge clearance {clear:.0f}mm < 1067mm"})
```

### NKBA-CL-02 — Door swing reservation
```python
# 900×900mm clear inside door arc
for door in [e for e in spatial.exclusions if e.kind == "door"]:
    if not check_door_arc_clear(door, items, spatial):
        violations.append({"rule_id": "NKBA-CL-02", "message": f"Door arc blocked at {door.id}"})
```

### WORKFLOW-01 — Sink near dishwasher
```python
# DW within 600mm of sink edge
sink = find_item_by_category(items, "sink")
dw   = find_item_by_category(items, "dishwasher")
if sink and dw:
    dist = abs(sink.position_mm["x"] - (dw.position_mm["x"] + dw.dimensions_mm["width"]))
    if dist > 600:
        violations.append({"rule_id": "WORKFLOW-01", "message": f"DW {dist:.0f}mm from sink, max 600mm"})
```

### WORKFLOW-02 — Stove not next to fridge
```python
# >= 600mm gap between stove and fridge
stove  = find_item_by_category(items, "stove")
fridge = find_item_by_category(items, "fridge")
if stove and fridge and same_wall(stove, fridge):
    gap = item_gap(stove, fridge)
    if gap < 600:
        violations.append({"rule_id": "WORKFLOW-02", "message": f"Stove-fridge gap {gap:.0f}mm < 600mm"})
```

### WORKFLOW-03 — Work triangle
```python
# CRITICAL: minimum is 3962mm (13 feet), NOT 3600mm
sink   = find_item_centroid(items, "sink")
stove  = find_item_centroid(items, "stove")
fridge = find_item_centroid(items, "fridge")
if all([sink, stove, fridge]):
    perimeter = (dist(sink, stove) + dist(stove, fridge) + dist(fridge, sink))
    if perimeter < 3962 or perimeter > 6600:
        violations.append({"rule_id": "WORKFLOW-03",
                           "message": f"Work triangle {perimeter:.0f}mm outside 3962–6600mm range"})
```

### LAYOUT-01 — Sink under window
```python
windows_on_cabinet_walls = [e for e in spatial.exclusions if e.kind == "window"]
if windows_on_cabinet_walls and sink:
    nearest_window = min(windows_on_cabinet_walls, key=lambda w: abs(w.offset_mm + w.width_mm/2 - sink_center_x))
    window_center = nearest_window.offset_mm + nearest_window.width_mm / 2
    delta = abs(sink_center_x - window_center)
    if delta > 300:
        violations.append({"rule_id": "LAYOUT-01", "message": f"Sink {delta:.0f}mm from window, max 300mm"})
```

### LAYOUT-02 — Hood above stove
```python
hood  = find_item_by_category(items, "hood")
stove = find_item_by_category(items, "stove")
if hood and stove:
    x_delta = abs((hood.position_mm["x"] + hood.dimensions_mm["width"]/2) -
                  (stove.position_mm["x"] + stove.dimensions_mm["width"]/2))
    if x_delta > 100:
        violations.append({"rule_id": "LAYOUT-02", "message": f"Hood offset {x_delta:.0f}mm from stove, max 100mm"})
```

### LAYOUT-03 — Continuous run
```python
# <= 50mm gap between consecutive items on same wall (door/window gap excepted)
# Group positioned items by anchor_wall
# Sort by x position
# Check gaps between adjacent items
```

### LAYOUT-04 — Base cabinet coverage
```python
# Every appliance must have a base cabinet at its position
```

### LAYOUT-05 — Mandatory base
```python
# Run must terminate at a base cabinet or corner
```

### LAYOUT-06 — Fridge/tall at corner
```python
# Fridge and tall cabinets must be at corners or ends of runs
```

---

## Official NKBA Rules (20)

Implement checks for: NKBA-01 (entry clearance ≥813mm), NKBA-02 (door interference), NKBA-03 (triangle ≤7925mm), NKBA-04 (tall obstacle), NKBA-05 (traffic path), NKBA-06 (work aisle ≥1067mm), NKBA-06b (2-cook aisle ≥1219mm), NKBA-07 (walkway ≥914mm), NKBA-08 (seating clearance), NKBA-10 (sink adjacent to cooktop+fridge), NKBA-11 (sink landing ≥610mm/457mm), NKBA-12 (prep area ≥762×610mm), NKBA-13 (DW within 914mm of sink), NKBA-LA-01 (fridge landing ≥381mm), NKBA-LA-02 (cooktop landing), NKBA-LA-03 (oven landing), NKBA-LA-05 (microwave landing), NKBA-18 (clearance above cooktop ≥610mm), NKBA-19 (ventilation ≥150CFM), NKBA-25 (total countertop ≥4013mm).

---

## Validation
```bash
python -c "
from pipeline.nkba_validator import NKBAValidator
# Test WORKFLOW-03 with perimeter=3962 → should PASS
# Test WORKFLOW-03 with perimeter=3000 → should FAIL
# Test WORKFLOW-03 with perimeter=7000 → should FAIL
# Assert scores are in [0.0, 1.3]
"
```
