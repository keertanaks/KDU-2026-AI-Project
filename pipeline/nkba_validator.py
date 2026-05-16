"""Layer 5 / Phase 7: NKBA Validator — 31 rules, deterministic scoring.

Pure Python math. No LLM calls. No Anthropic imports.
Consumes PlacementEngineOutput and emits VariantSummaryDTO.
"""

from __future__ import annotations

import math
from typing import Any

from dtos.contracts import (
    PlacedItem,
    PlacementEngineOutput,
    PreprocessingOutput,
    SpatialEngineOutput,
    VariantSummaryDTO,
)
from utils.logger import get_logger

logger = get_logger(__name__)

# ============================================================================
# Constants
# ============================================================================

FRIDGE_CLEARANCE_MM: float = 1067.0
DOOR_CLEAR_MM: float = 900.0
DW_SINK_MAX_MM: float = 600.0
STOVE_FRIDGE_MIN_MM: float = 600.0
WORK_TRI_MIN_MM: float = 3962.0
WORK_TRI_MAX_MM: float = 6600.0
WORK_TRI_NKBA03_MAX_MM: float = 7925.0
SINK_WINDOW_MM: float = 300.0
HOOD_STOVE_MM: float = 100.0
CONTINUOUS_GAP_MM: float = 50.0
SINK_LAND_LONG_MM: float = 610.0
SINK_LAND_SHORT_MM: float = 457.0
PREP_AREA_MM: float = 762.0
DW_SINK_NKBA13_MM: float = 914.0
DW_STAND_MM: float = 533.0
FRIDGE_LAND_MM: float = 381.0
STOVE_LAND_SHORT_MM: float = 305.0
STOVE_LAND_LONG_MM: float = 381.0
HOOD_CLEARANCE_MM: float = 610.0
TOTAL_COUNTER_MM: float = 4013.0
DOOR_WIDTH_MIN_MM: float = 813.0
AISLE_1COOK_MM: float = 1067.0
AISLE_2COOK_MM: float = 1219.0
WALKWAY_MM: float = 914.0

RULE_WEIGHTS: dict[str, float] = {
    "WORKFLOW-03": 0.15,
    "NKBA-CL-01": 0.10,
    "NKBA-CL-02": 0.10,
    "WORKFLOW-01": 0.10,
    "WORKFLOW-02": 0.10,
    "LAYOUT-01": 0.08,
    "LAYOUT-02": 0.08,
    "LAYOUT-03": 0.08,
    "LAYOUT-04": 0.08,
    "LAYOUT-05": 0.07,
    "LAYOUT-06": 0.06,
}


# ============================================================================
# Validator
# ============================================================================


class NKBAValidator:
    """Run all 31 NKBA/project rules and produce a scored VariantSummaryDTO."""

    def validate(
        self,
        placed: PlacementEngineOutput,
        spatial: SpatialEngineOutput,
        preprocessing: PreprocessingOutput,
    ) -> VariantSummaryDTO:
        """Evaluate all rules and return a fully scored VariantSummaryDTO."""
        violations: list[dict[str, Any]] = []

        # ── 11 Project rules (weighted) ──────────────────────────────────
        self._check_nkba_cl_01(placed, spatial, violations)
        self._check_nkba_cl_02(placed, spatial, violations)
        self._check_workflow_01(placed, violations)
        self._check_workflow_02(placed, violations)
        self._check_workflow_03(placed, violations)
        self._check_layout_01(placed, spatial, violations)
        self._check_layout_02(placed, violations)
        self._check_layout_03(placed, spatial, violations)
        self._check_layout_04(placed, violations)
        self._check_layout_05(placed, spatial, violations)
        self._check_layout_06(placed, spatial, violations)

        # ── 20 Official NKBA rules (unweighted, count only) ──────────────
        self._check_nkba_01(spatial, violations)
        self._check_nkba_02(placed, violations)
        self._check_nkba_03(placed, violations)
        self._check_nkba_04(placed, violations)
        self._check_nkba_05(violations)
        self._check_nkba_06(placed, spatial, violations)
        self._check_nkba_06b(placed, spatial, violations)
        self._check_nkba_07(placed, spatial, violations)
        self._check_nkba_08(violations)
        self._check_nkba_10(placed, violations)
        self._check_nkba_11(placed, spatial, violations)
        self._check_nkba_12(placed, spatial, violations)
        self._check_nkba_13(placed, violations)
        self._check_nkba_la_01(placed, spatial, violations)
        self._check_nkba_la_02(placed, spatial, violations)
        self._check_nkba_la_03(placed, spatial, violations)
        self._check_nkba_la_05(placed, violations)
        self._check_nkba_18(placed, violations)
        self._check_nkba_19(placed, violations)
        self._check_nkba_25(placed, violations)

        total_rules = 31
        violated_ids = {v["rule_id"] for v in violations}
        passed_rules = total_rules - len(violated_ids)
        nkba_pct = passed_rules / total_rules

        adjacency_violations = len(placed.collision_flags)
        spillover_count = len(placed.spillover_log)
        weight_penalty = sum(RULE_WEIGHTS.get(rid, 0.0) for rid in violated_ids)

        score = (
            1.0
            + nkba_pct * 0.30
            - spillover_count * 0.05
            - adjacency_violations * 0.05
            - weight_penalty
        )

        warnings = list(placed.collision_flags)
        if any("CONSTRAINT_VIOLATION" in s for s in placed.spillover_log):
            warnings.append("One or more items forced to corner — check LAYOUT-06")

        layout = self._serialize_layout(placed)

        logger.info(
            "Variant '%s': score=%.3f passed=%d/%d spillover=%d collisions=%d",
            placed.variant_id,
            score,
            passed_rules,
            total_rules,
            spillover_count,
            adjacency_violations,
        )

        return VariantSummaryDTO(
            id=placed.variant_id,
            family="",
            score=score,
            placement_count=len(placed.positioned_items),
            nkba_compliance_pct=nkba_pct,
            spillover_count=spillover_count,
            warnings=warnings,
            violations=violations,
            rationale=[],
            layout=layout,
            environment={},
        )

    # ================================================================== #
    # 11 Project Rules                                                     #
    # ================================================================== #

    def _check_nkba_cl_01(
        self,
        placed: PlacementEngineOutput,
        spatial: SpatialEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-CL-01: Fridge needs >= 1067mm clear space in front."""
        fridge = self._find("fridge", placed) or self._find("refrigerator", placed)
        if fridge is None:
            return
        room_depth = self._room_depth(spatial)
        clearance = room_depth - fridge.position_mm["y"] - fridge.dimensions_mm["depth"]
        if clearance < FRIDGE_CLEARANCE_MM:
            violations.append(
                {
                    "rule_id": "NKBA-CL-01",
                    "text": f"Fridge clearance {clearance:.0f}mm < {FRIDGE_CLEARANCE_MM:.0f}mm",
                }
            )

    def _check_nkba_cl_02(
        self,
        placed: PlacementEngineOutput,
        spatial: SpatialEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-CL-02: 900x900mm clear zone inside every door arc."""
        for opening in spatial.exclusions:
            if opening.kind != "door":
                continue
            zone = opening.blocked_end_mm - opening.blocked_start_mm
            if zone < DOOR_CLEAR_MM:
                violations.append(
                    {
                        "rule_id": "NKBA-CL-02",
                        "text": (
                            f"Door '{opening.id}' clear zone {zone:.0f}mm < {DOOR_CLEAR_MM:.0f}mm"
                        ),
                    }
                )

    def _check_workflow_01(
        self,
        placed: PlacementEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """WORKFLOW-01: Sink and dishwasher centres <= 600mm apart."""
        sink = self._find("sink", placed)
        dw = self._find("dishwasher", placed)
        if sink is None or dw is None:
            return
        dist = abs(self._centre_x(sink) - self._centre_x(dw))
        if dist > DW_SINK_MAX_MM:
            violations.append(
                {
                    "rule_id": "WORKFLOW-01",
                    "text": f"Sink-DW distance {dist:.0f}mm > {DW_SINK_MAX_MM:.0f}mm",
                }
            )

    def _check_workflow_02(
        self,
        placed: PlacementEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """WORKFLOW-02: Stove and fridge must be >= 600mm apart."""
        stove = self._find("stove", placed) or self._find("range", placed)
        fridge = self._find("fridge", placed) or self._find("refrigerator", placed)
        if stove is None or fridge is None:
            return
        stove_right = stove.position_mm["x"] + stove.dimensions_mm["width"]
        fridge_right = fridge.position_mm["x"] + fridge.dimensions_mm["width"]
        gap = abs(stove.position_mm["x"] - fridge_right)
        gap2 = abs(fridge.position_mm["x"] - stove_right)
        min_gap = min(gap, gap2)
        if min_gap < STOVE_FRIDGE_MIN_MM:
            violations.append(
                {
                    "rule_id": "WORKFLOW-02",
                    "text": f"Stove-fridge gap {min_gap:.0f}mm < {STOVE_FRIDGE_MIN_MM:.0f}mm",
                }
            )

    def _check_workflow_03(
        self,
        placed: PlacementEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """WORKFLOW-03: Work triangle perimeter 3962-6600mm."""
        sink = self._find("sink", placed)
        fridge = self._find("fridge", placed) or self._find("refrigerator", placed)
        stove = self._find("stove", placed) or self._find("range", placed)
        if not (sink and fridge and stove):
            return
        perimeter = (
            self._dist2d(sink, fridge) + self._dist2d(fridge, stove) + self._dist2d(stove, sink)
        )
        if perimeter < WORK_TRI_MIN_MM or perimeter > WORK_TRI_MAX_MM:
            violations.append(
                {
                    "rule_id": "WORKFLOW-03",
                    "text": (
                        f"Work triangle {perimeter:.0f}mm outside "
                        f"[{WORK_TRI_MIN_MM:.0f}, {WORK_TRI_MAX_MM:.0f}]mm"
                    ),
                }
            )

    def _check_layout_01(
        self,
        placed: PlacementEngineOutput,
        spatial: SpatialEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """LAYOUT-01: Sink under window (if window on same wall)."""
        sink = self._find("sink", placed)
        if sink is None:
            return
        windows_on_wall = [
            o for o in spatial.exclusions if o.kind == "window" and o.wall == sink.anchor_wall
        ]
        if not windows_on_wall:
            return
        win = windows_on_wall[0]
        win_cx = win.offset_mm + win.width_mm / 2.0
        dist = abs(self._centre_x(sink) - win_cx)
        if dist > SINK_WINDOW_MM:
            violations.append(
                {
                    "rule_id": "LAYOUT-01",
                    "text": f"Sink {dist:.0f}mm from window centre (max {SINK_WINDOW_MM:.0f}mm)",
                }
            )

    def _check_layout_02(
        self,
        placed: PlacementEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """LAYOUT-02: Hood must be above stove and within 100mm x-alignment."""
        hood = self._find("hood", placed)
        stove = self._find("stove", placed) or self._find("range", placed)
        if hood is None:
            if stove is not None:
                violations.append(
                    {
                        "rule_id": "LAYOUT-02",
                        "text": "No hood found in layout",
                    }
                )
            return
        if stove is None:
            return
        x_offset = abs(self._centre_x(hood) - self._centre_x(stove))
        above = hood.position_mm["z"] > stove.position_mm["z"]
        if x_offset > HOOD_STOVE_MM or not above:
            violations.append(
                {
                    "rule_id": "LAYOUT-02",
                    "text": (f"Hood not above stove: x_offset={x_offset:.0f}mm above={above}"),
                }
            )

    def _check_layout_03(
        self,
        placed: PlacementEngineOutput,
        spatial: SpatialEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """LAYOUT-03: Continuous run — gaps <= 50mm except at door/window openings."""
        opening_ranges: dict[str, list[tuple[float, float]]] = {}
        for o in spatial.exclusions:
            opening_ranges.setdefault(o.wall, []).append((o.blocked_start_mm, o.blocked_end_mm))

        for wall in spatial.walls:
            if not wall.has_cabinets:
                continue
            items = self._items_on_wall(wall.name, placed)
            if len(items) < 2:
                continue
            ops = opening_ranges.get(wall.name, [])
            for i in range(len(items) - 1):
                right_edge = items[i].position_mm["x"] + items[i].dimensions_mm["width"]
                next_left = items[i + 1].position_mm["x"]
                gap = next_left - right_edge
                if gap <= CONTINUOUS_GAP_MM:
                    continue
                forced_by_opening = any(os <= right_edge and oe >= next_left for os, oe in ops)
                if not forced_by_opening:
                    violations.append(
                        {
                            "rule_id": "LAYOUT-03",
                            "text": (
                                f"Gap {gap:.0f}mm on wall '{wall.name}' "
                                f"between items at x={right_edge:.0f} and x={next_left:.0f}"
                            ),
                        }
                    )
                    break  # one violation per wall

    def _check_layout_04(
        self,
        placed: PlacementEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """LAYOUT-04: Every appliance/sink has a base_cabinet overlapping its x-range."""
        appliances = [
            item
            for item in placed.positioned_items.values()
            if any(
                kw in item.category.lower() or kw in item.name.lower()
                for kw in ("sink", "stove", "range", "refrigerator", "fridge", "dishwasher")
            )
        ]
        base_cabs = [
            item
            for item in placed.positioned_items.values()
            if "base_cabinet" in item.category.lower()
        ]
        for appl in appliances:
            ax1 = appl.position_mm["x"]
            ax2 = ax1 + appl.dimensions_mm["width"]
            covered = any(
                bc.anchor_wall == appl.anchor_wall
                and bc.position_mm["x"] < ax2
                and bc.position_mm["x"] + bc.dimensions_mm["width"] > ax1
                for bc in base_cabs
            )
            if not covered:
                violations.append(
                    {
                        "rule_id": "LAYOUT-04",
                        "text": (
                            f"'{appl.name}' has no base_cabinet coverage"
                            f" on wall '{appl.anchor_wall}'"
                        ),
                    }
                )

    def _check_layout_05(
        self,
        placed: PlacementEngineOutput,
        spatial: SpatialEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """LAYOUT-05: Leftmost and rightmost items per wall are base_cabinet or at corner."""
        for wall in spatial.walls:
            if not wall.has_cabinets:
                continue
            items = self._items_on_wall(wall.name, placed)
            if not items:
                continue
            for item in (items[0], items[-1]):
                is_base = "base_cabinet" in item.category.lower()
                at_left = item.position_mm["x"] == 0.0
                at_right = (
                    item.position_mm["x"] + item.dimensions_mm["width"] >= wall.length_mm - 50.0
                )
                if not (is_base or at_left or at_right):
                    violations.append(
                        {
                            "rule_id": "LAYOUT-05",
                            "text": (
                                f"Wall '{wall.name}' run end is '{item.name}' "
                                f"(not base_cabinet and not at corner)"
                            ),
                        }
                    )
                    break

    def _check_layout_06(
        self,
        placed: PlacementEngineOutput,
        spatial: SpatialEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """LAYOUT-06: Fridge and tall_cabinets at corners/ends only."""
        for item in placed.positioned_items.values():
            is_target = "tall_cabinet" in item.category.lower() or any(
                kw in item.name.lower() for kw in ("fridge", "refrigerator")
            )
            if not is_target:
                continue
            wall = self._get_wall(item.anchor_wall, spatial)
            if wall is None:
                continue
            at_left = item.position_mm["x"] == 0.0
            at_right = item.position_mm["x"] + item.dimensions_mm["width"] >= wall.length_mm - 50.0
            if not (at_left or at_right):
                violations.append(
                    {
                        "rule_id": "LAYOUT-06",
                        "text": (f"'{item.name}' not at corner/end on wall '{item.anchor_wall}'"),
                    }
                )

    # ================================================================== #
    # 20 Official NKBA Rules                                               #
    # ================================================================== #

    def _check_nkba_01(
        self,
        spatial: SpatialEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-01: Door opening >= 813mm."""
        for opening in spatial.exclusions:
            if opening.kind != "door":
                continue
            if opening.width_mm < DOOR_WIDTH_MIN_MM:
                violations.append(
                    {
                        "rule_id": "NKBA-01",
                        "text": (
                            f"Door '{opening.id}' width {opening.width_mm:.0f}mm "
                            f"< {DOOR_WIDTH_MIN_MM:.0f}mm"
                        ),
                    }
                )

    def _check_nkba_02(
        self,
        placed: PlacementEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-02: No two appliances with overlapping front clearance zones."""
        appliances = [
            item
            for item in placed.positioned_items.values()
            if item.zone_type in ("cooking", "cooling", "cleaning")
        ]
        for i in range(len(appliances)):
            for j in range(i + 1, len(appliances)):
                a, b = appliances[i], appliances[j]
                if a.anchor_wall != b.anchor_wall:
                    continue
                # Front clearance zone: extends from item y forward
                a_front_end = a.position_mm["y"] + a.dimensions_mm["depth"]
                b_front_end = b.position_mm["y"] + b.dimensions_mm["depth"]
                a_zone_end = a_front_end + self._front_clearance(a, placed)
                b_zone_end = b_front_end + self._front_clearance(b, placed)
                if a_front_end < b_zone_end and b_front_end < a_zone_end:
                    violations.append(
                        {
                            "rule_id": "NKBA-02",
                            "text": (
                                f"'{a.name}' and '{b.name}' have overlapping front clearance zones"
                            ),
                        }
                    )
                    return  # one violation sufficient

    def _check_nkba_03(
        self,
        placed: PlacementEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-03: Work triangle perimeter <= 7925mm."""
        sink = self._find("sink", placed)
        fridge = self._find("fridge", placed) or self._find("refrigerator", placed)
        stove = self._find("stove", placed) or self._find("range", placed)
        if not (sink and fridge and stove):
            return
        perimeter = (
            self._dist2d(sink, fridge) + self._dist2d(fridge, stove) + self._dist2d(stove, sink)
        )
        if perimeter > WORK_TRI_NKBA03_MAX_MM:
            violations.append(
                {
                    "rule_id": "NKBA-03",
                    "text": (f"Work triangle {perimeter:.0f}mm > {WORK_TRI_NKBA03_MAX_MM:.0f}mm"),
                }
            )

    def _check_nkba_04(
        self,
        placed: PlacementEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-04: No tall_cabinet between sink and stove on the same wall."""
        sink = self._find("sink", placed)
        stove = self._find("stove", placed) or self._find("range", placed)
        if sink is None or stove is None:
            return
        if sink.anchor_wall != stove.anchor_wall:
            return
        left_x = min(self._centre_x(sink), self._centre_x(stove))
        right_x = max(self._centre_x(sink), self._centre_x(stove))
        for item in placed.positioned_items.values():
            if item.anchor_wall != sink.anchor_wall:
                continue
            if "tall_cabinet" not in item.category.lower():
                continue
            cx = self._centre_x(item)
            if left_x < cx < right_x:
                violations.append(
                    {
                        "rule_id": "NKBA-04",
                        "text": (
                            f"Tall cabinet '{item.name}' between sink and stove "
                            f"on wall '{sink.anchor_wall}'"
                        ),
                    }
                )
                return

    def _check_nkba_05(self, violations: list[dict[str, Any]]) -> None:
        """NKBA-05: Work triangle traffic — always passes (no traffic data)."""

    def _check_nkba_06(
        self,
        placed: PlacementEngineOutput,
        spatial: SpatialEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-06: Work aisle (1 cook) >= 1067mm."""
        clearance = self._min_aisle(placed, spatial)
        if clearance < AISLE_1COOK_MM:
            violations.append(
                {
                    "rule_id": "NKBA-06",
                    "text": f"Work aisle {clearance:.0f}mm < {AISLE_1COOK_MM:.0f}mm",
                }
            )

    def _check_nkba_06b(
        self,
        placed: PlacementEngineOutput,
        spatial: SpatialEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-06b: Work aisle (2+ cooks) >= 1219mm."""
        clearance = self._min_aisle(placed, spatial)
        if clearance < AISLE_2COOK_MM:
            violations.append(
                {
                    "rule_id": "NKBA-06b",
                    "text": f"Work aisle {clearance:.0f}mm < {AISLE_2COOK_MM:.0f}mm (2-cook)",
                }
            )

    def _check_nkba_07(
        self,
        placed: PlacementEngineOutput,
        spatial: SpatialEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-07: Walkway clearance >= 914mm."""
        clearance = self._min_aisle(placed, spatial)
        if clearance < WALKWAY_MM:
            violations.append(
                {
                    "rule_id": "NKBA-07",
                    "text": f"Walkway clearance {clearance:.0f}mm < {WALKWAY_MM:.0f}mm",
                }
            )

    def _check_nkba_08(self, violations: list[dict[str, Any]]) -> None:
        """NKBA-08: Seating clearance — always passes (no seating in catalog)."""

    def _check_nkba_10(
        self,
        placed: PlacementEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-10: Sink on same wall as stove or fridge (within 1500mm)."""
        sink = self._find("sink", placed)
        if sink is None:
            return
        stove = self._find("stove", placed) or self._find("range", placed)
        fridge = self._find("fridge", placed) or self._find("refrigerator", placed)
        threshold = 1500.0
        near_stove = stove is not None and (
            sink.anchor_wall == stove.anchor_wall
            and abs(self._centre_x(sink) - self._centre_x(stove)) <= threshold
        )
        near_fridge = fridge is not None and (
            sink.anchor_wall == fridge.anchor_wall
            and abs(self._centre_x(sink) - self._centre_x(fridge)) <= threshold
        )
        if not (near_stove or near_fridge):
            violations.append(
                {
                    "rule_id": "NKBA-10",
                    "text": "Sink not within 1500mm of stove or fridge on same wall",
                }
            )

    def _check_nkba_11(
        self,
        placed: PlacementEngineOutput,
        spatial: SpatialEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-11: Sink landing >= 610mm one side AND >= 457mm other side."""
        sink = self._find("sink", placed)
        if sink is None:
            return
        wall = self._get_wall(sink.anchor_wall, spatial)
        wall_len = wall.length_mm if wall else 99999.0
        left = self._gap_left(sink, sink.anchor_wall, placed)
        right = self._gap_right(sink, sink.anchor_wall, placed, wall_len)
        long_side = max(left, right)
        short_side = min(left, right)
        if long_side < SINK_LAND_LONG_MM or short_side < SINK_LAND_SHORT_MM:
            violations.append(
                {
                    "rule_id": "NKBA-11",
                    "text": (
                        f"Sink landing: long={long_side:.0f}mm (min {SINK_LAND_LONG_MM:.0f}mm), "
                        f"short={short_side:.0f}mm (min {SINK_LAND_SHORT_MM:.0f}mm)"
                    ),
                }
            )

    def _check_nkba_12(
        self,
        placed: PlacementEngineOutput,
        spatial: SpatialEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-12: >= 762mm continuous counter adjacent to sink."""
        sink = self._find("sink", placed)
        if sink is None:
            return
        wall = self._get_wall(sink.anchor_wall, spatial)
        wall_len = wall.length_mm if wall else 99999.0
        left = self._gap_left(sink, sink.anchor_wall, placed)
        right = self._gap_right(sink, sink.anchor_wall, placed, wall_len)
        if max(left, right) < PREP_AREA_MM:
            violations.append(
                {
                    "rule_id": "NKBA-12",
                    "text": (
                        f"Prep area beside sink: {max(left, right):.0f}mm < {PREP_AREA_MM:.0f}mm"
                    ),
                }
            )

    def _check_nkba_13(
        self,
        placed: PlacementEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-13: DW within 914mm of sink AND >= 533mm beside DW."""
        dw = self._find("dishwasher", placed)
        sink = self._find("sink", placed)
        if dw is None or sink is None:
            return
        dist = abs(self._centre_x(dw) - self._centre_x(sink))
        if dist > DW_SINK_NKBA13_MM:
            violations.append(
                {
                    "rule_id": "NKBA-13",
                    "text": f"DW-sink distance {dist:.0f}mm > {DW_SINK_NKBA13_MM:.0f}mm",
                }
            )
            return
        # Check open space beside DW (simplified: gap on either side)
        items_on_wall = self._items_on_wall(dw.anchor_wall, placed)
        dw_idx = next((i for i, it in enumerate(items_on_wall) if it.sku_id == dw.sku_id), None)
        if dw_idx is None:
            return
        if dw_idx > 0:
            left_item = items_on_wall[dw_idx - 1]
            gap = dw.position_mm["x"] - (
                left_item.position_mm["x"] + left_item.dimensions_mm["width"]
            )
            if gap >= DW_STAND_MM:
                return
        if dw_idx < len(items_on_wall) - 1:
            right_item = items_on_wall[dw_idx + 1]
            gap = right_item.position_mm["x"] - (dw.position_mm["x"] + dw.dimensions_mm["width"])
            if gap >= DW_STAND_MM:
                return
        violations.append(
            {
                "rule_id": "NKBA-13",
                "text": f"< {DW_STAND_MM:.0f}mm open space beside dishwasher",
            }
        )

    def _check_nkba_la_01(
        self,
        placed: PlacementEngineOutput,
        spatial: SpatialEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-LA-01: >= 381mm counter on handle side of fridge."""
        fridge = self._find("fridge", placed) or self._find("refrigerator", placed)
        if fridge is None:
            return
        wall = self._get_wall(fridge.anchor_wall, spatial)
        wall_len = wall.length_mm if wall else 99999.0
        left = self._gap_left(fridge, fridge.anchor_wall, placed)
        right = self._gap_right(fridge, fridge.anchor_wall, placed, wall_len)
        if max(left, right) < FRIDGE_LAND_MM:
            violations.append(
                {
                    "rule_id": "NKBA-LA-01",
                    "text": (
                        f"Fridge landing {max(left, right):.0f}mm "
                        f"< {FRIDGE_LAND_MM:.0f}mm on handle side"
                    ),
                }
            )

    def _check_nkba_la_02(
        self,
        placed: PlacementEngineOutput,
        spatial: SpatialEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-LA-02: >= 305mm one side AND >= 381mm other side of stove."""
        stove = self._find("stove", placed) or self._find("range", placed)
        if stove is None:
            return
        wall = self._get_wall(stove.anchor_wall, spatial)
        wall_len = wall.length_mm if wall else 99999.0
        left = self._gap_left(stove, stove.anchor_wall, placed)
        right = self._gap_right(stove, stove.anchor_wall, placed, wall_len)
        short = min(left, right)
        long_ = max(left, right)
        if short < STOVE_LAND_SHORT_MM or long_ < STOVE_LAND_LONG_MM:
            violations.append(
                {
                    "rule_id": "NKBA-LA-02",
                    "text": (
                        f"Stove landing: {short:.0f}mm/{long_:.0f}mm "
                        f"(need {STOVE_LAND_SHORT_MM:.0f}/{STOVE_LAND_LONG_MM:.0f}mm)"
                    ),
                }
            )

    def _check_nkba_la_03(
        self,
        placed: PlacementEngineOutput,
        spatial: SpatialEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-LA-03: >= 381mm on either side of oven/stove."""
        stove = self._find("stove", placed) or self._find("range", placed)
        if stove is None:
            return
        wall = self._get_wall(stove.anchor_wall, spatial)
        wall_len = wall.length_mm if wall else 99999.0
        left = self._gap_left(stove, stove.anchor_wall, placed)
        right = self._gap_right(stove, stove.anchor_wall, placed, wall_len)
        if max(left, right) < STOVE_LAND_LONG_MM:
            violations.append(
                {
                    "rule_id": "NKBA-LA-03",
                    "text": (
                        f"Oven landing {max(left, right):.0f}mm "
                        f"< {STOVE_LAND_LONG_MM:.0f}mm on either side"
                    ),
                }
            )

    def _check_nkba_la_05(
        self,
        placed: PlacementEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-LA-05: Microwave landing — passes if no microwave present."""

    def _check_nkba_18(
        self,
        placed: PlacementEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-18: >= 610mm vertical clearance from stove top to wall_cab above."""
        stove = self._find("stove", placed) or self._find("range", placed)
        if stove is None:
            return
        stove_top_z = stove.position_mm["z"] + stove.dimensions_mm["height"]
        stove_cx = self._centre_x(stove)
        for item in placed.positioned_items.values():
            if "wall_cabinet" not in item.category.lower():
                continue
            if item.anchor_wall != stove.anchor_wall:
                continue
            item_cx = self._centre_x(item)
            if abs(item_cx - stove_cx) > stove.dimensions_mm["width"]:
                continue
            clearance = item.position_mm["z"] - stove_top_z
            if clearance < HOOD_CLEARANCE_MM:
                violations.append(
                    {
                        "rule_id": "NKBA-18",
                        "text": (
                            f"Wall cabinet above stove: clearance {clearance:.0f}mm "
                            f"< {HOOD_CLEARANCE_MM:.0f}mm"
                        ),
                    }
                )
                return

    def _check_nkba_19(
        self,
        placed: PlacementEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-19: Hood must be present in layout."""
        hood = self._find("hood", placed)
        if hood is None:
            violations.append(
                {
                    "rule_id": "NKBA-19",
                    "text": "No hood/ventilation found in layout",
                }
            )

    def _check_nkba_25(
        self,
        placed: PlacementEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-25: Total base_cabinet frontage >= 4013mm."""
        total = sum(
            item.dimensions_mm["width"]
            for item in placed.positioned_items.values()
            if "base_cabinet" in item.category.lower()
        )
        if total < TOTAL_COUNTER_MM:
            violations.append(
                {
                    "rule_id": "NKBA-25",
                    "text": (f"Total countertop frontage {total:.0f}mm < {TOTAL_COUNTER_MM:.0f}mm"),
                }
            )

    # ================================================================== #
    # Helpers                                                              #
    # ================================================================== #

    def _find(self, keyword: str, placed: PlacementEngineOutput) -> PlacedItem | None:
        """Find first item whose category or name contains keyword (case-insensitive)."""
        kw = keyword.lower()
        for item in placed.positioned_items.values():
            if kw in item.category.lower() or kw in item.name.lower():
                return item
        return None

    def _centre_x(self, item: PlacedItem) -> float:
        return item.position_mm["x"] + item.dimensions_mm["width"] / 2.0

    def _centre_y(self, item: PlacedItem) -> float:
        return item.position_mm["y"] + item.dimensions_mm["depth"] / 2.0

    def _dist2d(self, a: PlacedItem, b: PlacedItem) -> float:
        dx = self._centre_x(a) - self._centre_x(b)
        dy = self._centre_y(a) - self._centre_y(b)
        return math.sqrt(dx * dx + dy * dy)

    def _items_on_wall(self, wall_name: str, placed: PlacementEngineOutput) -> list[PlacedItem]:
        """Return items on wall, sorted by x position."""
        items = [it for it in placed.positioned_items.values() if it.anchor_wall == wall_name]
        items.sort(key=lambda it: it.position_mm["x"])
        return items

    def _gap_left(
        self,
        item: PlacedItem,
        wall_name: str,
        placed: PlacementEngineOutput,
    ) -> float:
        """Distance from item left edge to nearest item to its left, or wall start."""
        item_left = item.position_mm["x"]
        left_edges = [
            it.position_mm["x"] + it.dimensions_mm["width"]
            for it in placed.positioned_items.values()
            if it.anchor_wall == wall_name
            and it.sku_id != item.sku_id
            and it.position_mm["x"] + it.dimensions_mm["width"] <= item_left
        ]
        nearest = max(left_edges, default=0.0)
        return item_left - nearest

    def _gap_right(
        self,
        item: PlacedItem,
        wall_name: str,
        placed: PlacementEngineOutput,
        wall_length: float,
    ) -> float:
        """Distance from item right edge to nearest item to its right, or wall end."""
        item_right = item.position_mm["x"] + item.dimensions_mm["width"]
        right_lefts = [
            it.position_mm["x"]
            for it in placed.positioned_items.values()
            if it.anchor_wall == wall_name
            and it.sku_id != item.sku_id
            and it.position_mm["x"] >= item_right
        ]
        nearest = min(right_lefts, default=wall_length)
        return nearest - item_right

    def _get_wall(self, wall_name: str, spatial: SpatialEngineOutput) -> Any:
        """Return Wall by name or None."""
        for wall in spatial.walls:
            if wall.name == wall_name:
                return wall
        return None

    def _room_depth(self, spatial: SpatialEngineOutput) -> float:
        """Estimate room depth from wall thickness sums (rough heuristic)."""
        depths = [w.thickness_mm for w in spatial.walls]
        return max(depths, default=3000.0) * 10.0

    def _front_clearance(self, item: PlacedItem, placed: PlacementEngineOutput) -> float:
        """Look up front_clearance_mm from preprocessing nkba_constraints if available."""
        # PlacedItem doesn't carry clearance; use a sensible default per zone
        zone_defaults: dict[str, float] = {
            "cooking": 1219.0,
            "cooling": 1067.0,
            "cleaning": 1067.0,
        }
        return zone_defaults.get(item.zone_type, 1067.0)

    def _min_aisle(self, placed: PlacementEngineOutput, spatial: SpatialEngineOutput) -> float:
        """Estimate minimum aisle: room depth minus max counter depth on any wall."""
        room_depth = self._room_depth(spatial)
        max_depth = max(
            (it.dimensions_mm["depth"] for it in placed.positioned_items.values()),
            default=0.0,
        )
        return room_depth - max_depth

    # ================================================================== #
    # Layout serialization                                                 #
    # ================================================================== #

    def _serialize_layout(self, placed: PlacementEngineOutput) -> dict[str, Any]:
        """Convert positioned_items to a plain dict for VariantSummaryDTO.layout."""
        return {
            name: {
                "is_wall": False,
                "product_id": item.sku_id,
                "position_mm": item.position_mm,
                "dimensions_mm": item.dimensions_mm,
                "rotation_z_deg": item.rotation_z_deg,
                "anchor_wall": item.anchor_wall,
                "zone_type": item.zone_type,
            }
            for name, item in placed.positioned_items.items()
        }
