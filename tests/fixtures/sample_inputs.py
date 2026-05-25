"""Shared test fixtures — load input JSON files for use in tests."""

from __future__ import annotations

import json
from pathlib import Path

from dtos.contracts import SKU

ROOT = Path(__file__).parent.parent.parent  # Kitchen-Layout-Visualizer/


def load_input(filename: str) -> dict:
    """Load one of the 3 test input files."""
    return json.loads((ROOT / filename).read_text(encoding="utf-8"))


INPUT1 = load_input("input1.json")  # 3600×3200mm, no openings, L-shape
INPUT2 = load_input("input2.json")  # 42000×42000mm, no openings, L-shape
INPUT3 = load_input("input3.json")  # 4200×3000mm, door + 2 windows


MINIMAL_PREFERENCES = {
    "budget_tier": "mid",
    "must_have": ["dishwasher", "hood"],
    "avoid": [],
    "prompt": "navy blue base cabinets",
    "catalogId": "catalog",
}


# ============================================================================
# SKU fixtures for budget optimizer unit tests
#
# These SKUs mirror the structure of catalog.json entries but are ONLY used
# in unit tests to verify cost calculation math (ESTIMATED_PRICE_MAP).
# They use the same fields as the real SKU dataclass.
# Do NOT use these IDs in integration tests or pipeline code — use real catalog
# entries retrieved via mcp_server/server.py.
# ============================================================================

SAMPLE_SKU_LOW = SKU(
    sku_id="TEST-BC-LOW",
    name="Test Base Cabinet Low",
    category="base_cabinet",
    width_mm=600.0,
    depth_mm=570.0,
    height_mm=850.0,
    color="EDEDE9",
    price_tier="low",
    style=["modern"],
    front_clearance_mm=1067.0,
    needs_water=False,
    needs_power=False,
    must_attach_to="wall",
)

SAMPLE_SKU_MID = SKU(
    sku_id="TEST-BC-MID",
    name="Test Base Cabinet Mid",
    category="base_cabinet",
    width_mm=600.0,
    depth_mm=570.0,
    height_mm=850.0,
    color="1F3A5F",
    price_tier="mid",
    style=["modern"],
    front_clearance_mm=1067.0,
    needs_water=False,
    needs_power=False,
    must_attach_to="wall",
)

SAMPLE_SKU_HIGH = SKU(
    sku_id="TEST-BC-HIGH",
    name="Test Base Cabinet High",
    category="base_cabinet",
    width_mm=600.0,
    depth_mm=570.0,
    height_mm=850.0,
    color="2F5233",
    price_tier="high",
    style=["modern"],
    front_clearance_mm=1067.0,
    needs_water=False,
    needs_power=False,
    must_attach_to="wall",
)

SAMPLE_SKU_MID_NARROW = SKU(
    sku_id="TEST-BC-MID-NARROW",
    name="Test Base Cabinet Mid Narrow",
    category="base_cabinet",
    width_mm=500.0,
    depth_mm=570.0,
    height_mm=850.0,
    color="1F3A5F",
    price_tier="mid",
    style=["modern"],
    front_clearance_mm=1067.0,
    needs_water=False,
    needs_power=False,
    must_attach_to="wall",
)
