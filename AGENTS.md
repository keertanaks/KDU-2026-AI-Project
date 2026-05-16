# AGENTS.md — Agent Specifications
## Auto-Design System | Project 2

---

## Coding Standards for All Agents

Before writing any agent file read `CODING_STANDARDS.md`. Agent-specific rules:

1. **Never hard-code model strings.** Use `from utils.model_selector import for_agent`.
   ```python
   model = for_agent("prompt_parser")       # → "claude-haiku-4-5"
   model = for_agent("layout_strategist")   # → "claude-sonnet-4-6"
   model = for_agent("layout_strategist", is_retry=True)  # → "claude-opus-4-7"
   ```

2. **Every API call is wrapped in try/except.** On failure return an empty valid DTO — never raise.

3. **All agents use prompt caching** on their static system message:
   ```python
   {"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}
   ```

4. **All agents use `tool_choice`** for structured output — never parse free text from the model.

5. **Agents are plain Python classes** — not services, not daemons, not separate processes.
   LangGraph calls them as normal async functions. They only know about their own input/output DTOs.

6. **Full type annotations required.** Use `from __future__ import annotations`.

7. **Logging:** `from utils.logger import get_logger` — `logger = get_logger(__name__)`.

---

## Agent 1 — Prompt Parser
**File:** `agents/prompt_parser.py`
**Model:** `claude-haiku-4-5`
**Type:** Sequential (runs once per request)
**Input:** Raw user prompt string + input JSON preferences
**Output:** `IntentDTO` (structured JSON via tool_choice)

### Rules
- NEVER return `valid: false` — always extract best effort
- If nothing found → return nulls, use input JSON defaults
- NEVER block generation under any circumstances
- Extract kitchen parts only, log non-kitchen requests in `"ignored"`
- Always use `tool_choice` for structured JSON output

### System Prompt Core
```
ROLE:    Kitchen design intent extractor
TASK:    Extract structured information from user prompt
RULES:   Never return valid:false — always extract best effort
         If nothing found → return nulls, use input JSON defaults
         Never block generation under any circumstances
         Extract kitchen parts only, log non-kitchen requests in "ignored"
OUTPUT:  Strict JSON schema via tool_choice
```

### Output Schema
```json
{
  "color_keyword": "navy blue | null",
  "color_hex": "#1F3A5F | null",
  "layout_family": "L | U | I | null",
  "style": "modern | traditional | minimalist | null",
  "cabinet_preference": "base_only | with_uppers | with_tall | null",
  "special_requests": ["island", "pantry"],
  "ignored": ["AC", "TV"]
}
```

### Prompt Caching
Cache: system prompt + NKBA rule list (static across requests)
Do NOT cache: user input (unique per request)

---

## Agent 2 — Catalog Selector
**File:** `agents/catalog_selector.py`
**Model:** `claude-haiku-4-5`
**Type:** Sequential (runs once, results shared across all variants)
**Input:** `IntentDTO` + MCP tools
**Output:** `PreprocessingOutput` (skus, zone_groups, zone_min_widths, nkba_constraints)

### Rules
- NEVER invent a SKU — only use what MCP returns
- MCP runs ONCE — results cached for all variants
- Group selected SKUs by zone type
- Calculate zone_min_widths from SKU dimensions
- Include relevant NKBA constraints per zone

### MCP Tools Available
| Tool | Purpose |
|------|---------|
| `get_catalog_items()` | List all SKUs |
| `get_skus_by_category(category)` | Filter by type |
| `get_sku_dimensions(sku_id)` | width_mm, depth_mm, height_mm |
| `get_sku_constraints(sku_id)` | front_clearance_mm, needs_water, needs_power |
| `get_skus_by_price_tier(tier)` | Filter by low/mid/high |
| `get_skus_by_style(style)` | Filter by modern/traditional/minimalist |
| `resolve_color(keyword)` | keyword → hex → catalog match |
| `validate_placement(sku_id, wall_length_mm)` | Fit + NKBA check |
| `check_clearance(sku_id, adjacent_items)` | front_clearance_mm check |

### Prompt Caching
Cache: system prompt + full catalog JSON (largest cache, biggest saving)

---

## Agent 3 — Layout Strategist
**File:** `agents/layout_strategist.py`
**Model:** `claude-sonnet-4-6` primary / `claude-opus-4-7` on retry
**Type:** Parallel × 3–5 variants
**Input:** `SpatialEngineOutput` + `PreprocessingOutput` + variant seed suffix
**Output:** `ZonePlannerOutput` (variant_id, family, wall_strategies, zone_assignments)

### HARD CONSTRAINT
**Agent 3 MUST NEVER output coordinates, mm values, or any numbers.**
**Output is semantic only — using ONLY the vocabulary below.**

### Valid Semantic Vocabulary
| Term | Meaning |
|------|---------|
| `"at north-west corner"` | x=0, y=wall_depth |
| `"at north-east corner"` | x=wall_length-item_width, y=wall_depth |
| `"at south-west corner"` | x=0, y=0 |
| `"at south-east corner"` | x=wall_length-item_width, y=0 |
| `"near {wall} window"` | x=window_center ± item_width/2 |
| `"centre of {wall}"` | x=(wall_length-item_width)/2 |
| `"left end of {wall}"` | x=0 (start of first free segment) |
| `"right end of {wall}"` | x=wall_length-item_width |
| `"next to {item_name}"` | immediately adjacent, no gap |
| `"above {item_name}"` | z=item.z+item.height, same x/y |
| `"leave gap before {item_name}"` | 600mm buffer before item |

Unrecognised term → fall back to `"left end of {wall}"`, log warning.

### Placement Strategy Rules
- Fridge and tall cabinets ALWAYS at corners/ends
- Sink near window if window exists on that wall
- Dishwasher next to sink (expressed as `"next to sink"`)
- Hood above stove (expressed as `"above stove"`)
- Stove ≥ 600mm from fridge (expressed as `"leave gap before fridge"`)

### Variant Seeds
| Variant | Injected Suffix |
|---------|----------------|
| 1 | "Prefer L-shape. Maximise counter run on the longest wall. Fridge at far end." |
| 2 | "Prefer U-shape. Close the work triangle tightly. Dishwasher opposite the sink wall." |
| 3 | "Prefer I-shape or island. Minimise total cabinet cost. Use narrower SKUs where possible." |
| 4 | "Maximise storage. Prioritise tall cabinets and wall cabinets over base units." |
| 5 | "Accessibility focus. Maximise aisle widths. No tall cabinets blocking circulation." |

### Retry Trigger (LangGraph conditional edge)
Retry if: score < 0.60 OR WORKFLOW-03 violated OR NKBA-CL-01 violated
On retry: Agent 3 receives violation list as context → re-plans with `claude-opus-4-7`
If retry also fails: keep variant, mark `warnings[]`, do NOT drop variant

### Prompt Caching
Cache: system prompt + room geometry template
Do NOT cache: variant-specific seed suffix or violation context

---

## Agent 4 — Rationale Writer
**File:** `agents/rationale_writer.py`
**Model:** `claude-haiku-4-5`
**Type:** Parallel × variants (runs after NKBA scoring)
**Input:** `PlacementEngineOutput` + NKBA validation result + IntentDTO
**Output:** `rationale[]` array — each entry has `rule_id` and `text`

### Rules
- Reference NKBA rule IDs explicitly (e.g., LAYOUT-01, WORKFLOW-03)
- Confirm color match to prompt, flag violations in plain English
- Keep each rationale entry to 1–2 sentences
- Always run even if violations exist — explain them, don't hide them

### Output Schema
```json
[
  {"rule_id": "LAYOUT-01", "text": "Sink centred under north window (delta=0mm)"},
  {"rule_id": "COLOR-MATCH", "text": "SKU-C11 (#1F3A5F) selected for navy blue prompt"},
  {"rule_id": "WORKFLOW-03", "text": "Work triangle perimeter: 4200mm (within 3962–6600mm)"}
]
```

### Prompt Caching
Cache: system prompt + rationale templates
Do NOT cache: placement result or violations (unique per variant)
