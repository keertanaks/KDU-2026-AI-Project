# OpenSpec: MCP Server
## Files: `mcp_server/server.py`, `mcp_server/catalog_loader.py`, `mcp_server/color_resolver.py`
## Branch: `feature/mcp-server`
## Design Doc: §6

---

## Goal
Expose the catalog as 9 queryable MCP tools. Agent code never reads catalog.json directly — always goes through these tools.
Catalog is swappable via `catalogId` in preferences without any agent code change.

## Do NOT
- Modify `catalog.json`
- Hard-code any SKU names or IDs in agent logic
- Return SKUs that don't exist in the loaded catalog

---

## `mcp_server/catalog_loader.py`

### Purpose
Load and normalize catalog.json (or alternate catalog via catalogId).
Apply alias maps so any country's catalog works with the same tools.

### Required Alias Maps
```python
CATEGORY_ALIASES = {
    "unterschrank": "base_cabinet",
    "oberschrank":  "wall_cabinet",
    "base_unit":    "base_cabinet",
    "wall_unit":    "wall_cabinet",
}

PRICE_ALIASES = {
    "budget":  "low",
    "premium": "high",
    "economy": "low",
    "luxury":  "high",
}
```

### Required Fields Validation
Every SKU must have: sku_id, name, category, width_mm, depth_mm, height_mm, color, price_tier, style, front_clearance_mm, needs_water, needs_power, must_attach_to.
Raise `ValueError` if any required field is missing after normalization.

### Function Signature
```python
def load_catalog(catalog_id: str = "catalog", base_dir: str = ".") -> dict[str, dict]:
    """Returns dict keyed by sku_id with all fields normalized."""
```

---

## `mcp_server/color_resolver.py`

### Purpose
Convert natural language color keywords to hex, then match against catalog color field.

### ΔE Tolerance
15 (CIE Lab color space distance). Use `colormath` library.

### Function Signatures
```python
def keyword_to_hex(keyword: str, client: anthropic.Anthropic) -> str:
    """Use claude-haiku-4-5 to convert color keyword to 6-char hex. E.g. 'navy blue' → '#1F3A5F'"""

def match_catalog_color(hex_code: str, catalog: dict[str, dict]) -> str | None:
    """Return sku_id of nearest catalog color within ΔE=15, or None if no match."""

def delta_e(hex1: str, hex2: str) -> float:
    """CIE76 ΔE distance between two hex colors."""
```

---

## `mcp_server/server.py`

### Framework
Use `mcp` Python package. Start server on stdio transport.

### All 9 Tools

```python
@mcp.tool()
def get_catalog_items() -> list[dict]:
    """Return all SKUs as list of dicts."""

@mcp.tool()
def get_skus_by_category(category: str) -> list[dict]:
    """Filter SKUs by normalized category. category: 'base_cabinet'|'wall_cabinet'|'tall_cabinet'|'appliance'|'fixture'|'island'"""

@mcp.tool()
def get_sku_dimensions(sku_id: str) -> dict:
    """Return {'width_mm': int, 'depth_mm': int, 'height_mm': int} for given SKU."""

@mcp.tool()
def get_sku_constraints(sku_id: str) -> dict:
    """Return {'front_clearance_mm': int, 'needs_water': bool, 'needs_power': bool, 'must_attach_to': str}"""

@mcp.tool()
def get_skus_by_price_tier(tier: str) -> list[dict]:
    """Filter SKUs by normalized price tier. tier: 'low'|'mid'|'high'"""

@mcp.tool()
def get_skus_by_style(style: str) -> list[dict]:
    """Filter SKUs where style array contains given style value."""

@mcp.tool()
def resolve_color(keyword: str) -> dict:
    """Convert color keyword to hex and return nearest catalog match.
    Returns {'hex': '#1F3A5F', 'matched_sku': 'SKU-C11', 'delta_e': 4.2}"""

@mcp.tool()
def validate_placement(sku_id: str, wall_length_mm: int) -> dict:
    """Check if SKU fits in wall_length_mm and passes NKBA constraints.
    Returns {'fits': bool, 'reason': str}"""

@mcp.tool()
def check_clearance(sku_id: str, adjacent_items: list[str]) -> dict:
    """Verify front_clearance_mm is not blocked by any adjacent item.
    Returns {'clearance_ok': bool, 'blocked_by': list[str]}"""
```

### Startup
```python
if __name__ == "__main__":
    mcp.run(transport="stdio")
```

---

## Testing
```bash
# Start server
python mcp_server/server.py &

# Call get_catalog_items via MCP client
python -c "
from mcp import ClientSession, StdioServerParameters
# test get_catalog_items returns >= 1 item
"
```
