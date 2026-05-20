"""Integration tests — make real API calls. Run with: pytest tests/integration/ -m integration."""

from __future__ import annotations

import asyncio
import json

import pytest
from tests.fixtures.sample_inputs import INPUT1, INPUT3, MINIMAL_PREFERENCES


@pytest.mark.integration
@pytest.mark.slow
async def test_full_pipeline_input1():
    """End-to-end run on the small kitchen — 3 variants expected."""
    from graph.kitchen_graph import build_graph

    input_json = {**INPUT1, "preferences": MINIMAL_PREFERENCES}
    graph = build_graph()
    result = await graph.ainvoke({"input_json": input_json})

    layouts = result["final_output"].layouts
    assert len(layouts) >= 3, f"Expected ≥3 variants, got {len(layouts)}"
    for layout in layouts:
        assert layout.score >= 0.0
        assert layout.placement_count > 0
        assert layout.variant_id.startswith("variant-")


@pytest.mark.integration
@pytest.mark.slow
async def test_full_pipeline_input3_with_openings():
    """End-to-end run on kitchen with door + windows — tests Bonus P1."""
    from graph.kitchen_graph import build_graph

    input_json = {**INPUT3, "preferences": MINIMAL_PREFERENCES}
    graph = build_graph()
    result = await graph.ainvoke({"input_json": input_json})

    layouts = result["final_output"].layouts
    assert len(layouts) >= 3
    # At least one variant should have a sink near the north window
    sink_near_window = any(
        any(r["rule_id"] == "LAYOUT-01" and "window" in r["text"].lower() for r in v.rationale)
        for v in layouts
    )
    assert sink_near_window, "Expected at least one variant with sink near window (LAYOUT-01)"


@pytest.mark.integration
async def test_output_json_matches_render_contract():
    """output.json must pass render.py without errors."""
    import subprocess
    from pathlib import Path

    result = subprocess.run(
        ["python", "render.py", "output.json", "--out-dir", "renders", "--2d-only"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"render.py failed:\n{result.stderr}"
