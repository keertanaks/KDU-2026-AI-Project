# CLAUDE.md — Auto-Design System (Project 2)
## Read this before touching any file.

---

## NEVER MODIFY THESE FILES
- `render.py` — existing renderer, provided by project spec
- `layout.py` — existing visualizer, provided by project spec
- `catalog.json` — source of truth catalog
- `input1.json`, `input2.json`, `input3.json` — test inputs
- `output.json` — reference example

---

## Architecture: 5-Layer Pipeline

```
input.json → Layer 1 (Spatial Engine) → Layer 2 (Preprocessing: Agent1 + MCP + Agent2)
           → Layer 3 (Zone Planner: Agent3 ×3–5 parallel)
           → Layer 4 (Placement Engine ×3–5 parallel)
           → NKBA Validator ×3–5 parallel
           → Layer 5 (Output Generator: Agent4 ×3–5 parallel)
           → output.json + PNGs → Streamlit UI
```

Sequential: Layer 1 → Layer 2
Parallel: Layer 3, 4, NKBA Validator, Agent 4, Renderer — all per-variant, all parallel

---

## Models
- Agent 1 (Prompt Parser): `claude-haiku-4-5`
- Agent 2 (Catalog Selector): `claude-haiku-4-5`
- Agent 3 (Layout Strategist): `claude-sonnet-4-6` primary / `claude-opus-4-7` on retry
- Agent 4 (Rationale Writer): `claude-haiku-4-5`

Retry trigger: score < 0.60 OR WORKFLOW-03 violated OR NKBA-CL-01 violated
On retry: Agent 3 re-plans with claude-opus-4-7. If retry also fails: keep variant, add warnings[].

---

## LangGraph State

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

Define KitchenGraphState FIRST before writing any LangGraph nodes.

---

## Agent 3 Semantic Vocabulary (ONLY these terms allowed)

| Term | Placement Engine Action |
|------|------------------------|
| `"at north-west corner"` | x=0, y=wall_depth |
| `"at north-east corner"` | x=wall_length-item_width, y=wall_depth |
| `"at south-west corner"` | x=0, y=0 |
| `"at south-east corner"` | x=wall_length-item_width, y=0 |
| `"near {wall} window"` | x=window_center ± item_width/2, clamped to free segment |
| `"centre of {wall}"` | x=(wall_length-item_width)/2 |
| `"left end of {wall}"` | x=0 (start of first free segment) |
| `"right end of {wall}"` | x=wall_length-item_width |
| `"next to {item_name}"` | placed immediately adjacent to named item |
| `"above {item_name}"` | z=named_item.z+named_item.height, same x/y centred |
| `"leave gap before {item_name}"` | 600mm buffer before named item |

Unrecognised term → fall back to `"left end of {wall}"`, log warning.

---

## Variant Seed Differentiation

| Variant | Injected Strategy Suffix |
|---------|--------------------------|
| 1 | "Prefer L-shape. Maximise counter run on the longest wall. Fridge at far end." |
| 2 | "Prefer U-shape. Close the work triangle tightly. Dishwasher opposite the sink wall." |
| 3 | "Prefer I-shape or island. Minimise total cabinet cost. Use narrower SKUs where possible." |
| 4 | "Maximise storage. Prioritise tall cabinets and wall cabinets over base units." |
| 5 | "Accessibility focus. Maximise aisle widths. No tall cabinets blocking circulation." |

Mode A (user specified shape) → all variants use that shape, seed strategy only changes zone/item placement.
Mode B (layout_family=null) → seed determines shape as above.

---

## Collision Whitelist (not flagged as errors)
- `hood ↔ stove` (z-axis: hood above stove)
- `tap ↔ sink` (tap is sub-item of sink unit)
- `wall_cab ↔ base_cab` (z-axis: upper above lower)
- `dishwasher ↔ base_cab` (integrated panel, shared x boundary)

---

## Spillover Priority
wall_cabinet → island → NEVER drop appliances or tall cabinets
Tall cabinets: never dropped. If cannot fit → log constraint_violation + LAYOUT-06 penalty, place at nearest corner/end.

---

## Scoring Formula
```
SCORE = 1.0
+ (passed_NKBA / total_NKBA) × 0.30
- (spillover_count × 0.05)
- (adjacency_violations × 0.05)
- sum(RULE_WEIGHTS[v] for v in violations)
```

---

## All Coordinates in mm
Consistent with catalog.json, render.py, and NKBA measurements.

---

## NKBA WORKFLOW-03 Corrected Value
Work triangle: 3962–6600mm (NOT 3600mm — 3962mm = 13 feet, official NKBA minimum)

---

## File Structure
```
agents/
  prompt_parser.py      Agent 1 (Haiku)
  catalog_selector.py   Agent 2 (Haiku + MCP)
  layout_strategist.py  Agent 3 (Sonnet / Opus fallback)
  rationale_writer.py   Agent 4 (Haiku)
mcp_server/
  server.py             9 MCP tool definitions
  catalog_loader.py     normalization + alias maps
  color_resolver.py     hex matching logic
pipeline/
  spatial_engine.py     Layer 1
  preprocessor.py       Layer 2
  zone_planner.py       Layer 3
  placement_engine.py   Layer 4
  nkba_validator.py     All 31 rules + scoring
  output_generator.py   Layer 5
graph/
  kitchen_graph.py      LangGraph state graph
dtos/
  contracts.py          All DTO dataclasses
ui/
  app.py                Main Streamlit app (4 persona tabs, dark theme)
  components/
    room_picker.py
    pipeline_log.py
    variant_card.py
    nkba_checklist.py
```

---

## UI Theme
Dark navy background (#0D1117), teal accents (#00D4B1), score colors: green >0.8, amber 0.6–0.8, red <0.6.
Zone colors: Cooking=#E53E3E, Cleaning=#00D4B1, Cooling=#3182CE, Prep=#D69E2E, Storage=#718096.

---

## Coding Standards
Read `CODING_STANDARDS.md` before writing any code. Key rules:
- Full type annotations on every function signature (`from __future__ import annotations`)
- No `print()` — use `utils.logger.get_logger(__name__)`
- All thresholds as named constants (no bare numbers in logic)
- All Claude API calls in try/except returning a valid fallback DTO
- Modules max ~400 lines. Functions max ~60 lines.
- Run `ruff format . && ruff check . && mypy .` before every commit

## Model Selection — `utils/model_selector.py`
**Never hard-code model strings in agent files.** Always use:
```python
from utils.model_selector import for_agent, should_use_opus
model = for_agent("layout_strategist")            # → "claude-sonnet-4-6"
model = for_agent("layout_strategist", is_retry=True)  # → "claude-opus-4-7"
```
Summary of assignments:
- Haiku: prompt_parser, catalog_selector, rationale_writer (fast extraction + text gen)
- Sonnet: layout_strategist primary (spatial reasoning — default workhorse)
- Opus: layout_strategist retry ONLY, when score < 0.60 OR WORKFLOW-03 OR NKBA-CL-01 violated

## What "Agents" Actually Are
There are no separate agent services or processes. "Agents" are plain Python classes in `agents/`
that call the Anthropic API (SDK) with a specific system prompt and tool schema.
LangGraph is the orchestrator that connects them into a pipeline with state, parallel branches,
and conditional retry edges. You write normal Python — LangGraph handles the wiring.

## Tests
- `tests/unit/` — pure-code modules (spatial, placement, nkba, model_selector). No mocks for math.
- `tests/integration/` — full pipeline. Real API. Marked `@pytest.mark.integration`.
- Run units: `pytest tests/unit/ -v`
- Run integration: `pytest tests/integration/ -v -m integration`

## Git Workflow
main → dev2 → feature/* → PR back to dev2 → merge to main at end.
One feature branch per module. PR message must reference design doc section.
All 3 linting checks must pass before PR is opened.
