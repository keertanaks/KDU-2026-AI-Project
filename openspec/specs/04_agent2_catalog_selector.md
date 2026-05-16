# OpenSpec: Agent 2 — Catalog Selector
## File: `agents/catalog_selector.py`
## Branch: `feature/agent2`
## Design Doc: §5.2, §7.2

---

## Goal
Select the right SKUs from the catalog via MCP tools based on intent and spatial constraints.
Results are cached and shared across ALL variants (MCP runs once per request).

## Model
`claude-haiku-4-5`

## Input
```python
intent: IntentDTO
spatial: SpatialEngineOutput
mcp_session: ClientSession  # active MCP session
```

## Output
```python
PreprocessingOutput  # from dtos.contracts
```

---

## Class Structure

```python
from mcp import ClientSession
from dtos.contracts import PreprocessingOutput, SKU, IntentDTO, SpatialEngineOutput
import anthropic

class CatalogSelector:
    MODEL = "claude-haiku-4-5"

    def __init__(self, mcp_session: ClientSession):
        self.mcp = mcp_session
        self.client = anthropic.Anthropic()

    async def select(self, intent: IntentDTO, spatial: SpatialEngineOutput) -> PreprocessingOutput:
        # Use Claude with MCP tools to select SKUs
        # Run tool loop until model stops calling tools
        # Group by zone
        # Calculate zone_min_widths
        # Return PreprocessingOutput
```

---

## MCP Tool Loop Pattern

```python
async def select(self, intent: IntentDTO, spatial: SpatialEngineOutput) -> PreprocessingOutput:
    tools = await self.mcp.list_tools()
    messages = [{"role": "user", "content": self._build_prompt(intent, spatial)}]

    while True:
        response = self.client.messages.create(
            model=self.MODEL,
            max_tokens=2000,
            system=[{"type": "text", "text": self._system, "cache_control": {"type": "ephemeral"}}],
            tools=tools,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            break

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = await self.mcp.call_tool(block.name, block.input)
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(result)})

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    return self._parse_selection(response, intent, spatial)
```

---

## Zone Min-Width Formulas

After SKU selection, compute zone_min_widths:
```python
def _compute_zone_min_widths(self, skus: dict[str, SKU], zone_groups: dict) -> dict[str, float]:
    fridge = next((s for s in zone_groups.get("cooling", []) if "fridge" in s.name.lower()), None)
    sink   = next((s for s in zone_groups.get("cleaning", []) if "sink" in s.name.lower()), None)
    dw     = next((s for s in zone_groups.get("cleaning", []) if "dishwasher" in s.name.lower()), None)
    stove  = next((s for s in zone_groups.get("cooking", []) if "stove" in s.name.lower() or "range" in s.name.lower()), None)
    base_cabs = zone_groups.get("storage", [])

    return {
        "cooling":     fridge.width_mm if fridge else 600,
        "cleaning":    (sink.width_mm if sink else 600) + (dw.width_mm if dw else 600),
        "cooking":     (stove.width_mm if stove else 600) + 600,
        "preparation": 900,
        "storage":     sum(s.width_mm for s in base_cabs) if base_cabs else 1800,
    }
```

---

## Color Resolution

If intent.color_hex is set, call resolve_color MCP tool to find the nearest catalog match:
```python
if intent.color_hex:
    color_result = await self.mcp.call_tool("resolve_color", {"keyword": intent.color_keyword or intent.color_hex})
    # Apply matched color to all base cabinets in selection
```

---

## Rules
- NEVER invent a SKU — only use what the MCP tools return
- If must_have item not found in budget tier → try adjacent tier (mid → high if needed)
- If avoid list conflicts with must_have → must_have wins, log warning
- All selections cached — do NOT call MCP tools again for individual variants

---

## Validation
```bash
python -c "
import asyncio
from mcp import ClientSession, StdioServerParameters
from agents.catalog_selector import CatalogSelector
from dtos.contracts import IntentDTO

intent = IntentDTO(color_keyword='navy blue', color_hex='#1F3A5F',
                   layout_family=None, style='modern', cabinet_preference=None,
                   special_requests=['dishwasher', 'hood'], ignored=[])

# Test with running MCP server
# Expected: PreprocessingOutput with at least 5 SKUs, zone_groups populated
"
```
