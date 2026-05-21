"""Run all 4 demo test scenarios and save results to test_render/.

Usage:
    python run_demo_tests.py

Each scenario gets its own subfolder under test_render/:
    test_render/
        01_L_sage_green/
            output.json
            vA_top.png  vA_3d.png ...
        02_U_warm_walnut/
        03_I_anthracite/
        04_all_variants_ivory_white/
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
import time
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).parent))

from graph.kitchen_graph import KitchenGraph

# ── Test scenarios ────────────────────────────────────────────────────────────

SCENARIOS: list[dict] = [
    {
        "name": "01_L_sage_green",
        "label": "L-shape · Sage Green · Compact Kitchen",
        "input_file": "input1.json",
        "prompt": "L-shape kitchen with sage green cabinets, modern style",
        "budget_tier": "high",
        "must_have": ["dishwasher", "hood"],
        "avoid": ["single_sink"],
    },
    {
        "name": "02_U_warm_walnut",
        "label": "U-shape · Warm Walnut · Open Plan",
        "input_file": "input2.json",
        "prompt": "U-shape kitchen with warm walnut cabinets, traditional style, maximize storage",
        "budget_tier": "mid",
        "must_have": ["dishwasher", "hood", "microwave"],
        "avoid": [],
    },
    {
        "name": "03_I_anthracite",
        "label": "I-shape · Anthracite · Family Kitchen",
        "input_file": "input3.json",
        "prompt": "I-shape kitchen with anthracite grey cabinets, minimalist design",
        "budget_tier": "mid",
        "must_have": ["hood"],
        "avoid": ["double_sink"],
    },
    {
        "name": "04_all_variants_ivory_white",
        "label": "All variants (L+U+I) · Ivory White · Open Plan",
        "input_file": "input2.json",
        "prompt": "modern kitchen with ivory white cabinets, maximize counter space",
        "budget_tier": "high",
        "must_have": ["dishwasher", "hood", "microwave"],
        "avoid": [],
    },
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_input(filename: str) -> dict:
    with open(filename, encoding="utf-8") as f:
        return json.load(f)


def build_input(scenario: dict) -> dict:
    data = load_input(scenario["input_file"])
    data.setdefault("preferences", {})
    data["preferences"]["prompt"] = scenario["prompt"]
    data["preferences"]["budget_tier"] = scenario["budget_tier"]
    data["preferences"]["must_have"] = scenario["must_have"]
    data["preferences"]["avoid"] = scenario["avoid"]
    return data


async def run_scenario(client: anthropic.Anthropic, scenario: dict) -> None:
    name = scenario["name"]
    label = scenario["label"]
    out_dir = Path("test_render") / name
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(out_dir / "output.json")

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  Output: test_render/{name}/")
    print(f"{'='*60}")

    input_json = build_input(scenario)
    graph = KitchenGraph(client, output_path=output_path, out_dir=str(out_dir))

    t0 = time.time()
    try:
        result = await graph.run(input_json)
        elapsed = time.time() - t0
        layouts = getattr(result, "layouts", []) or []
        print(f"  Done in {elapsed:.1f}s — {len(layouts)} variant(s)")
        for v in layouts:
            vid = getattr(v, "id", "?")
            score = getattr(v, "score", 0)
            family = getattr(v, "family", "?")
            nkba = getattr(v, "nkba_compliance_pct", 0)
            warns = len(getattr(v, "warnings", []))
            print(f"    {vid} ({family})  score={score:.2f}  nkba={nkba:.0f}%  warnings={warns}")
    except Exception as exc:
        elapsed = time.time() - t0
        print(f"  FAILED after {elapsed:.1f}s: {exc}")


async def main() -> None:
    Path("test_render").mkdir(exist_ok=True)
    client = anthropic.Anthropic()

    total_t0 = time.time()
    for scenario in SCENARIOS:
        await run_scenario(client, scenario)

    total = time.time() - total_t0
    print(f"\n{'='*60}")
    print(f"  All scenarios complete in {total:.1f}s")
    print(f"  Results saved to: test_render/")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
