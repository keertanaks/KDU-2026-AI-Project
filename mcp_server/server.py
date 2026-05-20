"""MCP server exposing catalog as queryable tools.

Provides 9 tools for agents to access catalog data without direct JSON reads.
Tools are designed to be integrated with LangGraph orchestrator.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.catalog_loader import get_catalog
from mcp_server.color_resolver import keyword_to_hex, match_catalog_color

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
    """Convert color keyword to hex and return nearest catalog match."""
    catalog = _get_catalog()
    try:
        hex_code = keyword_to_hex(keyword)
        match = match_catalog_color(hex_code, catalog)
        if match:
            matched_sku_id, distance = match
            return {
                "hex": hex_code,
                "matched_sku": matched_sku_id,
                "delta_e": round(distance, 2),
            }
        else:
            return {
                "hex": hex_code,
                "matched_sku": None,
                "delta_e": None,
                "reason": "No catalog color within tolerance",
            }
    except Exception as e:
        logger.error(f"Color resolution failed: {e}")
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
