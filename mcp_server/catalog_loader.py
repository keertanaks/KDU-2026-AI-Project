"""Load and normalize catalog.json for MCP tool access.

Applies alias maps for categories and price tiers to enable multi-region support.
All color fields normalized to 6-char lowercase hex.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger(__name__)

# Alias maps for normalized field values
CATEGORY_ALIASES = {
    "unterschrank": "base_cabinet",
    "oberschrank": "wall_cabinet",
    "base_unit": "base_cabinet",
    "wall_unit": "wall_cabinet",
}

PRICE_ALIASES = {
    "budget": "low",
    "premium": "high",
    "economy": "low",
    "luxury": "high",
}

# Required fields that every SKU must have
REQUIRED_FIELDS = {
    "sku_id",
    "name",
    "category",
    "width_mm",
    "depth_mm",
    "height_mm",
    "color",
    "price_tier",
    "style",
    "front_clearance_mm",
    "needs_water",
    "needs_power",
    "must_attach_to",
}


def _normalize_color(color_value: Any) -> str:
    """Convert color to 6-char lowercase hex."""
    if isinstance(color_value, str):
        color_str = color_value.strip()
        if color_str.startswith("#"):
            color_str = color_str[1:]
        # Normalize to 6 chars, lowercase
        return color_str.lower().zfill(6)[:6]
    raise ValueError(f"Color must be string, got {type(color_value)}")


def _normalize_category(category_str: str) -> str:
    """Apply category alias map."""
    normalized = category_str.lower().strip()
    return CATEGORY_ALIASES.get(normalized, normalized)


def _normalize_price_tier(price_str: str) -> str:
    """Apply price tier alias map."""
    normalized = price_str.lower().strip()
    return PRICE_ALIASES.get(normalized, normalized)


def load_catalog(catalog_id: str = "catalog", base_dir: str = ".") -> dict[str, dict[str, Any]]:
    """Load and normalize catalog JSON.

    Args:
        catalog_id: Name of catalog file (without .json extension)
        base_dir: Directory containing catalog file

    Returns:
        Dict keyed by sku_id with all fields normalized

    Raises:
        ValueError: If required fields are missing or file not found
    """
    catalog_path = Path(base_dir) / f"{catalog_id}.json"

    if not catalog_path.exists():
        raise ValueError(f"Catalog file not found: {catalog_path}")

    with open(catalog_path, encoding="utf-8") as f:
        raw_catalog = json.load(f)

    if not isinstance(raw_catalog, list):
        raise ValueError(f"Catalog must be a list, got {type(raw_catalog)}")

    normalized: dict[str, dict[str, Any]] = {}

    for item in raw_catalog:
        if not isinstance(item, dict):
            logger.warning("Skipping non-dict item in catalog")
            continue

        # Extract and normalize fields
        sku_id = item.get("id", "")
        if not sku_id:
            logger.warning("Skipping item without id field")
            continue

        # Flatten nested constraints if present
        constraints = item.get("constraints", {})
        if not isinstance(constraints, dict):
            constraints = {}

        normalized_sku: dict[str, Any] = {
            "sku_id": sku_id,
            "name": item.get("type", sku_id),
            "category": _normalize_category(item.get("category", "")),
            "width_mm": float(item.get("width_mm", 0)),
            "depth_mm": float(item.get("depth_mm", 0)),
            "height_mm": float(item.get("height_mm", 0)),
            "color": _normalize_color(item.get("color", "#000000")),
            "price_tier": _normalize_price_tier(item.get("price_tier", "mid")),
            "style": item.get("style_tags", []),
            "front_clearance_mm": float(constraints.get("front_clearance_mm", 0)),
            "needs_water": bool(constraints.get("needs_water", False)),
            "needs_power": bool(constraints.get("needs_power", False)),
            "must_attach_to": item.get("must_attach_to", ""),
        }

        # Validate all required fields present
        missing = REQUIRED_FIELDS - set(normalized_sku.keys())
        if missing:
            raise ValueError(f"SKU {sku_id} missing required fields: {missing}")

        normalized[sku_id] = normalized_sku

    logger.info("Loaded %d SKUs from %s", len(normalized), catalog_path)
    return normalized


# Global catalog instance (loaded once)
_CATALOG: dict[str, dict[str, Any]] | None = None


def get_catalog(catalog_id: str = "catalog", base_dir: str = ".") -> dict[str, dict[str, Any]]:
    """Get cached catalog (loads once on first call)."""
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = load_catalog(catalog_id, base_dir)
    return _CATALOG
