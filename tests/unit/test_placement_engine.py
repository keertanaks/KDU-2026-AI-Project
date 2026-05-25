"""Unit tests for pipeline/placement_engine.py.

Tests cover: semantic term resolution, dependent placement,
spillover handling, collision whitelist, and work triangle check.
"""

from __future__ import annotations

import pytest

from dtos.contracts import (
    SKU,
    IntentDTO,
    Opening,
    PlacedItem,
    PlacementEngineOutput,
    PreprocessingOutput,
    Segment,
    SpatialEngineOutput,
    Wall,
    ZonePlannerOutput,
)
from pipeline.placement_engine import (
    WORK_TRIANGLE_MIN_MM,
    PlacementEngine,
)

# ============================================================================
# Fixtures
# ============================================================================


def _make_wall(
    name: str = "north_wall",
    length_mm: float = 4000.0,
    height_mm: float = 2400.0,
    thickness_mm: float = 100.0,
) -> Wall:
    return Wall(
        name=name,
        anchor=name,
        length_mm=length_mm,
        height_mm=height_mm,
        thickness_mm=thickness_mm,
        has_cabinets=True,
        points=[],
    )


def _make_sku(
    sku_id: str = "BC-001",
    name: str = "Base Cabinet",
    category: str = "base_cabinet",
    width_mm: float = 600.0,
    depth_mm: float = 600.0,
    height_mm: float = 850.0,
) -> SKU:
    return SKU(
        sku_id=sku_id,
        name=name,
        category=category,
        width_mm=width_mm,
        depth_mm=depth_mm,
        height_mm=height_mm,
        color="ffffff",
        price_tier="mid",
        style=["modern"],
        front_clearance_mm=1200.0,
        needs_water=False,
        needs_power=False,
        must_attach_to="",
    )


def _make_spatial(
    wall: Wall | None = None,
    segments: list[Segment] | None = None,
    exclusions: list[Opening] | None = None,
) -> SpatialEngineOutput:
    w = wall or _make_wall()
    segs = segments or [Segment(start_mm=0.0, end_mm=w.length_mm)]
    return SpatialEngineOutput(
        walls=[w],
        free_segments={w.name: segs},
        flow_order=[w.name],
        exclusions=exclusions or [],
        layout_capacity="medium",
    )


def _make_intent() -> IntentDTO:
    return IntentDTO(
        color_keyword=None,
        color_hex=None,
        layout_family=None,
        style=None,
        cabinet_preference=None,
        special_requests=[],
        ignored=[],
        budget_tier="mid",
        must_have=[],
        avoid=[],
    )


def _make_preprocessing(skus_by_zone: dict[str, list[SKU]]) -> PreprocessingOutput:
    all_skus = {sku.sku_id: sku for skus in skus_by_zone.values() for sku in skus}
    zone_groups: dict[str, list[SKU]] = {
        "cooling": [],
        "cleaning": [],
        "cooking": [],
        "preparation": [],
        "storage": [],
    }
    zone_groups.update(skus_by_zone)
    return PreprocessingOutput(
        intent=_make_intent(),
        skus=all_skus,
        zone_groups=zone_groups,
        zone_min_widths={z: 600.0 for z in zone_groups},
        nkba_constraints={},
    )


def _make_plan(
    wall_name: str,
    zone_name: str,
    strategy: str,
    variant_id: str = "v1",
    work_triangle_priority: bool = False,
) -> ZonePlannerOutput:
    return ZonePlannerOutput(
        variant_id=variant_id,
        family="L",
        wall_strategies={wall_name: [strategy]},
        zone_assignments={zone_name: wall_name},
        work_triangle_priority=work_triangle_priority,
        adjacency_hints=[],
        avoid_zones=[],
        notes="",
    )


def _placed_item(
    sku_id: str,
    name: str,
    category: str,
    x: float,
    y: float,
    z: float,
    width: float = 600.0,
    depth: float = 600.0,
    height: float = 850.0,
    wall: str = "north_wall",
) -> PlacedItem:
    return PlacedItem(
        sku_id=sku_id,
        name=name,
        category=category,
        position_mm={"x": x, "y": y, "z": z},
        dimensions_mm={"width": width, "depth": depth, "height": height},
        rotation_z_deg=0.0,
        anchor_wall=wall,
        zone_type="preparation",
    )


# ============================================================================
# Test 1: "left end of north_wall" resolves to free_segments[0].start_mm
# ============================================================================


def test_left_end_resolves_to_first_segment_start() -> None:
    """'left end of north_wall' → x = free_segments['north_wall'][0].start_mm."""
    engine = PlacementEngine()
    wall = _make_wall("north_wall", length_mm=4000.0)
    seg = Segment(start_mm=200.0, end_mm=4000.0)
    spatial = _make_spatial(wall=wall, segments=[seg])
    sku = _make_sku("BC-001", "Base Cabinet", "base_cabinet", width_mm=600.0)
    preprocessing = _make_preprocessing({"preparation": [sku]})
    plan = _make_plan("north_wall", "preparation", "left end of north_wall")

    output: PlacementEngineOutput = engine.place(plan, preprocessing, spatial)

    assert "BC-001" in output.positioned_items
    item = output.positioned_items["BC-001"]
    assert item.position_mm["x"] == pytest.approx(seg.start_mm)


# ============================================================================
# Test 2: "next to sink" → dishwasher.x = sink.x + sink.width
# ============================================================================


def test_next_to_sink_places_dishwasher_adjacent() -> None:
    """Dishwasher placed 'next to sink' ends up immediately right of sink."""
    engine = PlacementEngine()
    wall = _make_wall("north_wall", length_mm=5000.0)
    spatial = _make_spatial(wall=wall)

    sink = _make_sku("SINK-01", "Sink Unit", "sink", width_mm=600.0)
    dishwasher = _make_sku("DW-01", "Dishwasher", "dishwasher", width_mm=600.0)

    preprocessing = _make_preprocessing({"cleaning": [sink, dishwasher]})

    plan = ZonePlannerOutput(
        variant_id="v1",
        family="L",
        wall_strategies={"north_wall": ["left end of north_wall"]},
        zone_assignments={"cleaning": "north_wall"},
        work_triangle_priority=False,
        adjacency_hints=[],
        avoid_zones=[],
        notes="",
    )

    output = engine.place(plan, preprocessing, spatial)

    assert "SINK-01" in output.positioned_items
    assert "DW-01" in output.positioned_items

    sink_item = output.positioned_items["SINK-01"]
    dw_item = output.positioned_items["DW-01"]

    expected_dw_x = sink_item.position_mm["x"] + sink_item.dimensions_mm["width"]
    assert dw_item.position_mm["x"] == pytest.approx(expected_dw_x)


# ============================================================================
# Test 3: Spillover — wall_cabinet dropped; appliance forced to corner
# ============================================================================


def test_spillover_drops_wall_cabinet_and_forces_appliance() -> None:
    """wall_cabinet dropped to spillover log when no space; appliance forced to corner."""
    engine = PlacementEngine()
    # Very short wall — only 100mm free, not enough for 600mm items
    wall = _make_wall("north_wall", length_mm=100.0)
    seg = Segment(start_mm=0.0, end_mm=100.0)
    spatial = _make_spatial(wall=wall, segments=[seg])

    wall_cab = _make_sku("WC-01", "Wall Cabinet", "wall_cabinet", width_mm=600.0)
    fridge = _make_sku("FR-01", "Refrigerator", "refrigerator", width_mm=600.0)

    preprocessing = _make_preprocessing({"storage": [wall_cab], "cooling": [fridge]})

    plan = ZonePlannerOutput(
        variant_id="v1",
        family="L",
        wall_strategies={"north_wall": []},
        zone_assignments={"storage": "north_wall", "cooling": "north_wall"},
        work_triangle_priority=False,
        adjacency_hints=[],
        avoid_zones=[],
        notes="",
    )

    output = engine.place(plan, preprocessing, spatial)

    # Wall cabinet should be in spillover (dropped), not placed
    spillover_text = " ".join(output.spillover_log)
    assert "WC-01" in spillover_text
    assert "SPILLOVER" in spillover_text

    # Appliance (fridge) should be forced to corner with CONSTRAINT_VIOLATION
    assert "FR-01" in output.positioned_items
    assert any("CONSTRAINT_VIOLATION" in entry for entry in output.spillover_log)


# ============================================================================
# Test 4: Collision whitelist — hood↔stove not flagged; dup base_cabs ARE
# ============================================================================


def test_collision_whitelist_hood_stove_not_flagged() -> None:
    """hood↔stove overlap is whitelisted; two base_cabinets at same position are flagged."""
    engine = PlacementEngine()

    # hood directly above stove — whitelisted (z-axis overlap)
    stove = _placed_item("ST-01", "Stove", "stove", x=0.0, y=100.0, z=0.0, height=850.0)
    hood = _placed_item("HD-01", "Hood", "hood", x=0.0, y=100.0, z=850.0, height=400.0)

    # Two base cabinets at SAME position — collision
    bc1 = _placed_item("BC-01", "Base Cabinet", "base_cabinet", x=1000.0, y=100.0, z=0.0)
    bc2 = _placed_item("BC-02", "Base Cabinet", "base_cabinet", x=1000.0, y=100.0, z=0.0)

    placed = {"ST-01": stove, "HD-01": hood, "BC-01": bc1, "BC-02": bc2}
    flags = engine._detect_collisions(placed)

    # hood↔stove must NOT appear
    assert not any("HD-01" in f and "ST-01" in f for f in flags)
    assert not any("ST-01" in f and "HD-01" in f for f in flags)

    # BC-01 ↔ BC-02 must be flagged
    assert any("BC-01" in f and "BC-02" in f for f in flags) or any(
        "BC-02" in f and "BC-01" in f for f in flags
    )


# ============================================================================
# Test 5: work_triangle_priority=True → WORKFLOW-03 logged when < 3962mm
# ============================================================================


def test_work_triangle_violation_logged_when_too_small() -> None:
    """WORKFLOW-03 is logged when triangle perimeter is below WORK_TRIANGLE_MIN_MM."""
    engine = PlacementEngine()

    # Place sink, fridge, stove very close together — triangle < 3962mm
    sink = _placed_item(
        "SINK-01", "Sink Unit", "sink", x=0.0, y=0.0, z=0.0, width=600.0, depth=600.0
    )
    fridge = _placed_item(
        "FR-01", "Refrigerator", "refrigerator", x=700.0, y=0.0, z=0.0, width=600.0, depth=600.0
    )
    stove = _placed_item(
        "ST-01", "Stove", "stove", x=1400.0, y=0.0, z=0.0, width=600.0, depth=600.0
    )

    placed: dict[str, PlacedItem] = {
        "SINK-01": sink,
        "FR-01": fridge,
        "ST-01": stove,
    }
    # All items on same wall ("north_wall") with empty points → _global_xy falls back to local
    spatial = _make_spatial()
    spillover: list[str] = []
    engine._check_work_triangle(placed, spatial, spillover)

    # Perimeter should be well below 3962mm — violation expected
    assert any("WORKFLOW-03" in entry for entry in spillover)

    # Verify the perimeter really is below min (using local _dist2d since same-wall)
    perimeter = (
        engine._dist2d(sink, fridge) + engine._dist2d(fridge, stove) + engine._dist2d(stove, sink)
    )
    assert perimeter < WORK_TRIANGLE_MIN_MM
