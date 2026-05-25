---
name: dto-contracts
description: Use when adding new fields to DTOs, creating new DTOs, extending KitchenGraphState, or passing data between pipeline stages. dtos/contracts.py is the single source of truth for all inter-module data contracts.
version: 1.0.0
last_verified: 2026-05-24
applies_to:
  - dtos/contracts.py
  - graph/kitchen_graph.py
  - pipeline/*.py
  - agents/*.py
tool_risk: high
---

# DTO Contracts Skill

## Purpose
Ensure all data crossing module boundaries uses typed DTOs from `dtos/contracts.py`. No loose dicts between stages. `KitchenGraphState` changes defined before node code.

## When to Use
Any feature that adds new data to the pipeline, changes what one layer passes to the next, or needs to carry new context through the graph.

## Existing Repo Pattern

**`dtos/contracts.py`** contains (non-exhaustive):
- `Wall`, `Segment`, `Opening` — spatial primitives
- `SKU` — catalog item with `id`, `name`, `width_mm`, `depth_mm`, `height_mm`, `price_tier`, `style`, `color_hex`, `category`
- `IntentDTO` — Agent 1 output: color_keyword, layout_family, style, cabinet_preference, special_requests
- `SpatialEngineOutput`, `PreprocessingOutput`, `ZonePlannerOutput`, `PlacementEngineOutput`, `PlacedItem`
- `VariantSummaryDTO` — post-validation: variant_id, score, violations, warnings, rationale, placed_items
- `FinalOutput` — top-level pipeline output
- `KitchenGraphState` — TypedDict used by LangGraph

**Pattern**: all dataclasses are `@dataclass`, value objects use `frozen=True`. `TypedDict` for `KitchenGraphState`.

## Rules
1. **Define `KitchenGraphState` additions FIRST** in `dtos/contracts.py` before writing any node code
2. **Never pass loose dicts between pipeline stages** when a DTO exists
3. **Never duplicate DTO definitions** in other files — always import from `dtos/contracts.py`
4. **New DTOs are dataclasses** — not Pydantic models, not plain dicts
5. **Breaking changes to DTOs** (removing fields, changing types) require an ADR and all callers updated in the same PR
6. **Full type annotations always** on all DTO fields — use `from __future__ import annotations`

## Bad Example
```python
# WRONG — loose dict between stages
def run_placement(zone_plan: dict, ...) -> dict:
    ...

# WRONG — duplicate DTO in wrong file
# (in pipeline/output_generator.py)
@dataclass
class VariantSummary:  # duplicates VariantSummaryDTO from dtos/contracts.py
    score: float
    ...
```

## Good Example
```python
# CORRECT — typed DTOs at every boundary
def run(
    zone_plan: ZonePlannerOutput,
    preprocessing: PreprocessingOutput,
    spatial: SpatialEngineOutput,
) -> PlacementEngineOutput:
    ...

# CORRECT — extend KitchenGraphState in dtos/contracts.py first
class KitchenGraphState(TypedDict):
    ...
    accessibility_report: AccessibilityReportDTO | None  # new field
```

## Common Failure Modes
- New graph node needs data but it's not in `KitchenGraphState` → node reads stale state
- Feature adds a dict field to `PlacementEngineOutput` instead of creating a typed DTO
- Two modules define similar dataclasses independently → schema drift between modules

## Must Not Do
- Never pass `dict[str, Any]` across module boundaries when a DTO covers the use case
- Never define a DTO outside `dtos/contracts.py`
- Never add mutable default values (use `field(default_factory=list)` for lists)

## Completion Checklist
- [ ] All new inter-module data uses DTOs from `dtos/contracts.py`
- [ ] `KitchenGraphState` additions defined in `dtos/contracts.py` before node code written
- [ ] No duplicate DTO definitions in other files
- [ ] All DTO fields fully typed
- [ ] No breaking changes without ADR and full caller update
