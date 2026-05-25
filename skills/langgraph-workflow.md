---
name: langgraph-workflow
description: Use when adding pipeline nodes, changing graph routing, extending KitchenGraphState, wiring retry edges, or adding parallel branches to graph/kitchen_graph.py.
version: 1.0.1
last_verified: 2026-05-24
applies_to:
  - graph/kitchen_graph.py
  - dtos/contracts.py
  - pipeline/*.py
tool_risk: high
---

# LangGraph Workflow Skill

## Purpose
Ensure new pipeline steps are properly wired into `graph/kitchen_graph.py` and that `KitchenGraphState` changes are defined before node code is written.

## When to Use
Any feature that adds a new pipeline step, changes routing, adds parallel branches, or modifies how state flows between nodes.

## Existing Repo Pattern

**`graph/kitchen_graph.py`** uses LangGraph `StateGraph` with `START`/`END` imports from `langgraph.graph`.

**`KitchenGraphState`** (TypedDict defined in `dtos/contracts.py`):
```python
class KitchenGraphState(TypedDict):
    input_json:            dict
    spatial_output:        SpatialEngineOutput
    preprocessing_output:  PreprocessingOutput
    variants:              list[ZonePlannerOutput]
    placed_variants:       list[PlacementEngineOutput]
    validated_variants:    list[VariantSummaryDTO]
    retry_context:         dict[str, list[str]]
    final_output:          FinalOutput
```

**Sequential** (Layer 1 → Layer 2): `spatial_engine` node → `preprocessor` node
**Parallel** (per variant): `zone_planner`, `placement_engine`, `nkba_validator`, `output_generator` each run as parallel branches via `asyncio.gather` inside their respective nodes.
**Retry edge**: conditional edge from `nkba_validator` back to `zone_planner` if score < 0.60 OR WORKFLOW-03 OR NKBA-CL-01 violated; uses `should_use_opus(score, violation_ids)` from `utils/model_selector.py`.

## Rules
1. **Define `KitchenGraphState` changes FIRST** in `dtos/contracts.py` before writing node code
2. **Every new pipeline step must be wired into `kitchen_graph.py`** — never leave a module disconnected
3. **Graph orchestration logic must NOT live in UI files, utility files, or pipeline modules** — only in `graph/kitchen_graph.py`
4. **New nodes must handle their own exceptions** — API errors return fallback DTOs, never propagate as unhandled exceptions into graph state
5. **Retry must use `should_use_opus()` from `utils/model_selector.py`** — no hardcoded model strings in graph code

## Bad Example
```python
# WRONG — new accessibility advisor runs outside the graph
# (in ui/app.py)
async def run_pipeline(input_json):
    ...
    report = await accessibility_advisor.analyze(variants)  # bypasses graph
    return report

# WRONG — hardcoded model in graph node
model = "claude-opus-4-7"  # should use should_use_opus()
```

## Good Example
```python
# CORRECT — new node registered in kitchen_graph.py
graph.add_node("accessibility_advisor", _accessibility_advisor_node)
graph.add_edge("nkba_validator", "accessibility_advisor")
graph.add_edge("accessibility_advisor", "output_generator")

# CORRECT — model selection via utility with proper signature
from utils.model_selector import for_agent, should_use_opus
model = for_agent("accessibility_advisor")
if should_use_opus(state["validated_variants"][0].score, state["retry_context"].get("violations", [])):
    model = for_agent("accessibility_advisor", is_retry=True)
```

## Common Failure Modes
- New module written but not added as a graph node → runs in isolation, not part of pipeline
- `KitchenGraphState` modified in node code (dict mutation) instead of defined in `dtos/contracts.py`
- Retry edge added without `should_use_opus()` check → always uses Sonnet, never escalates

## Must Not Do
- Never add a new pipeline step outside the graph
- Never modify `KitchenGraphState` without updating `dtos/contracts.py` first
- Never hardcode model strings in `kitchen_graph.py`

## Completion Checklist
- [ ] `KitchenGraphState` changes defined in `dtos/contracts.py` before writing node code
- [ ] New pipeline step is a registered graph node
- [ ] New node handles exceptions and returns valid DTOs
- [ ] Retry edges use `should_use_opus()` from `utils/model_selector.py`
- [ ] No orchestration logic in UI, utils, or pipeline modules
