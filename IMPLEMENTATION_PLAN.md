# IMPLEMENTATION PLAN
## Auto-Design System | Project 2
## Version: 1.0 | Branch: dev2

---

## Phase Overview

| Phase | Module | Branch | Files |
|-------|--------|--------|-------|
| 0 | Foundation (DTOs + requirements) | feature/dtos | `dtos/contracts.py`, `requirements.txt` |
| 1 | MCP Server | feature/mcp-server | `mcp_server/server.py`, `catalog_loader.py`, `color_resolver.py` |
| 2 | Spatial Engine | feature/spatial-engine | `pipeline/spatial_engine.py` |
| 3 | Agent 1 — Prompt Parser | feature/agent1 | `agents/prompt_parser.py` |
| 4 | Agent 2 — Catalog Selector | feature/agent2 | `agents/catalog_selector.py` |
| 5 | Agent 3 — Layout Strategist | feature/agent3 | `agents/layout_strategist.py` |
| 6 | Placement Engine | feature/placement-engine | `pipeline/placement_engine.py` |
| 7 | NKBA Validator + Scoring | feature/nkba | `pipeline/nkba_validator.py` |
| 8 | Agent 4 + Output Generator | feature/output | `agents/rationale_writer.py`, `pipeline/output_generator.py` |
| 9 | LangGraph Orchestration | feature/graph | `graph/kitchen_graph.py`, `pipeline/preprocessor.py`, `pipeline/zone_planner.py` |
| 10 | Streamlit UI | feature/ui | `ui/app.py`, `ui/components/*.py` |

---

## Phase 0 — Foundation

**Branch:** `feature/dtos`
**Goal:** All DTO dataclasses and project requirements — zero logic, just contracts.

### Files to Create

#### `dtos/contracts.py`
All TypedDict / dataclass definitions:
- `SpatialEngineOutput`
- `PreprocessingOutput`
- `ZonePlannerOutput`
- `PlacementEngineOutput`
- `VariantSummaryDTO`
- `FinalOutput`
- `KitchenGraphState`
- `IntentDTO`
- `Wall`, `Segment`, `Opening`, `SKU`, `PlacedItem`

#### `requirements.txt`
```
anthropic>=0.40.0
langchain-anthropic>=0.3.0
langgraph>=0.2.0
mcp>=1.0.0
streamlit>=1.40.0
matplotlib>=3.8.0
numpy>=1.26.0
colormath>=3.0.0
python-dotenv>=1.0.0
```

#### `dtos/__init__.py` — empty

---

## Phase 1 — MCP Server

**Branch:** `feature/mcp-server`

### `mcp_server/catalog_loader.py`
- Load catalog.json (or catalogId from preferences)
- Apply CATEGORY_ALIASES and PRICE_ALIASES normalization
- Validate all required fields present on every SKU
- Return indexed dict keyed by sku_id

### `mcp_server/color_resolver.py`
- `resolve_color(keyword: str) -> str` — LLM resolves keyword → hex
- `match_catalog_color(hex: str, catalog: dict) -> str` — scan catalog color field within ΔE tolerance
- ΔE tolerance: 15 (lab color space distance)

### `mcp_server/server.py`
Implement all 9 MCP tools:
```python
@mcp.tool()
def get_catalog_items() -> list[dict]: ...

@mcp.tool()
def get_skus_by_category(category: str) -> list[dict]: ...

@mcp.tool()
def get_sku_dimensions(sku_id: str) -> dict: ...

@mcp.tool()
def get_sku_constraints(sku_id: str) -> dict: ...

@mcp.tool()
def get_skus_by_price_tier(tier: str) -> list[dict]: ...

@mcp.tool()
def get_skus_by_style(style: str) -> list[dict]: ...

@mcp.tool()
def resolve_color(keyword: str) -> str: ...

@mcp.tool()
def validate_placement(sku_id: str, wall_length_mm: int) -> dict: ...

@mcp.tool()
def check_clearance(sku_id: str, adjacent_items: list[str]) -> dict: ...
```

---

## Phase 2 — Spatial Engine

**Branch:** `feature/spatial-engine`

### `pipeline/spatial_engine.py`
**Class:** `SpatialEngine`
**Input:** `dict` (raw input JSON)
**Output:** `SpatialEngineOutput`

#### Methods
```python
def parse(self, input_json: dict) -> SpatialEngineOutput:
    walls = self._parse_walls(input_json["environment"]["wall"])
    exclusions = self._parse_openings(input_json["environment"].get("openings", []))
    free_segments = self._compute_free_segments(walls, exclusions)
    flow_order = self._compute_flow_order(walls)
    layout_capacity = self._determine_layout_capacity(walls)
    return SpatialEngineOutput(...)

def _parse_walls(self, wall_data: list) -> list[Wall]:
    # Parse has_cabinets, dimensions, anchor, thickness

def _parse_openings(self, openings: list) -> list[Opening]:
    # Door: footprint + swing arc = total blocked zone
    # Window: base cabinets allowed below sill_mm, wall cabs blocked in front

def _compute_free_segments(self, walls, exclusions) -> dict[str, list[Segment]]:
    # Split each wall into free segments avoiding blocked zones

def _compute_flow_order(self, walls) -> list[str]:
    # Return has_cabinets walls sorted: longest wall first

def _determine_layout_capacity(self, walls) -> str:
    # 1 cabinet wall → "I", 2 adjacent → "L", 3+ → "U"
```

#### Door Blocked Zone Formula
```
door_blocked_start = opening.offset_mm
door_blocked_end = opening.offset_mm + opening.width_mm + opening.width_mm  # footprint + arc
total_blocked = [door_blocked_start, door_blocked_end]
```

#### Window Rules
```
base_cabinet: allowed if cabinet_height_mm <= opening.sill_mm
wall_cabinet: blocked in front of window (within window x range)
sink: attracted to window center ± 300mm (passed as zone context)
```

---

## Phase 3 — Agent 1

**Branch:** `feature/agent1`

### `agents/prompt_parser.py`
**Class:** `PromptParser`
**Model:** `claude-haiku-4-5`

```python
class PromptParser:
    def __init__(self):
        self.client = anthropic.Anthropic()
        self._system = self._build_system_prompt()  # cached

    def parse(self, prompt: str, preferences: dict) -> IntentDTO:
        # Use tool_choice for structured output
        # Never raise — always return best-effort IntentDTO
        # Merge with preferences as fallback
```

**tool_choice schema:**
```json
{
  "name": "extract_intent",
  "input_schema": {
    "type": "object",
    "properties": {
      "color_keyword": {"type": ["string", "null"]},
      "color_hex": {"type": ["string", "null"]},
      "layout_family": {"type": ["string", "null"], "enum": ["L","U","I",null]},
      "style": {"type": ["string", "null"]},
      "cabinet_preference": {"type": ["string", "null"]},
      "special_requests": {"type": "array", "items": {"type": "string"}},
      "ignored": {"type": "array", "items": {"type": "string"}}
    }
  }
}
```

Enable prompt caching on system message (cache_control: {"type": "ephemeral"}).

---

## Phase 4 — Agent 2

**Branch:** `feature/agent2`

### `agents/catalog_selector.py`
**Class:** `CatalogSelector`
**Model:** `claude-haiku-4-5`

```python
class CatalogSelector:
    def __init__(self, mcp_client):
        self.mcp = mcp_client
        self.client = anthropic.Anthropic()

    def select(self, intent: IntentDTO, spatial: SpatialEngineOutput) -> PreprocessingOutput:
        # Run MCP queries with tool_use
        # Group by zone
        # Calculate zone_min_widths
        # Resolve color via resolve_color MCP tool
        # Results are cached (shared across all variants)
```

Zone min-width formulas:
```python
zone_min_widths = {
    "cooling":     catalog[fridge_sku]["width_mm"],
    "cleaning":    catalog[sink_sku]["width_mm"] + catalog[dw_sku]["width_mm"],
    "cooking":     catalog[stove_sku]["width_mm"] + 600,
    "preparation": 900,
    "storage":     sum(catalog[sku]["width_mm"] for sku in base_cabinets)
}
```

---

## Phase 5 — Agent 3

**Branch:** `feature/agent3`

### `agents/layout_strategist.py`
**Class:** `LayoutStrategist`
**Model:** `claude-sonnet-4-6` (retry: `claude-opus-4-7`)

```python
class LayoutStrategist:
    SEEDS = {
        1: "Prefer L-shape. Maximise counter run on the longest wall. Fridge at far end.",
        2: "Prefer U-shape. Close the work triangle tightly. Dishwasher opposite the sink wall.",
        3: "Prefer I-shape or island. Minimise total cabinet cost. Use narrower SKUs where possible.",
        4: "Maximise storage. Prioritise tall cabinets and wall cabinets over base units.",
        5: "Accessibility focus. Maximise aisle widths. No tall cabinets blocking circulation.",
    }

    def plan_variants(self, spatial: SpatialEngineOutput, preprocessing: PreprocessingOutput,
                      n_variants: int = 3, layout_family: str | None = None,
                      retry_context: dict | None = None) -> list[ZonePlannerOutput]:
        # Run n_variants calls in parallel using asyncio.gather
        # Inject seed suffix per variant
        # If layout_family provided (Mode A) → all variants use that shape
        # If layout_family is None (Mode B) → seed determines shape
        # If retry_context provided → use opus, inject violations
```

Mode A vs B logic:
```python
if layout_family:  # Mode A: user specified shape
    seed_suffix = SEEDS[variant_index]  # strategy only, no shape override
    shape_instruction = f"Use {layout_family}-shape for all variants."
else:  # Mode B: seed determines shape
    seed_suffix = SEEDS[variant_index]  # includes shape preference
    shape_instruction = ""
```

Validate output: any term not in semantic vocabulary → replace with "left end of {wall}", log warning.

---

## Phase 6 — Placement Engine

**Branch:** `feature/placement-engine`

### `pipeline/placement_engine.py`
**Class:** `PlacementEngine`
**Input:** `ZonePlannerOutput` + `PreprocessingOutput` + `SpatialEngineOutput`
**Output:** `PlacementEngineOutput`

#### Placement Priority Order
1. **ANCHORED**: sink, fridge, stove (semantic positions resolved to mm)
2. **DEPENDENT**: hood (above stove), dishwasher (next to sink)
3. **FILL**: base cabinets, wall cabinets, tall cabinets (fill free segments)

#### Semantic → Coordinate Resolution
```python
def resolve_position(term: str, wall: Wall, item: SKU, openings: list) -> tuple[float, float, float]:
    match term:
        case _ if "north-west corner" in term: return (0, wall.depth, 0)
        case _ if "north-east corner" in term: return (wall.length - item.width_mm, wall.depth, 0)
        case _ if "near {wall} window" in term: return clamp_to_free_segment(window_center, item, wall)
        # ... etc
```

#### Landing Area Allocator
Zone weights: cooling=1.0, cleaning=1.0, cooking=0.9, prep=0.7, storage=0.4
Reserve counter space before placing items.

#### Spillover Handler
```python
if wall_too_short:
    if adjacent_wall_has_space:
        overflow_to_adjacent()
    else:
        if item.category == "wall_cabinet":
            drop_item()  # log to spillover_log
        elif item.category in ("island",):
            drop_item()
        else:  # appliances, tall cabinets
            log_constraint_violation()
            apply_LAYOUT_06_penalty()
            place_at_nearest_corner_end()
```

#### Collision Detector
3D bounding box overlap check (x, y, z all in mm).
Whitelist pairs (skip these):
- hood + stove
- tap + sink
- wall_cab + base_cab
- dishwasher + base_cab

---

## Phase 7 — NKBA Validator

**Branch:** `feature/nkba`

### `pipeline/nkba_validator.py`
**Class:** `NKBAValidator`
**Input:** `PlacementEngineOutput` + `SpatialEngineOutput`
**Output:** `VariantSummaryDTO` (partial — score + violations, no rationale yet)

#### All 31 Rules (pure math, no LLM)
Project Rules (11): NKBA-CL-01, NKBA-CL-02, WORKFLOW-01, WORKFLOW-02, WORKFLOW-03, LAYOUT-01 through LAYOUT-06
Official NKBA (20): NKBA-01 through NKBA-25 (see design doc §9.2)

#### Score Formula
```python
RULE_WEIGHTS = {
    "WORKFLOW-03": 0.15, "NKBA-CL-01": 0.10, "NKBA-CL-02": 0.10,
    "WORKFLOW-01": 0.10, "WORKFLOW-02": 0.10, "LAYOUT-01": 0.08,
    "LAYOUT-02": 0.08, "LAYOUT-03": 0.08, "LAYOUT-04": 0.08,
    "LAYOUT-05": 0.07, "LAYOUT-06": 0.06,
}

def score(passed, total, spillover, adjacency_violations, violations):
    return (1.0
        + (passed / total) * 0.30
        - spillover * 0.05
        - adjacency_violations * 0.05
        - sum(RULE_WEIGHTS.get(v, 0) for v in violations))
```

#### WORKFLOW-03 Critical Values
- Minimum perimeter: **3962mm** (13 feet — official NKBA)
- Maximum perimeter: 6600mm

---

## Phase 8 — Agent 4 + Output Generator

**Branch:** `feature/output`

### `agents/rationale_writer.py`
**Class:** `RationaleWriter`
**Model:** `claude-haiku-4-5`
Parallel across variants. Input: placement + validation result. Output: rationale[] with rule_id + text.

### `pipeline/output_generator.py`
**Class:** `OutputGenerator`
- Merges rationale into VariantSummaryDTO
- Sorts variants by score descending
- Wraps in FinalOutput with request_id + duration_ms
- Writes output.json
- Calls render.py via subprocess for each variant

---

## Phase 9 — LangGraph Orchestration

**Branch:** `feature/graph`

### `graph/kitchen_graph.py`
Build the StateGraph using KitchenGraphState.

#### Node Map
```
spatial_node → preprocessing_node → zone_planner_node (parallel)
             ↓                                    ↓
      conditional_edge ← nkba_validator_node ← placement_node (parallel)
             ↓ (if retry needed)
      zone_planner_node (opus retry)
             ↓
      output_generator_node → END
```

#### Conditional Edge Logic
```python
def should_retry(state: KitchenGraphState) -> str:
    for v in state["validated_variants"]:
        if (v.score < 0.60 or
            "WORKFLOW-03" in [x["rule_id"] for x in v.violations] or
            "NKBA-CL-01" in [x["rule_id"] for x in v.violations]):
            return "retry"
    return "output"
```

#### `pipeline/preprocessor.py`
Orchestrates Agent 1 → MCP → Agent 2 sequentially.

#### `pipeline/zone_planner.py`
Orchestrates parallel Agent 3 calls via asyncio.gather.

---

## Phase 10 — Streamlit UI

**Branch:** `feature/ui`

### Design
Dark navy background: `#0D1117`
Teal accent: `#00D4B1`
Score badges: green `#38A169` (>0.8), amber `#D69E2E` (0.6–0.8), red `#E53E3E` (<0.6)
Zone colors: Cooking=`#E53E3E`, Cleaning=`#00D4B1`, Cooling=`#3182CE`, Prep=`#D69E2E`, Storage=`#718096`

### `ui/app.py`
4 tabs:
1. **Homeowner** — room selector (3 cards), prompt, budget, generate button, variant cards with score badges, 2D/3D toggle
2. **Kitchen Designer** — variants side-by-side, zone breakdown, work triangle measurement, item coordinate table
3. **Catalog Manager** — MCP status, catalog info, 9 tool list, live tool log, SKU swatches
4. **Design Reviewer** — NKBA checklist (✅/⚠️/❌), score breakdown, full rationale, variant comparison

### `ui/components/room_picker.py`
3 room cards: input1 (3600×3200mm, no openings), input2 (42000×42000mm, no openings), input3 (4200×3000mm, door+windows)

### `ui/components/pipeline_log.py`
Live progress per stage with spinner + elapsed time display.

### `ui/components/variant_card.py`
Score badge + family label + 2D/3D PNG toggle + "Open Interactive 3D" button (calls render.py --show).

### `ui/components/nkba_checklist.py`
Full 31-rule checklist, color-coded pass/warn/fail per variant.

---

## Feature Branch Naming Convention
```
git checkout dev2
git checkout -b feature/<phase-name>
# implement
git add <files>
git commit -m "feat(<phase>): <description>"
git push -u origin feature/<phase-name>
gh pr create --base dev2 --title "feat: <description>" --body "Implements design doc §<section>"
```
