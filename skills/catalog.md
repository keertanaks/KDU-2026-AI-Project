---
name: catalog
description: Use when writing any code that retrieves SKUs, queries catalog data, filters by category/price/style, resolves dimensions, or handles budget/cost features. Covers both retrieval patterns and catalog governance rules.
version: 1.0.0
last_verified: 2026-05-24
applies_to:
  - mcp_server/server.py
  - mcp_server/catalog_loader.py
  - agents/catalog_selector.py
  - tests/unit/test_*.py
  - tests/fixtures/sample_inputs.py
tool_risk: medium
---

# Catalog Skill

## Purpose
Govern all access to `catalog.json` via the MCP server abstraction, and enforce SKU integrity across agents, pipeline, and tests.

## When to Use
Any time code retrieves items from the catalog, filters by category/style/price, validates SKU dimensions, or implements a budget/cost feature.

## Existing Repo Pattern

**MCP tools available in `mcp_server/server.py`:**
| Tool | Purpose |
|------|---------|
| `get_catalog_items()` | All SKUs |
| `get_skus_by_category(category)` | Filter by type (e.g., "base_cabinet", "refrigerator") |
| `get_sku_dimensions(sku_id)` | width_mm, depth_mm, height_mm |
| `get_sku_constraints(sku_id)` | front_clearance_mm, needs_water, needs_power |
| `get_skus_by_price_tier(tier)` | "low", "mid", "high" |
| `get_skus_by_style(style)` | "modern", "traditional", "minimalist" |
| `resolve_color(keyword)` | keyword → hex → nearest catalog SKU |
| `validate_placement(sku_id, wall_length_mm)` | fit + NKBA check |
| `check_clearance(sku_id, adjacent_items)` | front clearance |

**Load pattern in `mcp_server/catalog_loader.py`:** catalog is loaded once at server startup; agents call MCP tools, never read the file directly.

## Rules
1. **Never read `catalog.json` directly** from agent or pipeline code — always use MCP tools
2. **Never invent a SKU** to satisfy a query or make a test pass
3. `catalog.json` has `price_tier` ("low"/"mid"/"high") but NO real prices; budget features MUST use a documented estimated price map and label all cost output as "Estimated Cost"
4. Use `tests/fixtures/sample_inputs.py` for reusable fixture data — no inline fake SKUs in test files
5. Preserve `catalog.json` schema compatibility — never add/remove top-level fields without an ADR
6. Category strings must match exactly: "base_cabinet", "wall_cabinet", "tall_cabinet", "refrigerator", "sink", "dishwasher", "stove", "hood", "oven", "microwave", "coffee_machine"

## Bad Example
```python
# WRONG — reads catalog.json directly from agent code
import json
with open("catalog.json") as f:
    catalog = json.load(f)
items = [v for v in catalog.values() if v["category"] == "sink"]

# WRONG — invents a SKU
return SKU(id="SKU-FAKE-001", name="Budget Sink", width_mm=600, ...)
```

## Good Example
```python
# CORRECT — calls MCP tool
sinks = await mcp_client.call_tool("get_skus_by_category", {"category": "sink"})
# CORRECT — estimated cost with documented map, labeled clearly
ESTIMATED_PRICES: dict[str, float] = {"low": 500.0, "mid": 1200.0, "high": 2800.0}
cost = ESTIMATED_PRICES[sku.price_tier]  # label this "Estimated Cost" in output
```

## Common Failure Modes
- Agent imports `catalog.json` directly instead of using MCP → violates abstraction
- Test creates a fake SKU inline (`SKU(id="fake-sink", ...)`) → pollutes fixtures
- Budget feature uses unlabeled costs, implying real prices → misleads users

## Must Not Do
- Never modify `catalog.json` without an ADR in `decisions/`
- Never return a cost figure without the label "Estimated Cost"
- Never use a SKU ID that doesn't exist in `catalog.json`

## Completion Checklist
- [ ] All catalog access goes through `mcp_server/server.py` tools
- [ ] No invented SKUs in code, fixtures, or tests
- [ ] Budget/cost features use a documented estimated price map
- [ ] All cost outputs labeled "Estimated Cost"
- [ ] Existing `catalog.json` schema preserved
