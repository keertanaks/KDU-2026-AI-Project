---
name: color-resolution
description: Use when writing code that maps user color keywords to hex values and then to catalog SKUs. Covers fuzzy matching, nearest-color fallback, warning behavior, and the rule that every resolved color must map to a real SKU.
version: 1.0.0
last_verified: 2026-05-24
applies_to:
  - mcp_server/color_resolver.py
  - agents/prompt_parser.py
  - agents/catalog_selector.py
  - tests/unit/test_*.py
tool_risk: low
---

# Color Resolution Skill

## Purpose
Map user color keywords → hex values → catalog SKUs using `mcp_server/color_resolver.py`, with graceful fallback and warnings when no exact match exists.

## When to Use
Any time user input contains a color keyword ("navy blue", "sage green", "matte black"), a style phrase with color implications, or code resolves a material/finish to a catalog item.

## Existing Repo Pattern

**Resolution chain in `agents/prompt_parser.py`:**
1. `COLOR_KEYWORD_HEX` dict maps keywords → hex (e.g., `"navy blue" → "#1F3A5F"`)
2. `mcp_server/color_resolver.py` provides `keyword_to_hex()` and `match_catalog_color()` using `delta_e()` for perceptual distance
3. `mcp_server/server.py` exposes `resolve_color(keyword)` as an MCP tool
4. `delta_e()` imported from `mcp_server/color_resolver.py` is also used directly in `agents/catalog_selector.py`

**Fallback behavior:** If no exact keyword match, `match_catalog_color()` returns the nearest hex by CIELAB delta-E distance plus a `nearest_match: true` warning flag.

## Rules
1. **Never return a color that has no matching SKU** — every resolved color must map to a real catalog entry
2. **Never crash on unrecognized color** — always return a nearest match with a warning
3. **Never invent a SKU** to satisfy a color request
4. Color keywords must go through `mcp_server/color_resolver.py` or the `COLOR_KEYWORD_HEX` map in `prompt_parser.py` — no ad-hoc hex strings in agent logic
5. When a nearest-color fallback is used, surface a human-readable warning in the variant's `warnings[]` field
6. Case-insensitive keyword matching is required — `"Navy Blue"` and `"navy blue"` must resolve identically

## Bad Example
```python
# WRONG — invents a SKU for the color
if "dark grey" not in COLOR_KEYWORD_HEX:
    return SKU(id="FAKE-DG-001", name="Dark Grey Cabinet", hex="#333333")

# WRONG — crashes on unknown color
hex_val = COLOR_KEYWORD_HEX["unknown color"]  # KeyError
```

## Good Example
```python
# CORRECT — nearest match with warning
resolved = await mcp_client.call_tool("resolve_color", {"keyword": "dark grey"})
if resolved.get("nearest_match"):
    warnings.append(f"Color 'dark grey' not exact — nearest match: {resolved['hex']} ({resolved['sku_id']})")
```

## Common Failure Modes
- Resolving a hex value that exists in `COLOR_KEYWORD_HEX` but has no corresponding SKU in `catalog.json`
- Silently dropping the color warning, leaving the user unaware of the substitution
- Returning `None` or an empty SKU when no match found instead of the nearest match

## Must Not Do
- Never return `None` or raise an exception for an unrecognized color keyword
- Never skip the warning when a nearest-color substitution is made
- Never use a hex value not backed by a real catalog SKU

## Completion Checklist
- [ ] All color resolution goes through `mcp_server/color_resolver.py` or `COLOR_KEYWORD_HEX`
- [ ] Unknown colors return nearest match, not crash
- [ ] Nearest-match substitutions always add a `warnings[]` entry
- [ ] Resolved color always maps to a real `catalog.json` SKU
- [ ] Case-insensitive matching verified in tests
