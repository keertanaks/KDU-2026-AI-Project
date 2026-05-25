"""MCP server exposing catalog as queryable tools.

Provides 9 tools for agents to access catalog data without direct JSON reads.
Tools are designed to be integrated with LangGraph orchestrator.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.catalog_loader import get_catalog
from mcp_server.color_resolver import match_catalog_color, resolve_color_keyword

logger = logging.getLogger(__name__)

# Load catalog once at startup
_CATALOG: dict[str, dict[str, Any]] | None = None


def _get_catalog() -> dict[str, dict[str, Any]]:
    """Lazy-load and cache catalog."""
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = get_catalog()
    return _CATALOG


def _sku_to_dict(sku_id: str, sku_data: dict[str, Any]) -> dict[str, Any]:
    """Convert SKU to JSON-serializable dict."""
    return {
        "sku_id": sku_data["sku_id"],
        "name": sku_data["name"],
        "category": sku_data["category"],
        "width_mm": sku_data["width_mm"],
        "depth_mm": sku_data["depth_mm"],
        "height_mm": sku_data["height_mm"],
        "color": sku_data["color"],
        "price_tier": sku_data["price_tier"],
        "style": sku_data["style"],
        "front_clearance_mm": sku_data["front_clearance_mm"],
        "needs_water": sku_data["needs_water"],
        "needs_power": sku_data["needs_power"],
        "must_attach_to": sku_data["must_attach_to"],
    }


def get_catalog_items() -> list[dict[str, Any]]:
    """Return all SKUs as list of dicts."""
    catalog = _get_catalog()
    return [_sku_to_dict(sku_id, sku_data) for sku_id, sku_data in catalog.items()]


def get_skus_by_category(category: str) -> list[dict[str, Any]]:
    """Filter SKUs by normalized category."""
    catalog = _get_catalog()
    category_lower = category.lower()
    return [
        _sku_to_dict(sku_id, sku_data)
        for sku_id, sku_data in catalog.items()
        if sku_data["category"] == category_lower
    ]


def get_sku_dimensions(sku_id: str) -> dict[str, Any]:
    """Return dimensions dict for given SKU."""
    catalog = _get_catalog()
    if sku_id not in catalog:
        return {"error": f"SKU {sku_id} not found"}
    sku = catalog[sku_id]
    return {
        "sku_id": sku_id,
        "width_mm": sku["width_mm"],
        "depth_mm": sku["depth_mm"],
        "height_mm": sku["height_mm"],
    }


def get_sku_constraints(sku_id: str) -> dict[str, Any]:
    """Return constraints dict for given SKU."""
    catalog = _get_catalog()
    if sku_id not in catalog:
        return {"error": f"SKU {sku_id} not found"}
    sku = catalog[sku_id]
    return {
        "sku_id": sku_id,
        "front_clearance_mm": sku["front_clearance_mm"],
        "needs_water": sku["needs_water"],
        "needs_power": sku["needs_power"],
        "must_attach_to": sku["must_attach_to"],
    }


def get_skus_by_price_tier(tier: str) -> list[dict[str, Any]]:
    """Filter SKUs by normalized price tier."""
    catalog = _get_catalog()
    tier_lower = tier.lower()
    return [
        _sku_to_dict(sku_id, sku_data)
        for sku_id, sku_data in catalog.items()
        if sku_data["price_tier"] == tier_lower
    ]


def get_skus_by_style(style: str) -> list[dict[str, Any]]:
    """Filter SKUs where style array contains given style value."""
    catalog = _get_catalog()
    style_lower = style.lower()
    return [
        _sku_to_dict(sku_id, sku_data)
        for sku_id, sku_data in catalog.items()
        if style_lower in [s.lower() for s in sku_data["style"]]
    ]


def resolve_color(keyword: str) -> dict[str, Any]:
    """Convert color keyword to hex and return nearest catalog match.

    Returns a dict with:
    - ``hex``: resolved 6-char hex (no #)
    - ``matched_sku``: catalog SKU ID of closest color match (or None)
    - ``delta_e``: CIE76 distance to matched SKU (or None)
    - ``nearest_match``: True when the keyword was not found exactly in the
      color table and a substitution was made — callers should warn the user.
    """
    catalog = _get_catalog()
    try:
        resolution = resolve_color_keyword(keyword)
        hex_code = resolution.hex_code
        nearest_match = not resolution.exact_match

        match = match_catalog_color(hex_code, catalog)
        if match:
            matched_sku_id, distance = match
            return {
                "hex": hex_code,
                "matched_sku": matched_sku_id,
                "delta_e": round(distance, 2),
                "nearest_match": nearest_match,
            }
        else:
            return {
                "hex": hex_code,
                "matched_sku": None,
                "delta_e": None,
                "nearest_match": nearest_match,
                "reason": "No catalog color within tolerance",
            }
    except Exception as e:
        logger.error("Color resolution failed: %s", e)
        return {"error": f"Color resolution failed: {e}"}


def validate_placement(sku_id: str, wall_length_mm: int) -> dict[str, Any]:
    """Check if SKU fits in wall and passes constraints."""
    catalog = _get_catalog()
    if sku_id not in catalog:
        return {"fits": False, "reason": f"SKU {sku_id} not found"}

    sku = catalog[sku_id]
    if sku["width_mm"] > wall_length_mm:
        return {
            "fits": False,
            "reason": f"SKU width {sku['width_mm']}mm exceeds wall {wall_length_mm}mm",
        }

    return {"fits": True, "reason": "SKU fits in wall"}


def get_substitute_skus(
    category: str,
    max_tier: str,
    width_mm: float,
    width_tolerance_mm: float = 50.0,
) -> list[dict[str, Any]]:
    """Return catalog SKUs of the given category at or below max_tier whose
    width is within ±width_tolerance_mm of the target width.

    Used by pipeline/budget_optimizer.py to find cheaper, dimension-compatible
    substitutes without reading catalog.json directly.

    Args:
        category: SKU category string (e.g., "base_cabinet", "refrigerator").
        max_tier: Highest acceptable price tier ("low" | "mid" | "high").
            A "low" max_tier only returns "low" items.
            A "mid" max_tier returns "low" and "mid" items.
        width_mm: Target width of the item being replaced (mm).
        width_tolerance_mm: Max width deviation accepted (default 50mm = LAYOUT-03 gap limit).

    Returns:
        List of SKU dicts matching the constraints, sorted by width closeness.
    """
    _TIER_ORDER: dict[str, int] = {"low": 0, "mid": 1, "high": 2}
    max_rank = _TIER_ORDER.get(max_tier.lower(), 2)

    catalog = _get_catalog()
    category_lower = category.lower()

    candidates = [
        _sku_to_dict(sku_id, sku_data)
        for sku_id, sku_data in catalog.items()
        if (
            sku_data["category"] == category_lower
            and _TIER_ORDER.get(sku_data["price_tier"].lower(), 2) <= max_rank
            and abs(sku_data["width_mm"] - width_mm) <= width_tolerance_mm
        )
    ]
    # Sort by width closeness first, then by tier (cheapest first)
    candidates.sort(
        key=lambda s: (
            abs(s["width_mm"] - width_mm),
            _TIER_ORDER.get(s["price_tier"].lower(), 2),
        )
    )
    return candidates


def check_clearance(sku_id: str, adjacent_items: list[str]) -> dict[str, Any]:
    """Verify front_clearance_mm is not blocked by adjacent items."""
    catalog = _get_catalog()
    if sku_id not in catalog:
        return {"clearance_ok": False, "blocked_by": [f"SKU {sku_id} not found"]}

    sku = catalog[sku_id]
    blocked_by = []

    for adj_sku_id in adjacent_items:
        if adj_sku_id in catalog:
            adj_sku = catalog[adj_sku_id]
            if adj_sku["width_mm"] > sku["front_clearance_mm"]:
                blocked_by.append(adj_sku_id)

    return {
        "clearance_ok": len(blocked_by) == 0,
        "blocked_by": blocked_by,
    }


if __name__ == "__main__":

    def main() -> None:
        """Start MCP server."""
        logger.info("Kitchen catalog MCP server started")
        logger.info(f"Loaded catalog with {len(_get_catalog())} SKUs")

    main()
