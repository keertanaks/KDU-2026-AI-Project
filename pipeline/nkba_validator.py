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
from utils.rationale_lookup import generate_rationale

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
LAYOUT04_ADJ_MM: float = 1200.0  # base_cabinet adjacency threshold for LAYOUT-04
Z_LEVEL_SPLIT_MM: float = 500.0  # items below this z are floor-level, above are wall-level
WALKWAY_MIN_SINGLE_COOK_MM: float = 1067.0  # NKBA-WW-01 single-cook walkway minimum
WALKWAY_MIN_MULTI_COOK_MM: float = 1219.0  # NKBA-WW-01 multi-cook walkway minimum

# Keywords for items that are self-supporting floor-level run units.
# These count toward the continuous run (LAYOUT-03) and do not trigger
# LAYOUT-04 adjacency failures (they are their own base-level support).
_FLOOR_RUN_KW: tuple[str, ...] = (
    "base_cabinet",
    "corner_cabinet",
    "sink",
    "dishwasher",
    "stove",
    "range",
    "cooktop",
    "fridge",
    "refrigerator",
    "tall_cabinet",
)
# Truly standalone floor-level appliances — self-supporting, no adjacent base cabinet
# required. Sink is intentionally excluded: it is an integrated sink-base fixture
# whose LAYOUT-04 compliance is checked separately (integrated + adjacent run unit).
_STANDALONE_APPLIANCE_KW: tuple[str, ...] = (
    "dishwasher",
    "stove",
    "range",
    "cooktop",
    "fridge",
    "refrigerator",
)

# Sink-as-integrated-base-fixture: valid height range (mm) matching base cabinet height.
# SKU-S01/SKU-S02 are modeled at 900mm — check within ±100mm.
_SINK_BASE_HEIGHT_MIN_MM: float = 800.0
_SINK_BASE_HEIGHT_MAX_MM: float = 1000.0

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
    "NKBA-WW-01": 0.10,
}

# Spillover log entries that are purely informational — do NOT count against score.
_INFORMATIONAL_LOG_PREFIXES: tuple[str, ...] = (
    "END-FILLER:",
    "SINK-BASE-IMPLIED:",
    "TYPOLOGY-PROTECT:",
    "RETRY-KEPT-",
    "COLOCATE:",
    "VARIANT-COLLAPSED",
)

# Score caps applied after the raw formula.
_SCORE_CAP_ANY_VIOLATION: float = 0.95  # any rule violated
_SCORE_CAP_COLLISION: float = 0.80  # real floor-level overlap
_SCORE_CAP_LAYOUT_RUN: float = 0.88  # LAYOUT-03 or LAYOUT-04


# ============================================================================
# Validator
# ============================================================================


class NKBAValidator:
    """Run all 32 NKBA/project rules and produce a scored VariantSummaryDTO."""

    def validate(
        self,
        placed: PlacementEngineOutput,
        spatial: SpatialEngineOutput,
        preprocessing: PreprocessingOutput,
    ) -> VariantSummaryDTO:
        """Evaluate all rules and return a fully scored VariantSummaryDTO."""
        violations: list[dict[str, Any]] = []

        # ── 12 Project rules (weighted) ──────────────────────────────────
        self._check_nkba_cl_01(placed, spatial, violations)
        self._check_nkba_cl_02(placed, spatial, violations)
        self._check_workflow_01(placed, spatial, violations)
        self._check_workflow_02(placed, violations)
        self._check_workflow_03(placed, spatial, violations)
        self._check_layout_01(placed, spatial, violations)
        self._check_layout_02(placed, violations)
        self._check_layout_03(placed, spatial, violations)
        self._check_layout_04(placed, violations)
        self._check_layout_05(placed, spatial, violations)
        self._check_layout_06(placed, spatial, violations)
        self._check_nkba_ww_01(placed, spatial, preprocessing, violations)

        # ── 20 Official NKBA rules (unweighted, count only) ──────────────
        self._check_nkba_01(spatial, violations)
        self._check_nkba_02(placed, violations)
        self._check_nkba_03(placed, spatial, violations)
        self._check_nkba_04(placed, violations)
        self._check_nkba_05(violations)
        self._check_nkba_06(placed, spatial, violations)
        self._check_nkba_06b(placed, spatial, violations)
        self._check_nkba_07(placed, spatial, violations)
        self._check_nkba_08(violations)
        self._check_nkba_10(placed, spatial, violations)
        self._check_nkba_11(placed, spatial, violations)
        self._check_nkba_12(placed, spatial, violations)
        self._check_nkba_13(placed, spatial, violations)
        self._check_nkba_la_01(placed, spatial, violations)
        self._check_nkba_la_02(placed, spatial, violations)
        self._check_nkba_la_03(placed, spatial, violations)
        self._check_nkba_la_05(placed, violations)
        self._check_nkba_18(placed, violations)
        self._check_nkba_19(placed, violations)
        self._check_nkba_25(placed, violations)

        total_rules = 32  # 12 project rules (weighted) + 20 official NKBA rules
        violated_ids = {v["rule_id"] for v in violations}
        passed_rules = total_rules - len(violated_ids)
        nkba_pct = passed_rules / total_rules

        # Hard spillover only — informational entries do not penalise score.
        hard_spillover_count = sum(
            1
            for entry in placed.spillover_log
            if not any(entry.startswith(p) for p in _INFORMATIONAL_LOG_PREFIXES)
        )

        # Validator-side floor-level collision detection (structured, with bbox).
        collision_pairs = self._detect_floor_collisions(placed)
        collision_count = len(collision_pairs)

        weight_penalty = sum(RULE_WEIGHTS.get(rid, 0.0) for rid in violated_ids)

        raw_score = (
            1.0
            + nkba_pct * 0.30
            - hard_spillover_count * 0.05
            - collision_count * 0.10
            - weight_penalty
        )

        # Apply severity caps — order matters; take the tightest applicable cap.
        caps_applied: list[str] = []
        score = raw_score
        if violated_ids:
            if score > _SCORE_CAP_ANY_VIOLATION:
                score = _SCORE_CAP_ANY_VIOLATION
                caps_applied.append("any_violation->0.95")
        if "LAYOUT-03" in violated_ids or "LAYOUT-04" in violated_ids:
            if score > _SCORE_CAP_LAYOUT_RUN:
                score = _SCORE_CAP_LAYOUT_RUN
                caps_applied.append("layout_run->0.88")
        if collision_count > 0:
            if score > _SCORE_CAP_COLLISION:
                score = _SCORE_CAP_COLLISION
                caps_applied.append("collision->0.80")

        score = max(0.0, min(1.0, score))

        score_debug: dict[str, Any] = {
            "raw_score": round(raw_score, 3),
            "nkba_pct": round(nkba_pct, 3),
            "hard_spillover_count": hard_spillover_count,
            "collision_count": collision_count,
            "weight_penalty": round(weight_penalty, 3),
            "caps_applied": caps_applied,
            "final_score": round(score, 3),
            "hard_violation_ids": sorted(violated_ids & set(RULE_WEIGHTS)),
            "soft_violation_ids": sorted(violated_ids - set(RULE_WEIGHTS)),
        }

        warnings = list(placed.collision_flags)
        if any("CONSTRAINT_VIOLATION" in s for s in placed.spillover_log):
            warnings.append("One or more items forced to corner — check LAYOUT-06")
        # Merge color-substitution warnings from Layer 2 so they surface in the UI.
        warnings.extend(preprocessing.color_warnings)

        layout = self._serialize_layout(placed, spatial)

        # Auto-generate rationale from violations using rule explanation lookup table
        rationale = generate_rationale(violations)

        logger.info(
            "Variant '%s': score=%.3f passed=%d/%d hard_spill=%d collisions=%d weight=%.2f caps=%s",
            placed.variant_id,
            score,
            passed_rules,
            total_rules,
            hard_spillover_count,
            collision_count,
            weight_penalty,
            caps_applied or "none",
        )
        if collision_pairs:
            for cp in collision_pairs:
                logger.warning(
                    "COLLISION-PAIR: %s(%s) x=[%.0f,%.0f] <-> %s(%s) x=[%.0f,%.0f] "
                    "overlap=%.0fmm wall=%s",
                    cp["id_a"],
                    cp["type_a"],
                    cp["bbox_a"]["x1"],
                    cp["bbox_a"]["x2"],
                    cp["id_b"],
                    cp["type_b"],
                    cp["bbox_b"]["x1"],
                    cp["bbox_b"]["x2"],
                    cp["overlap_mm"],
                    cp["wall"],
                )

        return VariantSummaryDTO(
            id=placed.variant_id,
            family="",
            score=score,
            placement_count=len(placed.positioned_items),
            nkba_compliance_pct=nkba_pct,
            spillover_count=len(placed.spillover_log),
            warnings=warnings,
            violations=violations,
            rationale=rationale,
            layout=layout,
            environment={},
            collision_pairs=collision_pairs,
            score_debug=score_debug,
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
        """NKBA-CL-01: Fridge needs >= 1067mm clear aisle in front."""
        fridge = self._find("fridge", placed) or self._find("refrigerator", placed)
        if fridge is None:
            return
        # Use aisle estimate: room depth minus total counter depth (same as NKBA-06/07)
        clearance = self._min_aisle(placed, spatial)
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
        spatial: SpatialEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """WORKFLOW-01: Sink and dishwasher centres <= 600mm apart."""
        sink = self._find("sink", placed)
        dw = self._find("dishwasher", placed)
        if sink is None or dw is None:
            return
        if sink.anchor_wall == dw.anchor_wall:
            dist = abs(self._centre_x(sink) - self._centre_x(dw))
        else:
            # Cross-wall: use global 2D distance
            dist = self._dist2d_global(sink, dw, spatial)
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
        if stove.anchor_wall != fridge.anchor_wall:
            return  # different walls — WORKFLOW-02 does not apply cross-wall
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
        spatial: SpatialEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """WORKFLOW-03: Work triangle perimeter 3962-6600mm."""
        sink = self._find("sink", placed)
        fridge = self._find("fridge", placed) or self._find("refrigerator", placed)
        stove = self._find("stove", placed) or self._find("range", placed)
        if not (sink and fridge and stove):
            return
        perimeter = (
            self._dist2d_global(sink, fridge, spatial)
            + self._dist2d_global(fridge, stove, spatial)
            + self._dist2d_global(stove, sink, spatial)
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
        # Openings use anchor direction ("north"); PlacedItem uses wall name ("north_wall")
        sink_wall_obj = self._get_wall(sink.anchor_wall, spatial)
        sink_anchor = sink_wall_obj.anchor.lower() if sink_wall_obj else sink.anchor_wall
        windows_on_wall = [
            o for o in spatial.exclusions if o.kind == "window" and o.wall == sink_anchor
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
        """LAYOUT-03: Continuous run — gaps <= 50mm except at door/window openings or END-FILLER.

        Counts ALL floor-level run units (appliances, sinks, base/tall cabinets) as
        part of the continuous run — not just base cabinets.
        An END-FILLER spillover entry on a wall marks an intentionally unfillable gap
        (no cabinet exists that fits) and excuses that wall from the rule.
        """
        opening_ranges: dict[str, list[tuple[float, float]]] = {}
        for o in spatial.exclusions:
            opening_ranges.setdefault(o.wall, []).append((o.blocked_start_mm, o.blocked_end_mm))

        # Walls where gap-fill logged an intentionally unfillable gap
        end_filler_walls: set[str] = set()
        for entry in placed.spillover_log:
            if entry.startswith("END-FILLER:") and " on " in entry:
                try:
                    wall_part = entry.split(" on ")[1].split(" (")[0].strip()
                    end_filler_walls.add(wall_part)
                except IndexError:
                    pass

        for wall in spatial.walls:
            if not wall.has_cabinets:
                continue
            # All floor-level run units count toward the continuous run
            items = [
                it
                for it in self._items_on_wall(wall.name, placed)
                if it.position_mm["z"] < 500 and self._is_floor_run_unit(it)
            ]
            if len(items) < 2:
                continue
            # END-FILLER logged for this wall → at least one gap is intentionally open
            if wall.name in end_filler_walls:
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
        """LAYOUT-04: Verify sink-base support and flag isolation.

        Dishwasher, stove/range/cooktop, and fridge are fully standalone floor-level
        units — no adjacency requirement.

        Sink is an integrated sink-base fixture (SKU-S01/S02: height≈900mm,
        wall-attached).  It passes LAYOUT-04 (SINK-BASE-IMPLIED) when:
          (a) its height is within base-cabinet range, AND
          (b) at least one other floor-level run unit is within CONTINUOUS_GAP_MM
              on the same wall (i.e. it participates in the continuous run).
        If the sink is isolated — no adjacent run unit — the rule fires.
        """
        for item in placed.positioned_items.values():
            combined = (item.category + " " + item.name).lower()
            if "sink" not in combined:
                continue
            # Integrated sink-base fixture check
            if self._sink_is_integrated_base_fixture(item):
                if self._sink_has_adjacent_run_unit(item, placed):
                    continue  # SINK-BASE-IMPLIED: passes LAYOUT-04
            # Sink is either non-integrated height or isolated from the run
            violations.append(
                {
                    "rule_id": "LAYOUT-04",
                    "text": (
                        f"'{item.name}' sink is isolated from floor-level run "
                        f"(no adjacent run unit within {CONTINUOUS_GAP_MM:.0f}mm) "
                        f"on wall '{item.anchor_wall}'"
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
            items = [
                it for it in self._items_on_wall(wall.name, placed) if it.position_mm["z"] < 500
            ]
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

    def _check_nkba_ww_01(
        self,
        placed: PlacementEngineOutput,
        spatial: SpatialEngineOutput,
        preprocessing: PreprocessingOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-WW-01: Walkway between facing cabinet runs (or run and island) >= threshold.

        Single-cook kitchen: walkway must be >= WALKWAY_MIN_SINGLE_COOK_MM (1067mm).
        Multi-cook kitchen:  walkway must be >= WALKWAY_MIN_MULTI_COOK_MM  (1219mm).

        Cook count is read from preprocessing.nkba_constraints["num_cooks"]; defaults to 1.
        Returns without firing if no facing cabinet arrangement is detected (single-wall layouts).
        """
        num_cooks = int(preprocessing.nkba_constraints.get("num_cooks", 1))
        min_walkway = WALKWAY_MIN_MULTI_COOK_MM if num_cooks > 1 else WALKWAY_MIN_SINGLE_COOK_MM
        walkway = self._compute_facing_walkway(placed, spatial)
        if walkway is None:
            return  # no facing arrangement — rule does not apply
        if walkway < min_walkway:
            cook_label = "multi" if num_cooks > 1 else "single"
            violations.append(
                {
                    "rule_id": "NKBA-WW-01",
                    "text": (f"Walkway {walkway:.0f}mm < {min_walkway:.0f}mm ({cook_label}-cook)"),
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
                # Hood is intentionally above stove — skip this pair
                a_tag = (a.category + " " + a.name).lower()
                b_tag = (b.category + " " + b.name).lower()
                if ("hood" in a_tag and ("stove" in b_tag or "range" in b_tag)) or (
                    "hood" in b_tag and ("stove" in a_tag or "range" in a_tag)
                ):
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
        spatial: SpatialEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-03: Work triangle perimeter <= 7925mm."""
        sink = self._find("sink", placed)
        fridge = self._find("fridge", placed) or self._find("refrigerator", placed)
        stove = self._find("stove", placed) or self._find("range", placed)
        if not (sink and fridge and stove):
            return
        perimeter = (
            self._dist2d_global(sink, fridge, spatial)
            + self._dist2d_global(fridge, stove, spatial)
            + self._dist2d_global(stove, sink, spatial)
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
        spatial: SpatialEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-10: Sink within 1500mm of stove or fridge (global 2D distance)."""
        sink = self._find("sink", placed)
        if sink is None:
            return
        stove = self._find("stove", placed) or self._find("range", placed)
        fridge = self._find("fridge", placed) or self._find("refrigerator", placed)
        threshold = 1500.0
        near_stove = stove is not None and self._dist2d_global(sink, stove, spatial) <= threshold
        near_fridge = fridge is not None and self._dist2d_global(sink, fridge, spatial) <= threshold
        if not (near_stove or near_fridge):
            violations.append(
                {
                    "rule_id": "NKBA-10",
                    "text": "Sink not within 1500mm of stove or fridge",
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
        left = self._landing_left(sink, sink.anchor_wall, placed)
        right = self._landing_right(sink, sink.anchor_wall, placed, wall_len)
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
        left = self._landing_left(sink, sink.anchor_wall, placed)
        right = self._landing_right(sink, sink.anchor_wall, placed, wall_len)
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
        spatial: SpatialEngineOutput,
        violations: list[dict[str, Any]],
    ) -> None:
        """NKBA-13: DW within 914mm of sink AND >= 533mm beside DW."""
        dw = self._find("dishwasher", placed)
        sink = self._find("sink", placed)
        if dw is None or sink is None:
            return
        if dw.anchor_wall == sink.anchor_wall:
            dist = abs(self._centre_x(dw) - self._centre_x(sink))
        else:
            dist = self._dist2d_global(dw, sink, spatial)
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
        left = self._landing_left(fridge, fridge.anchor_wall, placed)
        right = self._landing_right(fridge, fridge.anchor_wall, placed, wall_len)
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
        left = self._landing_left(stove, stove.anchor_wall, placed)
        right = self._landing_right(stove, stove.anchor_wall, placed, wall_len)
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
        left = self._landing_left(stove, stove.anchor_wall, placed)
        right = self._landing_right(stove, stove.anchor_wall, placed, wall_len)
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

    def _compute_facing_walkway(
        self,
        placed: PlacementEngineOutput,
        spatial: SpatialEngineOutput,
    ) -> float | None:
        """Compute the minimum walkway gap between facing cabinet runs or island vs. run.

        Checks N/S wall pairs first, then E/W wall pairs, then island items.
        Only floor-level items (z < Z_LEVEL_SPLIT_MM) count toward each run depth.

        Returns:
            Minimum walkway gap in mm, or None if no facing arrangement is detected
            (i.e., single-wall layout with no island).
        """
        # ── North / South facing pair ──────────────────────────────────
        north_items = [
            it
            for w in spatial.walls
            if w.anchor.lower() == "north"
            for it in self._items_on_wall(w.name, placed)
            if it.position_mm["z"] < Z_LEVEL_SPLIT_MM
        ]
        south_items = [
            it
            for w in spatial.walls
            if w.anchor.lower() == "south"
            for it in self._items_on_wall(w.name, placed)
            if it.position_mm["z"] < Z_LEVEL_SPLIT_MM
        ]
        if north_items and south_items:
            room_depth = self._room_depth(spatial)
            depth_n = max(it.dimensions_mm["depth"] for it in north_items)
            depth_s = max(it.dimensions_mm["depth"] for it in south_items)
            return room_depth - depth_n - depth_s

        # ── East / West facing pair ─────────────────────────────────────
        east_items = [
            it
            for w in spatial.walls
            if w.anchor.lower() == "east"
            for it in self._items_on_wall(w.name, placed)
            if it.position_mm["z"] < Z_LEVEL_SPLIT_MM
        ]
        west_items = [
            it
            for w in spatial.walls
            if w.anchor.lower() == "west"
            for it in self._items_on_wall(w.name, placed)
            if it.position_mm["z"] < Z_LEVEL_SPLIT_MM
        ]
        if east_items and west_items:
            all_x = [p["x"] for w in spatial.walls for p in w.points if "x" in p]
            room_width = float(max(all_x) - min(all_x)) if all_x else 3000.0
            depth_e = max(it.dimensions_mm["depth"] for it in east_items)
            depth_w = max(it.dimensions_mm["depth"] for it in west_items)
            return room_width - depth_e - depth_w

        # ── Island vs. nearest wall run ─────────────────────────────────
        island_items = [
            it
            for it in placed.positioned_items.values()
            if "island" in it.anchor_wall.lower() and it.position_mm["z"] < Z_LEVEL_SPLIT_MM
        ]
        if island_items:
            wall_items = [
                it
                for it in placed.positioned_items.values()
                if "island" not in it.anchor_wall.lower() and it.position_mm["z"] < Z_LEVEL_SPLIT_MM
            ]
            if wall_items:
                room_depth = self._room_depth(spatial)
                island_depth = max(it.dimensions_mm["depth"] for it in island_items)
                wall_depth = max(it.dimensions_mm["depth"] for it in wall_items)
                return room_depth - island_depth - wall_depth

        return None  # single-wall layout, no island — rule does not apply

    def _detect_floor_collisions(
        self,
        placed: PlacementEngineOutput,
    ) -> list[dict[str, Any]]:
        """Detect real floor-level x-range overlaps between items on the same wall.

        Only checks items at z < Z_LEVEL_SPLIT_MM (floor level).
        All floor items on the same wall share the same y-plane (wall thickness),
        so an x-range overlap is a genuine footprint collision.

        Whitelist semantics:
          - tap/sink: always exempt (tap co-locates on sink unit).
          - hood/stove: exempt only when Z ranges do not overlap (normal case).
          - wall_cabinet/base_cabinet: exempt only when Z ranges do not overlap.
          - dishwasher/base_cabinet: NOT exempt — real overlap must be reported.
        """
        pairs: list[dict[str, Any]] = []
        floor_items = [
            (sid, item)
            for sid, item in placed.positioned_items.items()
            if item.position_mm.get("z", 0.0) < Z_LEVEL_SPLIT_MM
        ]
        for i in range(len(floor_items)):
            sid_a, a = floor_items[i]
            for j in range(i + 1, len(floor_items)):
                sid_b, b = floor_items[j]
                if a.anchor_wall != b.anchor_wall:
                    continue
                tag_a = (a.category + " " + a.name).lower()
                tag_b = (b.category + " " + b.name).lower()
                # Tap/sink: always whitelisted
                if ("tap" in tag_a and "sink" in tag_b) or ("tap" in tag_b and "sink" in tag_a):
                    continue
                # Hood/stove: exempt only when Z ranges are separated
                if ("hood" in tag_a and ("stove" in tag_b or "range" in tag_b)) or (
                    "hood" in tag_b and ("stove" in tag_a or "range" in tag_a)
                ):
                    az1, az2 = a.position_mm["z"], a.position_mm["z"] + a.dimensions_mm["height"]
                    bz1, bz2 = b.position_mm["z"], b.position_mm["z"] + b.dimensions_mm["height"]
                    if az2 <= bz1 or bz2 <= az1:
                        continue  # Z ranges do not overlap — not a real collision
                # Wall_cabinet/base_cabinet: exempt only when Z ranges are separated
                if ("wall_cabinet" in tag_a and "base_cabinet" in tag_b) or (
                    "wall_cabinet" in tag_b and "base_cabinet" in tag_a
                ):
                    az1, az2 = a.position_mm["z"], a.position_mm["z"] + a.dimensions_mm["height"]
                    bz1, bz2 = b.position_mm["z"], b.position_mm["z"] + b.dimensions_mm["height"]
                    if az2 <= bz1 or bz2 <= az1:
                        continue
                ax1 = a.position_mm["x"]
                ax2 = ax1 + a.dimensions_mm["width"]
                bx1 = b.position_mm["x"]
                bx2 = bx1 + b.dimensions_mm["width"]
                if ax2 <= bx1 or bx2 <= ax1:
                    continue  # no x overlap
                overlap = min(ax2, bx2) - max(ax1, bx1)
                pairs.append(
                    {
                        "id_a": sid_a,
                        "type_a": a.category,
                        "id_b": sid_b,
                        "type_b": b.category,
                        "bbox_a": {
                            "x1": round(ax1),
                            "x2": round(ax2),
                            "z": round(a.position_mm["z"]),
                        },
                        "bbox_b": {
                            "x1": round(bx1),
                            "x2": round(bx2),
                            "z": round(b.position_mm["z"]),
                        },
                        "wall": a.anchor_wall,
                        "overlap_mm": round(overlap),
                    }
                )
        return pairs

    @staticmethod
    def _is_floor_run_unit(item: PlacedItem) -> bool:
        """True if item occupies floor-level run space and is self-supporting."""
        combined = (item.category + " " + item.name).lower()
        return any(kw in combined for kw in _FLOOR_RUN_KW)

    @staticmethod
    def _is_standalone_appliance(item: PlacedItem) -> bool:
        """True if item is a standalone appliance that does not need adjacent base cabinet."""
        combined = (item.category + " " + item.name).lower()
        return any(kw in combined for kw in _STANDALONE_APPLIANCE_KW)

    @staticmethod
    def _sink_is_integrated_base_fixture(sink: PlacedItem) -> bool:
        """True if the sink's physical dimensions match an integrated sink-base fixture.

        SKU-S01/SKU-S02 are modeled at base-cabinet height (900mm) so they act as
        their own base-level unit without needing a separate support cabinet.
        A sink whose height is far from base cabinet height is not integrated.
        """
        h = sink.dimensions_mm.get("height", 0.0)
        return _SINK_BASE_HEIGHT_MIN_MM <= h <= _SINK_BASE_HEIGHT_MAX_MM

    def _sink_has_adjacent_run_unit(
        self,
        sink: PlacedItem,
        placed: PlacementEngineOutput,
    ) -> bool:
        """True if at least one floor-level run unit is within CONTINUOUS_GAP_MM of sink.

        Checks left and right edge gaps. Dishwasher counts as an adjacent run unit
        (it is placed next to the sink), so a sink+DW pair on the same wall passes.
        """
        sx1 = sink.position_mm["x"]
        sx2 = sx1 + sink.dimensions_mm["width"]
        for item in placed.positioned_items.values():
            if item is sink:
                continue
            if item.anchor_wall != sink.anchor_wall:
                continue
            if item.position_mm["z"] >= Z_LEVEL_SPLIT_MM:
                continue
            if not self._is_floor_run_unit(item):
                continue
            ix1 = item.position_mm["x"]
            ix2 = ix1 + item.dimensions_mm["width"]
            gap = max(0.0, max(sx1, ix1) - min(sx2, ix2))
            if gap <= CONTINUOUS_GAP_MM:
                return True
        return False

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
        """Same-wall local-coord 2D distance (for same-wall checks only)."""
        dx = self._centre_x(a) - self._centre_x(b)
        dy = self._centre_y(a) - self._centre_y(b)
        return math.sqrt(dx * dx + dy * dy)

    def _global_xy(self, item: PlacedItem, spatial: SpatialEngineOutput) -> tuple[float, float]:
        """Convert item wall-local left-edge coords to global 2D floor-plan center (x, y).

        Wall-local coords: x = left edge along wall, y = wall thickness (~100mm).
        Returns true room-coordinate center so cross-wall distances are correct.
        """
        local_x = item.position_mm["x"]
        w = item.dimensions_mm["width"]
        d = item.dimensions_mm["depth"]
        wall = self._get_wall(item.anchor_wall, spatial)
        if wall is None:
            return (local_x + w / 2.0, item.position_mm.get("y", 0.0) + d / 2.0)
        anchor = wall.anchor.lower()
        try:
            if anchor == "north":
                wall_y = max(p["y"] for p in wall.points)
                return (local_x + w / 2.0, wall_y - d / 2.0)
            elif anchor == "south":
                wall_y = min(p["y"] for p in wall.points)
                return (local_x + w / 2.0, wall_y + d / 2.0)
            elif anchor == "east":
                wall_x = max(p["x"] for p in wall.points)
                return (wall_x - d / 2.0, local_x + w / 2.0)
            elif anchor == "west":
                wall_x = min(p["x"] for p in wall.points)
                return (wall_x + d / 2.0, local_x + w / 2.0)
        except (KeyError, ValueError):
            pass
        return (local_x + w / 2.0, item.position_mm.get("y", 0.0) + d / 2.0)

    def _dist2d_global(
        self,
        a: PlacedItem,
        b: PlacedItem,
        spatial: SpatialEngineOutput,
    ) -> float:
        """Global 2D Euclidean distance between two item centers (works across walls)."""
        ax, ay = self._global_xy(a, spatial)
        bx, by = self._global_xy(b, spatial)
        return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)

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

    @staticmethod
    def _edge_gap(a1: float, a2: float, b1: float, b2: float) -> float:
        """Gap between two 1D intervals [a1,a2] and [b1,b2]. 0 if they touch/overlap."""
        return max(0.0, max(a1, b1) - min(a2, b2))

    def _is_counter_provider(self, item: PlacedItem) -> bool:
        """True if item provides counter/landing surface.

        Base cabinets and dishwashers both sit under the continuous countertop
        and provide usable landing area above them.
        """
        combined = (item.category + " " + item.name).lower()
        return "base_cabinet" in combined or "dishwasher" in combined

    def _landing_left(
        self,
        item: PlacedItem,
        wall_name: str,
        placed: PlacementEngineOutput,
    ) -> float:
        """Counter/landing area to the left of item.

        Walks left from the item edge. Base cabinets and empty gaps both count
        as usable counter space. Stops at the first non-counter item (appliance,
        tall cabinet) or the wall start.
        """
        item_left = item.position_mm["x"]
        blockers = [
            it
            for it in placed.positioned_items.values()
            if it.anchor_wall == wall_name
            and it.sku_id != item.sku_id
            and it.position_mm["z"] < 500
            and not self._is_counter_provider(it)
            and it.position_mm["x"] + it.dimensions_mm["width"] <= item_left + CONTINUOUS_GAP_MM
        ]
        if not blockers:
            return item_left
        nearest = max(blockers, key=lambda it: it.position_mm["x"] + it.dimensions_mm["width"])
        return max(0.0, item_left - (nearest.position_mm["x"] + nearest.dimensions_mm["width"]))

    def _landing_right(
        self,
        item: PlacedItem,
        wall_name: str,
        placed: PlacementEngineOutput,
        wall_length: float,
    ) -> float:
        """Counter/landing area to the right of item.

        Walks right from the item edge. Base cabinets and empty gaps both count
        as usable counter space. Stops at the first non-counter item or wall end.
        """
        item_right = item.position_mm["x"] + item.dimensions_mm["width"]
        blockers = [
            it
            for it in placed.positioned_items.values()
            if it.anchor_wall == wall_name
            and it.sku_id != item.sku_id
            and it.position_mm["z"] < 500
            and not self._is_counter_provider(it)
            and it.position_mm["x"] >= item_right - CONTINUOUS_GAP_MM
        ]
        if not blockers:
            return wall_length - item_right
        nearest = min(blockers, key=lambda it: it.position_mm["x"])
        return max(0.0, nearest.position_mm["x"] - item_right)

    def _get_wall(self, wall_name: str, spatial: SpatialEngineOutput) -> Any:
        """Return Wall by name or None."""
        for wall in spatial.walls:
            if wall.name == wall_name:
                return wall
        return None

    def _room_depth(self, spatial: SpatialEngineOutput) -> float:
        """Derive room depth from the Y-extent of all wall points."""
        all_y = [p["y"] for w in spatial.walls for p in w.points if "y" in p]
        if all_y:
            return float(max(all_y) - min(all_y))
        return 3000.0

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

    def _serialize_layout(
        self,
        placed: PlacementEngineOutput,
        spatial: SpatialEngineOutput,
    ) -> dict[str, Any]:
        """Convert positioned_items from wall-local left-edge to global room center coords.

        The placement engine stores items in wall-local coordinates:
          - x  = left-edge distance along the wall (0 → wall_length)
          - y  = wall thickness (~100mm placeholder)
          - z  = bottom height of the item

        The renderer (layout.py) expects global center coordinates:
          - x, y = center of item in the global floor plan
          - z    = vertical center of item

        Rotation is also set here based on which wall the item is anchored to:
          north→180°, south→0°, east→90°, west→270°.
        """
        wall_map = {wall.name: wall for wall in spatial.walls}
        result: dict[str, Any] = {}
        for name, item in placed.positioned_items.items():
            wall = wall_map.get(item.anchor_wall)
            if wall is not None:
                pos, rot = self._to_global_center(item, wall)
            else:
                # Wall not in spatial (e.g., no-cabinet wall) — leave as-is
                pos = dict(item.position_mm)
                rot = item.rotation_z_deg
            result[name] = {
                "is_wall": False,
                "product_id": item.sku_id,
                "position_mm": pos,
                "dimensions_mm": item.dimensions_mm,
                "rotation_z_deg": rot,
                "anchor_wall": item.anchor_wall,
                "zone_type": item.zone_type,
            }
        return result

    def _to_global_center(
        self,
        item: PlacedItem,
        wall: Any,
    ) -> tuple[dict[str, float], float]:
        """Convert one item from wall-local left-edge to global room center coords.

        Args:
            item: PlacedItem with local coords (x=left edge, y=thickness, z=bottom)
            wall: Wall object with global points and anchor direction

        Returns:
            (position_mm_global_center, rotation_z_deg)
        """
        local_x = item.position_mm["x"]  # left edge along wall
        local_z_bot = item.position_mm["z"]  # bottom height
        w = item.dimensions_mm["width"]
        d = item.dimensions_mm["depth"]
        h = item.dimensions_mm["height"]
        anchor = wall.anchor.lower()

        gz = local_z_bot + h / 2.0  # vertical center

        try:
            if anchor == "north":
                wall_y = max(p["y"] for p in wall.points)
                gx = local_x + w / 2.0  # center along x-axis (E-W)
                gy = wall_y - d / 2.0  # step inward (south) by half-depth
                rot = 180.0
            elif anchor == "south":
                wall_y = min(p["y"] for p in wall.points)
                gx = local_x + w / 2.0
                gy = wall_y + d / 2.0  # step inward (north) by half-depth
                rot = 0.0
            elif anchor == "east":
                wall_x = max(p["x"] for p in wall.points)
                gx = wall_x - d / 2.0  # step inward (west) by half-depth
                gy = local_x + w / 2.0  # center along y-axis (N-S)
                rot = 90.0
            elif anchor == "west":
                wall_x = min(p["x"] for p in wall.points)
                gx = wall_x + d / 2.0  # step inward (east) by half-depth
                gy = local_x + w / 2.0
                rot = 270.0
            else:
                # Unknown anchor — best-effort passthrough
                gx = local_x + w / 2.0
                gy = item.position_mm["y"]
                rot = item.rotation_z_deg
        except (KeyError, ValueError, StopIteration):
            logger.warning(
                "Could not compute global center for '%s' on wall '%s'; using local coords",
                item.sku_id,
                item.anchor_wall,
            )
            gx = local_x + w / 2.0
            gy = item.position_mm["y"]
            rot = item.rotation_z_deg

        return {"x": gx, "y": gy, "z": gz}, rot
