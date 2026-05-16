# OpenSpec: DTOs and Data Contracts
## File: `dtos/contracts.py`
## Branch: `feature/dtos`

---

## Goal
Define ALL TypedDict / dataclass definitions used across the entire pipeline.
This file is imported by every other module. It must be complete before any other phase.

## Do NOT
- Include any logic, math, or LLM calls
- Import from pipeline/, agents/, or mcp_server/

## Imports Required
```python
from __future__ import annotations
from typing import TypedDict, Any
from dataclasses import dataclass, field
```

## Definitions to Implement

### Primitive DTOs

```python
@dataclass
class Wall:
    name: str                  # "north_wall", "south_wall", etc.
    anchor: str                # "north" | "south" | "east" | "west"
    length_mm: float
    height_mm: float
    thickness_mm: float
    has_cabinets: bool
    points: list[dict]

@dataclass
class Segment:
    start_mm: float
    end_mm: float

    @property
    def length_mm(self) -> float:
        return self.end_mm - self.start_mm

@dataclass
class Opening:
    id: str
    kind: str                  # "door" | "window"
    wall: str                  # anchor name
    offset_mm: float
    width_mm: float
    height_mm: float
    sill_mm: float             # 0 for doors
    blocked_start_mm: float    # computed: includes swing arc for doors
    blocked_end_mm: float      # computed

@dataclass
class SKU:
    sku_id: str
    name: str
    category: str
    width_mm: float
    depth_mm: float
    height_mm: float
    color: str                 # hex
    price_tier: str
    style: list[str]
    front_clearance_mm: float
    needs_water: bool
    needs_power: bool
    must_attach_to: str

@dataclass
class PlacedItem:
    sku_id: str
    name: str
    category: str
    position_mm: dict          # {"x": float, "y": float, "z": float}
    dimensions_mm: dict        # {"width": float, "depth": float, "height": float}
    rotation_z_deg: float
    anchor_wall: str
    zone_type: str

@dataclass
class IntentDTO:
    color_keyword: str | None
    color_hex: str | None
    layout_family: str | None  # "L" | "U" | "I" | None
    style: str | None
    cabinet_preference: str | None
    special_requests: list[str]
    ignored: list[str]
```

### Pipeline DTOs

```python
@dataclass
class SpatialEngineOutput:
    walls: list[Wall]
    free_segments: dict[str, list[Segment]]    # wall_name → segments
    flow_order: list[str]                       # wall names, longest first
    exclusions: list[Opening]
    layout_capacity: str                        # "L" | "U" | "I"

@dataclass
class PreprocessingOutput:
    intent: IntentDTO
    skus: dict[str, SKU]                        # sku_id → SKU
    zone_groups: dict[str, list[SKU]]           # zone → SKUs
    zone_min_widths: dict[str, float]           # zone → mm
    nkba_constraints: dict                      # rule_id → value

@dataclass
class ZonePlannerOutput:
    variant_id: str
    family: str                                 # "L" | "U" | "I"
    wall_strategies: dict[str, list[str]]       # wall_name → [semantic terms]
    zone_assignments: dict[str, str]            # zone → wall_name

@dataclass
class PlacementEngineOutput:
    variant_id: str
    positioned_items: dict[str, PlacedItem]    # item_name → PlacedItem
    spillover_log: list[str]
    collision_flags: list[str]

@dataclass
class VariantSummaryDTO:
    variant_id: str
    family: str
    score: float
    placement_count: int
    nkba_compliance_pct: float
    spillover_count: int
    warnings: list[str]
    violations: list[dict]                      # [{"rule_id": str, "message": str}]
    rationale: list[dict]                       # [{"rule_id": str, "text": str}]
    layout: dict                                # render.py-compatible layout dict
    environment: dict                           # passthrough from input

@dataclass
class FinalOutput:
    request_id: str
    duration_ms: float
    layouts: list[VariantSummaryDTO]
```

### LangGraph State

```python
class KitchenGraphState(TypedDict):
    input_json:            dict
    spatial_output:        SpatialEngineOutput
    preprocessing_output:  PreprocessingOutput
    variants:              list[ZonePlannerOutput]
    placed_variants:       list[PlacementEngineOutput]
    validated_variants:    list[VariantSummaryDTO]
    retry_context:         dict[str, list[str]]        # variant_id → violations[]
    final_output:          FinalOutput
```

## Validation
After writing:
```bash
python -c "from dtos.contracts import KitchenGraphState, FinalOutput, VariantSummaryDTO; print('OK')"
```
Must print `OK` with zero import errors.
