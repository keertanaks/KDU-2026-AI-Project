"""Shared test fixtures — load input JSON files for use in tests."""

from __future__ import annotations

import json
from pathlib import Path

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
