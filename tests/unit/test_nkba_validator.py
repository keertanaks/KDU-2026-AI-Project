"""Unit tests for pipeline/nkba_validator.py — 6 tests covering scoring and rules."""

from __future__ import annotations

from dtos.contracts import (
    IntentDTO,
    Opening,
    PlacedItem,
    PlacementEngineOutput,
    PreprocessingOutput,
    Segment,
    SpatialEngineOutput,
    Wall,
)
from pipeline.nkba_validator import NKBAValidator

# ============================================================================
# Shared helpers
# ============================================================================


def _wall(
    name: str = "north_wall",
    length_mm: float = 6000.0,
    thickness_mm: float = 100.0,
    height_mm: float = 2400.0,
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


def _spatial(
    walls: list[Wall] | None = None,
    exclusions: list[Opening] | None = None,
) -> SpatialEngineOutput:
    ws = walls or [_wall()]
    return SpatialEngineOutput(
        walls=ws,
        free_segments={w.name: [Segment(0.0, w.length_mm)] for w in ws},
        flow_order=[w.name for w in ws],
        exclusions=exclusions or [],
        layout_capacity="medium",
    )


def _intent() -> IntentDTO:
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


def _preprocessing() -> PreprocessingOutput:
    return PreprocessingOutput(
        intent=_intent(),
        skus={},
        zone_groups={z: [] for z in ("cooling", "cleaning", "cooking", "preparation", "storage")},
        zone_min_widths={
            z: 600.0 for z in ("cooling", "cleaning", "cooking", "preparation", "storage")
        },
        nkba_constraints={},
    )


def _item(
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
    zone_type: str = "preparation",
) -> PlacedItem:
    return PlacedItem(
        sku_id=sku_id,
        name=name,
        category=category,
        position_mm={"x": x, "y": y, "z": z},
        dimensions_mm={"width": width, "depth": depth, "height": height},
        rotation_z_deg=0.0,
        anchor_wall=wall,
        zone_type=zone_type,
    )


def _placed(items: dict[str, PlacedItem], variant_id: str = "v1") -> PlacementEngineOutput:
    return PlacementEngineOutput(
        variant_id=variant_id,
        positioned_items=items,
        spillover_log=[],
        collision_flags=[],
    )


def _triangle_items(perimeter_mm: float) -> dict[str, PlacedItem]:
    """Build sink/fridge/stove so the work triangle perimeter ≈ perimeter_mm."""
    side = perimeter_mm / 3.0
    sink = _item("SINK-01", "Sink Unit", "sink", x=0.0, y=0.0, z=0.0, zone_type="cleaning")
    fridge = _item(
        "FR-01",
        "Refrigerator",
        "refrigerator",
        x=side,
        y=0.0,
        z=0.0,
        zone_type="cooling",
    )
    stove = _item(
        "ST-01",
        "Stove",
        "stove",
        x=side / 2.0,
        y=side * (3**0.5) / 2.0,
        z=0.0,
        zone_type="cooking",
    )
    return {"SINK-01": sink, "FR-01": fridge, "ST-01": stove}


# ============================================================================
# Test 1 — WORKFLOW-03 PASS: perimeter 4500mm
# ============================================================================


def test_workflow_03_pass_4500mm() -> None:
    """Triangle perimeter 4500mm is within [3962, 6600]mm → no WORKFLOW-03 violation."""
    validator = NKBAValidator()
    items = _triangle_items(4500.0)
    result = validator.validate(_placed(items), _spatial(), _preprocessing())
    violated_ids = {v["rule_id"] for v in result.violations}
    assert "WORKFLOW-03" not in violated_ids


# ============================================================================
# Test 2 — WORKFLOW-03 FAIL: perimeter 2000mm
# ============================================================================


def test_workflow_03_fail_2000mm() -> None:
    """Triangle perimeter 2000mm < 3962mm → WORKFLOW-03 violation and score < 1.0."""
    validator = NKBAValidator()
    items = _triangle_items(2000.0)
    result = validator.validate(_placed(items), _spatial(), _preprocessing())
    violated_ids = {v["rule_id"] for v in result.violations}
    assert "WORKFLOW-03" in violated_ids
    assert result.score < 1.0


# ============================================================================
# Test 3 — NKBA-CL-01 FAIL: fridge with 500mm clearance
# ============================================================================


def test_nkba_cl_01_fail_insufficient_clearance() -> None:
    """Fridge with only 1000mm clearance in a 1500mm-deep room → NKBA-CL-01 violation.

    Wall points give room depth = max_y - min_y = 1500 - 0 = 1500mm.
    fridge y=400, depth=100 → clearance = 1500 - 400 - 100 = 1000mm < 1067mm.
    """
    validator = NKBAValidator()
    north = Wall(
        name="north_wall",
        anchor="north_wall",
        length_mm=6000.0,
        height_mm=2400.0,
        thickness_mm=100.0,
        has_cabinets=True,
        points=[{"x": 0, "y": 1500}, {"x": 6000, "y": 1500}],
    )
    south = Wall(
        name="south_wall",
        anchor="south_wall",
        length_mm=6000.0,
        height_mm=2400.0,
        thickness_mm=100.0,
        has_cabinets=False,
        points=[{"x": 0, "y": 0}, {"x": 6000, "y": 0}],
    )
    spatial = _spatial(walls=[north, south])
    fridge = _item(
        "FR-01",
        "Refrigerator",
        "refrigerator",
        x=0.0,
        y=400.0,
        z=0.0,
        width=600.0,
        depth=100.0,
        height=1800.0,
        zone_type="cooling",
    )
    result = validator.validate(_placed({"FR-01": fridge}), spatial, _preprocessing())
    violated_ids = {v["rule_id"] for v in result.violations}
    assert "NKBA-CL-01" in violated_ids


# ============================================================================
# Test 4 — WORKFLOW-01 FAIL: sink and DW 1000mm apart
# ============================================================================


def test_workflow_01_fail_sink_dw_too_far() -> None:
    """Sink centre at x=300, DW centre at x=1300 → delta 1000mm > 600mm → WORKFLOW-01."""
    validator = NKBAValidator()
    sink = _item("SINK-01", "Sink Unit", "sink", x=0.0, y=0.0, z=0.0, zone_type="cleaning")
    dw = _item("DW-01", "Dishwasher", "dishwasher", x=1000.0, y=0.0, z=0.0, zone_type="cleaning")
    result = validator.validate(
        _placed({"SINK-01": sink, "DW-01": dw}), _spatial(), _preprocessing()
    )
    violated_ids = {v["rule_id"] for v in result.violations}
    assert "WORKFLOW-01" in violated_ids


# ============================================================================
# Test 5 — LAYOUT-02 FAIL: no hood in layout
# ============================================================================


def test_layout_02_fail_no_hood() -> None:
    """Stove present but no hood → LAYOUT-02 violation."""
    validator = NKBAValidator()
    stove = _item("ST-01", "Stove", "stove", x=1000.0, y=0.0, z=0.0, zone_type="cooking")
    result = validator.validate(_placed({"ST-01": stove}), _spatial(), _preprocessing())
    violated_ids = {v["rule_id"] for v in result.violations}
    assert "LAYOUT-02" in violated_ids


# ============================================================================
# Test 6 — Score > 1.0 when no violations and no spillover
# ============================================================================


def test_score_above_1_when_no_spillover_no_weighted_violations() -> None:
    """No spillover, no weighted-rule violations → score > 1.0 (NKBA compliance bonus).

    An empty layout still trips some unweighted structural rules (NKBA-06, NKBA-19,
    NKBA-25).  Those carry weight=0 so they don't reduce the score below 1.0.
    The compliance bonus (passed/total * 0.30) keeps score above 1.0.
    """
    validator = NKBAValidator()
    result = validator.validate(_placed({}), _spatial(), _preprocessing())
    assert result.score > 1.0
    assert result.spillover_count == 0
    # No weighted rules should be violated on an empty layout
    from pipeline.nkba_validator import RULE_WEIGHTS

    weighted_violated = {v["rule_id"] for v in result.violations} & set(RULE_WEIGHTS)
    assert not weighted_violated, f"Unexpected weighted violations: {weighted_violated}"
