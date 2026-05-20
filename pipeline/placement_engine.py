"""Layer 4: Placement Engine — resolve semantic terms to exact mm coordinates.

Pure Python math module. No LLM calls, no Anthropic imports.
Consumes ZonePlannerOutput (semantic) and emits PlacementEngineOutput (mm).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from dtos.contracts import (
    SKU,
    PlacedItem,
    PlacementEngineOutput,
    PreprocessingOutput,
    Segment,
    SpatialEngineOutput,
    Wall,
    ZonePlannerOutput,
)
from utils.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Template-based placement (Checkpoint A — I-shape first)
# ============================================================================


@dataclass
class WallRunTemplate:
    """Deterministic placement template for a single wall.

    Defines the ordered zone sequence and packing direction. A cursor walks
    the zones, placing one SKU per zone from preprocessing.zone_groups. Items
    pack contiguously by construction — no internal gaps possible.

    start_offset_mm: how far from the cursor's starting position to skip
    before placing items. Used on the L/U secondary wall to avoid the corner
    cabinet's 900mm projection from the perpendicular (primary) wall.
    """

    wall_name: str
    zones: list[str] = field(default_factory=list)
    reverse_axis: bool = False
    compactness: str = "balanced"  # spacious | balanced | compact
    start_offset_mm: float = 0.0


# Map zone names in templates → keywords to find the SKU in zone_groups
_TPL_ZONE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "fridge": ("fridge", "refrigerator"),
    "sink": ("sink",),
    "dishwasher": ("dishwasher",),
    "stove": ("stove", "range", "cooktop"),
    "hood": ("hood", "vent"),
    "tall": ("tall_cabinet", "pantry"),
    "base": ("base_cabinet",),
    "corner": ("corner_cabinet", "blind_corner"),
    "wall_cab": ("wall_cabinet",),
}

# Preferred SKU width per zone per compactness — drives variant diversity.
_TPL_TARGET_WIDTH: dict[str, dict[str, float]] = {
    "fridge":     {"spacious": 750, "balanced": 700, "compact": 600},
    "sink":       {"spacious": 900, "balanced": 600, "compact": 600},
    "dishwasher": {"spacious": 600, "balanced": 600, "compact": 600},
    "stove":      {"spacious": 750, "balanced": 600, "compact": 600},
    "base":       {"spacious": 1200, "balanced": 900, "compact": 450},
    "corner":     {"spacious": 900, "balanced": 900, "compact": 900},
    "tall":       {"spacious": 800, "balanced": 600, "compact": 600},
}

# Map template zone name → zone_type for PlacedItem
_TPL_ZONE_TYPE: dict[str, str] = {
    "fridge": "cooling",
    "sink": "cleaning",
    "dishwasher": "cleaning",
    "stove": "cooking",
    "hood": "cooking",
    "tall": "storage",
    "base": "preparation",
    "corner": "preparation",
    "wall_cab": "storage",
}

# Tail-fill cap by variant compactness (mm of additional base cabinets).
_TPL_FILL_CAP_MM: dict[str, float] = {
    "spacious": 1800.0,
    "balanced": 1500.0,
    "compact":  1200.0,
}

# z-mount height for wall cabinets (standard kitchen mount above base cab)
_WALL_CAB_Z_MM: float = 1510.0

# NKBA-18: minimum clearance from cooktop surface to hood bottom (protected
# surface = 610mm; using 762mm for safer unprotected-surface default).
_HOOD_CLEARANCE_ABOVE_COOKTOP_MM: float = 762.0

# Zones that may be filled with REPEATED SKU instances (e.g. two corner cabs
# for U-shape both using SKU-C11). Catalog spec only forbids synthetic SKUs;
# nothing prevents using a real SKU more than once.
_TPL_REPEATABLE_ZONES: set[str] = {"base", "corner", "tall", "wall_cab"}

# ============================================================================
# Constants
# ============================================================================

Z_FLOOR_MM: float = 0.0
Z_WALL_CAB_BOTTOM_MM: float = (
    1510.0  # bottom of wall cabinet (local z) — NKBA-18: 1510-900=610mm clearance
)
Z_HOOD_CLEARANCE_MM: float = 610.0  # NKBA min clearance above cooktop to hood bottom
Z_LEVEL_SPLIT_MM: float = 500.0  # items below this are "floor level", above are "wall level"
GAP_LEAVE_BEFORE_MM: float = 600.0
GAP_FRIDGE_STOVE_MM: float = 600.0
WORK_TRIANGLE_MIN_MM: float = 3962.0
WORK_TRIANGLE_MAX_MM: float = 6600.0
MIN_SEGMENT_MM: float = 100.0
SINK_WINDOW_TOLERANCE_MM: float = 300.0
WALL_END_TOLERANCE_MM: float = 50.0  # fridge within this distance of wall end = already at end

# Variant-aware fill caps (mm of additional base cabinets per wall) — modelled on the
# template-driven "compactness" pattern used in deterministic kitchen planners.
# v1 = spacious (max counter run), v2 = balanced, v3 = compact (narrow SKUs, less fill).
# Primary wall = wall containing fridge or stove; Secondary = other cabinet walls.
# I-shape uses no cap (fills the whole single wall).
_FILL_CAP_MM: dict[str, dict[int, float]] = {
    "primary":   {1: 1800.0, 2: 1500.0, 3: 1200.0},
    "secondary": {1: 1200.0, 2: 900.0,  3: 600.0},
}

ZONE_WEIGHTS: dict[str, float] = {
    "cooling": 1.0,
    "cleaning": 1.0,
    "cooking": 0.9,
    "preparation": 0.7,
    "storage": 0.4,
}

# base_cabinet ↔ dishwasher is intentionally NOT whitelisted — a gap-fill base cabinet
# placed inside a dishwasher footprint is a real collision that must be caught.
# wall_cabinet ↔ base_cabinet: these live at different z-levels (1510mm vs 0mm) so
# _overlap3d() never fires; the entry is kept only as documentation.
COLLISION_WHITELIST: set[frozenset[str]] = {
    frozenset({"hood", "stove"}),
    frozenset({"tap", "sink"}),
    frozenset({"wall_cabinet", "base_cabinet"}),
}

_ANCHORED_KW: tuple[str, ...] = ("sink", "refrigerator", "fridge", "stove", "range")
_DEPENDENT_KW: tuple[str, ...] = ("hood", "dishwasher", "tap")
_DROPPABLE_KW: tuple[str, ...] = ("wall_cabinet", "base_cabinet", "island")
_FRIDGE_KW: tuple[str, ...] = ("fridge", "refrigerator")
_TALL_KW: tuple[str, ...] = ("tall_cabinet", "larder", "pantry_cabinet")
_CORNER_KW: tuple[str, ...] = ("corner_cabinet", "blind_corner")
_TAP_KW: tuple[str, ...] = ("tap", "faucet", "mixer")
# Required appliances — never dropped, force-placed with CONSTRAINT_VIOLATION if no clean space
_REQUIRED_APPLIANCE_KW: tuple[str, ...] = (
    "fridge", "refrigerator", "sink", "stove", "cooktop", "range",
    "hood", "dishwasher", "oven", "microwave",
)
# Keywords identifying items that occupy floor-level run space.
# All of these count as part of the continuous run (LAYOUT-03) and as self-supporting
# base-level units (LAYOUT-04 adjacency check does not apply to them).
_FLOOR_RUN_KW: tuple[str, ...] = (
    "base_cabinet", "corner_cabinet",
    "sink", "dishwasher",
    "stove", "range", "cooktop",
    "fridge", "refrigerator",
    "tall_cabinet",
)
# Items exempt from run compaction: stay at their placed position.
# Dependents (hood, tap) are re-anchored separately after compaction.
_COMPACT_EXEMPT_KW: tuple[str, ...] = (
    "tap", "faucet", "mixer",
    "hood",
    "wall_cabinet",
)


# ============================================================================
# Engine
# ============================================================================


class PlacementEngine:
    """Resolve semantic placement strategies to exact mm coordinates."""

    # ------------------------------------------------------------------ #
    # Entry point                                                          #
    # ------------------------------------------------------------------ #

    def place(
        self,
        zone_plan: ZonePlannerOutput,
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
    ) -> PlacementEngineOutput:
        """Convert semantic zone plan into positioned items in mm.

        Uses a 3-pass approach to guarantee correct ordering:
          Pass 1 — Appliances + dependents only (fridge first → corner, then stove/sink)
          Pass 2 — Base cabinet gap fill on EVERY wall (fills spaces between appliances)
          Pass 3 — Remaining fill items (wall cabinets, etc.) on their assigned walls
        """
        zone_plan = self._normalize_zone_plan(zone_plan, spatial)
        zone_plan = self._colocate_corner_cabinets_with_fridge(zone_plan, preprocessing)

        # NEW PATH (Checkpoints A/B/C): template-based deterministic placement
        # for all I/L/U families. Falls through to legacy only if templates
        # can't be built (e.g. malformed input or unknown family).
        templates = self._build_wall_run_templates(zone_plan, preprocessing, spatial)
        if templates:
            return self._place_with_templates(
                zone_plan, preprocessing, spatial, templates,
            )

        placed: dict[str, PlacedItem] = {}
        spillover: list[str] = []

        landing_areas = self._compute_landing_areas(preprocessing, spatial)
        logger.info(
            "Landing areas allocated: %s",
            {k: round(v) for k, v in landing_areas.items()},
        )

        all_walls: set[str] = set(zone_plan.zone_assignments.values())
        all_walls.update(zone_plan.wall_strategies.keys())

        # I-shape: force single-wall by picking the longest cabinet wall and
        # redirecting all zone assignments to it. Gap-fill is also restricted.
        if zone_plan.family.upper() == "I" and all_walls:
            cabinet_walls = [w for w in spatial.walls if w.has_cabinets]
            if cabinet_walls:
                primary = max(cabinet_walls, key=lambda w: w.length_mm).name
                all_walls = {primary}
                zone_plan = ZonePlannerOutput(
                    variant_id=zone_plan.variant_id,
                    family=zone_plan.family,
                    wall_strategies={primary: zone_plan.wall_strategies.get(primary, [])},
                    zone_assignments={z: primary for z in zone_plan.zone_assignments},
                    item_hints={
                        k: {**v, "wall": primary}
                        for k, v in zone_plan.item_hints.items()
                    },
                    work_triangle_priority=zone_plan.work_triangle_priority,
                    adjacency_hints=zone_plan.adjacency_hints,
                    avoid_zones=zone_plan.avoid_zones,
                    notes=zone_plan.notes,
                )

        # --- Pre-Pass: corner cabinets claim wall corners BEFORE item_hints.
        # Without this, fridge/stove via item_hints ("at north-west corner",
        # "right end of north_wall") take both corners and CORNER-SKIPPED fires.
        # Only runs for L/U where corner cabs are structural.
        self._place_corner_cabs_first(
            zone_plan, preprocessing, spatial, placed, spillover
        )

        # --- Pass 0: place anchored items using item_hints (primary contract) ---
        if zone_plan.item_hints:
            self._place_by_item_hints(
                zone_plan, preprocessing, spatial, placed, spillover
            )

        sorted_walls = sorted(all_walls)

        # --- Pass 1: corner cabs (-2), fridge/tall (-1), anchored (0), dependents (1) ---
        # Items already placed by Pass 0 (item_hints) are skipped — their coordinates
        # are authoritative; re-running _place_wall would treat them as references AND
        # candidates simultaneously, causing left/right-shift artefacts.
        for wall_name in sorted_walls:
            wall = self._get_wall(wall_name, spatial)
            if wall is None:
                continue
            items = [
                (sku, zone)
                for sku, zone in self._items_for_wall(wall_name, zone_plan, preprocessing)
                if self._priority_rank(sku) <= 1 and sku.sku_id not in placed
            ]
            if not items:
                continue
            strategies = zone_plan.wall_strategies.get(wall_name, [])
            self._place_wall(items, strategies, wall, spatial, placed, spillover, zone_plan.family)

        # --- L-shape secondary-wall repair: if family=L and every major appliance
        # ended up on the same wall, move one zone to the secondary wall so the L
        # is actually used. Runs after Pass 1 so we know where things ended up,
        # before Pass 2 so gap-fill works on the corrected layout.
        self._maybe_repair_l_secondary_wall(
            zone_plan, preprocessing, spatial, placed, spillover
        )
        # --- U-shape distribution repair: ensure 3 cabinet walls are used.
        self._maybe_repair_u_distribution(
            zone_plan, preprocessing, spatial, placed, spillover
        )

        # --- Family run template: enforce canonical wall assignments; remove
        # base cabs placed by Pass 1 that are outside the appliance run span.
        self._apply_family_run_template(
            zone_plan, preprocessing, spatial, placed, spillover
        )

        # --- Pass 2: fill gaps with base cabinets on zone-assigned walls only ---
        self._fill_all_gaps_with_base_cabinets(
            placed, preprocessing, spatial, spillover, all_walls,
            zone_plan.variant_id, zone_plan.family,
        )

        # Log missing base-cabinet support beside each major appliance / sink
        self._log_base_support_issues(placed, preprocessing, spatial, spillover)

        # --- Pass 3: remaining fill items (wall cabs, etc.) on assigned walls ---
        for wall_name in sorted_walls:
            wall = self._get_wall(wall_name, spatial)
            if wall is None:
                continue
            items = [
                (sku, zone)
                for sku, zone in self._items_for_wall(wall_name, zone_plan, preprocessing)
                if self._priority_rank(sku) == 2
                and sku.sku_id not in placed
                and "base_cabinet" not in sku.category.lower()
            ]
            if not items:
                continue
            strategies = zone_plan.wall_strategies.get(wall_name, [])
            self._place_wall(items, strategies, wall, spatial, placed, spillover, zone_plan.family)

        # --- Run compactor: pack floor items into continuous segments per wall.
        # Moves gaps to the run end instead of leaving them between appliances.
        # Dependents (hood, tap) are re-anchored inside the compactor.
        # Must run BEFORE wall-cab alignment so wall cabs track their base cabs.
        self._compact_wall_runs(placed, preprocessing, spatial, spillover, zone_plan.variant_id, zone_plan.family)

        # Post-compact gap fill: compaction consolidates items and moves gaps to run
        # ends. Pre-compact gaps were too small (400mm) for any base cabinet; post-
        # compact the consolidated gap (≥600mm) can now accommodate base cabinets.
        self._fill_all_gaps_with_base_cabinets(
            placed, preprocessing, spatial, spillover,
            variant_id=zone_plan.variant_id, family=zone_plan.family,
        )

        # Snap wall cabinets above base cabinets (TDD: wall cabs mount ABOVE base cabs)
        self._align_wall_cabs_above_base_cabs(placed, spatial, spillover)
        # Remove any wall cabinets that ended up over a window span after alignment
        self._remove_wall_cabs_over_windows(placed, spatial, spillover)

        # Phase 2A.2: remove isolated / unsupported / base_only-violating optionals.
        # Family-aware: must preserve typology (L=2 walls, U=3 walls, I=1 wall).
        self._cleanup_isolated_optionals(
            placed, preprocessing, spillover, family=zone_plan.family
        )
        self._verify_typology(placed, zone_plan.family, spillover)

        if zone_plan.work_triangle_priority:
            self._check_work_triangle(placed, spatial, spillover)
        # Note: _enforce_stove_fridge_gap removed — gap logic is inside _compact_wall_runs

        return PlacementEngineOutput(
            variant_id=zone_plan.variant_id,
            positioned_items=placed,
            spillover_log=spillover,
            collision_flags=self._detect_collisions(placed),
        )

    # ================================================================== #
    # Template-based placement (Checkpoint A — I-shape)                    #
    # ================================================================== #

    @staticmethod
    def _tpl_variant_index(variant_id: str) -> int:
        """Extract 1-based variant index from a variant_id string."""
        digits = "".join(c for c in variant_id if c.isdigit())
        return int(digits[-1]) if digits else 1

    def _build_wall_run_templates(
        self,
        zone_plan: ZonePlannerOutput,
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
    ) -> dict[str, WallRunTemplate]:
        """Build per-wall placement templates from Agent 3's family + variant.

        Returns an empty dict for families not yet template-driven (caller
        falls through to legacy multi-pass placement).
        """
        family = (zone_plan.family or "").upper()
        vidx = self._tpl_variant_index(zone_plan.variant_id)

        if family == "I":
            return self._build_i_templates(spatial, vidx, preprocessing)
        if family == "L":
            return self._build_l_templates(zone_plan, preprocessing, spatial, vidx)
        if family == "U":
            return self._build_u_templates(zone_plan, preprocessing, spatial, vidx)
        return {}

    def _build_i_templates(
        self,
        spatial: SpatialEngineOutput,
        vidx: int,
        preprocessing: PreprocessingOutput,
    ) -> dict[str, WallRunTemplate]:
        """I-shape: every item on the single longest cabinet wall.

        Three variants differ in sink/DW order and base-cab position, so the
        three layouts read distinct visually:
            v1: fridge | base | sink | dw   | base | stove   (spacious)
            v2: fridge | base | dw   | sink | base | stove   (balanced — DW before sink)
            v3: fridge | base | base | sink | dw   | stove   (compact — bases-left)
        Tall cabinet inserted right after fridge if zone_groups has one.
        """
        cabinet_walls = [w for w in spatial.walls if w.has_cabinets]
        if not cabinet_walls:
            return {}
        primary = max(cabinet_walls, key=lambda w: w.length_mm).name

        # Variant-specific sink/DW ordering. Every run ends with "base" so the
        # outer terminus is a base cabinet, satisfying LAYOUT-05.
        if vidx == 2:
            base_zones = ["fridge", "base", "dishwasher", "sink", "base", "stove", "base"]
        elif vidx == 3:
            base_zones = ["fridge", "base", "base", "sink", "dishwasher", "stove", "base"]
        else:
            base_zones = ["fridge", "base", "sink", "dishwasher", "base", "stove", "base"]

        # Insert a tall cabinet slot after fridge if catalog has one available
        has_tall = any(
            "tall_cabinet" in sku.category.lower()
            for skus in preprocessing.zone_groups.values()
            for sku in skus
        )
        zones = base_zones[:]
        if has_tall:
            zones.insert(1, "tall")

        compactness = {1: "spacious", 2: "balanced", 3: "compact"}.get(vidx, "balanced")

        return {primary: WallRunTemplate(
            wall_name=primary,
            zones=zones,
            reverse_axis=False,
            compactness=compactness,
        )}

    def _build_l_templates(
        self,
        zone_plan: ZonePlannerOutput,
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
        vidx: int,
    ) -> dict[str, WallRunTemplate]:
        """L-shape: two cabinet walls meeting at a corner.

        Honors Agent 3's zone_assignments to decide primary/secondary:
          primary = wall hosting cooling (fridge) — anchored by structural items
          secondary = wall hosting cleaning (sink) — different from primary
        Falls back to "longest two walls" only if zone_assignments are unusable
        (e.g. all zones on one wall, which is effectively I-shape).
        Corner cabinet sits at the meeting corner on the primary wall. The
        secondary wall starts AFTER the corner cab's depth-projection (900mm)
        so its items don't physically overlap the corner cab.
        """
        cabinet_walls = [w for w in spatial.walls if w.has_cabinets]
        if len(cabinet_walls) < 2:
            return {}

        # Honour Agent 3's zone-to-wall assignment for primary/secondary.
        za = zone_plan.zone_assignments
        primary_name = za.get("cooling") or za.get("cooking") or ""
        cleaning_name = za.get("cleaning") or ""
        secondary_name = cleaning_name if cleaning_name and cleaning_name != primary_name else ""

        wall_by_name = {w.name: w for w in cabinet_walls}
        primary = wall_by_name.get(primary_name)
        secondary = wall_by_name.get(secondary_name)

        # Fallback if Agent 3 didn't give us two distinct walls
        if primary is None or secondary is None:
            sorted_walls = sorted(cabinet_walls, key=lambda w: w.length_mm, reverse=True)
            if primary is None:
                primary = sorted_walls[0]
            if secondary is None:
                secondary = next(
                    (w for w in sorted_walls if w.name != primary.name),
                    None,
                )
        if primary is None or secondary is None:
            return {}

        compactness = {1: "spacious", 2: "balanced", 3: "compact"}.get(vidx, "balanced")
        templates: dict[str, WallRunTemplate] = {}

        # Detect which end of each wall is the meeting corner
        primary_meeting = self._get_meeting_corner_x(primary, spatial)
        secondary_meeting = self._get_meeting_corner_x(secondary, spatial)

        # Primary wall: fridge + stove (cooling + cooking), plus corner cab at the
        # meeting corner. Zone order varies per variant.
        # corner_cab goes at the meeting end, so put it FIRST if meeting is at right
        # (with reverse_axis the cursor walks from right → left, corner ends up at right).
        has_corner = any(
            self._is_corner_cabinet(sku)
            for skus in preprocessing.zone_groups.values()
            for sku in skus
        )

        # Every run terminates with "base" (LAYOUT-05). Outer end = wall-edge,
        # so the last zone in each list ends up at the wall edge / outer end
        # under cursor packing.
        if vidx == 1:  # spacious — max counter run on primary
            primary_zones = ["fridge", "base", "stove", "base"]
            secondary_zones = ["sink", "dishwasher", "base"]
        elif vidx == 2:  # balanced — tight triangle (sink+stove closer)
            primary_zones = ["fridge", "base", "sink", "dishwasher", "stove", "base"]
            secondary_zones = ["base", "base"]
        else:  # compact — minimal, narrower SKUs
            primary_zones = ["fridge", "stove", "base"]
            secondary_zones = ["sink", "dishwasher", "base"]

        # Corner cab goes at the cursor's STARTING position so it lands at the
        # meeting corner. With reverse_axis=True (cursor starts at the wall's
        # right end), zones[0] is placed at the right end. With reverse_axis=False
        # (cursor starts at left), zones[0] is placed at the left end.
        # Either way: corner cab as zones[0] = corner cab at the meeting corner.
        if has_corner:
            primary_zones = ["corner"] + primary_zones

        # Reverse axis on the wall whose meeting corner is at its right end.
        # This makes the cursor pack items from the corner outward, leaving any
        # tail gap at the OUTER (away-from-corner) end.
        primary_reverse = (
            primary_meeting is not None and primary_meeting > primary.length_mm / 2.0
        )
        secondary_reverse = (
            secondary_meeting is not None and secondary_meeting > secondary.length_mm / 2.0
        )

        # Corner-cab depth projects from primary into secondary's space.
        # Pad the secondary cursor by 900mm from its meeting end so items
        # don't physically overlap the corner cab.
        secondary_offset = 900.0 if has_corner else 0.0

        templates[primary.name] = WallRunTemplate(
            wall_name=primary.name,
            zones=primary_zones,
            reverse_axis=primary_reverse,
            compactness=compactness,
        )
        templates[secondary.name] = WallRunTemplate(
            wall_name=secondary.name,
            zones=secondary_zones,
            reverse_axis=secondary_reverse,
            compactness=compactness,
            start_offset_mm=secondary_offset,
        )
        return templates

    def _build_u_templates(
        self,
        zone_plan: ZonePlannerOutput,
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
        vidx: int,
    ) -> dict[str, WallRunTemplate]:
        """U-shape: three cabinet walls. Back wall = wall with fridge.

        Honors Agent 3's zone_assignments:
          back wall   = wall hosting cooling (fridge); typically also has sink
          side walls  = remaining cabinet walls — one gets cooking, other storage
        Corner cabs at both ends of the back wall (bookended). Side walls
        start AFTER the corner cab's 900mm depth-projection.
        """
        cabinet_walls = [w for w in spatial.walls if w.has_cabinets]
        if len(cabinet_walls) < 3:
            # Not enough walls for a true U — fall back to L
            return self._build_l_templates(zone_plan, preprocessing, spatial, vidx)

        za = zone_plan.zone_assignments
        back_name = za.get("cooling") or za.get("cleaning") or ""
        cooking_name = za.get("cooking") or ""
        storage_name = za.get("storage") or ""

        wall_by_name = {w.name: w for w in cabinet_walls}
        back = wall_by_name.get(back_name)

        # Side walls: prefer the walls Agent 3 assigned to cooking and storage,
        # falling back to the two remaining cabinet walls by length.
        remaining = [w for w in cabinet_walls if back is None or w.name != back.name]
        side_a = wall_by_name.get(cooking_name) if cooking_name != back_name else None
        side_b = wall_by_name.get(storage_name) if storage_name != back_name else None
        if side_a is None or side_b is None or side_a.name == (side_b.name if side_b else None):
            remaining_sorted = sorted(remaining, key=lambda w: w.length_mm, reverse=True)
            if back is None and remaining_sorted:
                # Fall back: longest = back
                back = remaining_sorted[0]
                remaining_sorted = remaining_sorted[1:]
            if side_a is None and remaining_sorted:
                side_a = remaining_sorted[0]
                remaining_sorted = remaining_sorted[1:]
            if side_b is None and remaining_sorted:
                side_b = remaining_sorted[0]
        if back is None or side_a is None or side_b is None:
            return {}

        compactness = {1: "spacious", 2: "balanced", 3: "compact"}.get(vidx, "balanced")
        has_corner = any(
            self._is_corner_cabinet(sku)
            for skus in preprocessing.zone_groups.values()
            for sku in skus
        )

        templates: dict[str, WallRunTemplate] = {}

        # Back wall: bookended by corner cabs (one at each side wall's meeting corner)
        # Side walls always end with "base" (LAYOUT-05). Back wall is bookended
        # by corner cabs (added below), so it naturally terminates at corners.
        if vidx == 1:
            back_zones = ["fridge", "base", "sink", "dishwasher", "base"]
            side_a_zones = ["stove", "base"]
            side_b_zones = ["base", "base"]
        elif vidx == 2:
            back_zones = ["sink", "dishwasher", "fridge", "base"]
            side_a_zones = ["stove", "base"]
            side_b_zones = ["base"]
        else:
            back_zones = ["fridge", "sink", "dishwasher", "base"]
            side_a_zones = ["stove", "base"]
            side_b_zones = ["base"]

        if has_corner:
            # Bookend the back wall with corner cabs at both ends. Cursor packs
            # left-to-right (no reverse), so zones[0] lands at the left end and
            # zones[-1] lands rightmost — corner cabs at both meeting corners.
            back_zones = ["corner"] + back_zones + ["corner"]

        # Determine reverse_axis for each wall based on meeting corner position
        back_meeting = self._get_meeting_corner_x(back, spatial)
        side_a_meeting = self._get_meeting_corner_x(side_a, spatial)
        side_b_meeting = self._get_meeting_corner_x(side_b, spatial)

        # Side walls start AFTER the corner cab's 900mm depth-projection from
        # the back wall (when corner cabs are bookended on the back wall).
        side_offset = 900.0 if has_corner else 0.0

        # Back wall: no reverse since it's bookended by corner cabs on both ends
        templates[back.name] = WallRunTemplate(
            wall_name=back.name,
            zones=back_zones,
            reverse_axis=False,
            compactness=compactness,
        )
        templates[side_a.name] = WallRunTemplate(
            wall_name=side_a.name,
            zones=side_a_zones,
            reverse_axis=(
                side_a_meeting is not None and side_a_meeting > side_a.length_mm / 2.0
            ),
            compactness=compactness,
            start_offset_mm=side_offset,
        )
        templates[side_b.name] = WallRunTemplate(
            wall_name=side_b.name,
            zones=side_b_zones,
            reverse_axis=(
                side_b_meeting is not None and side_b_meeting > side_b.length_mm / 2.0
            ),
            compactness=compactness,
            start_offset_mm=side_offset,
        )
        return templates

    def _pick_sku_for_zone(
        self,
        zone: str,
        preprocessing: PreprocessingOutput,
        used_ids: set[str],
        compactness: str,
        max_width: float | None = None,
    ) -> SKU | None:
        """Pick the best SKU from zone_groups matching this zone keyword.

        Two-pass selection:
          1. Prefer an unused SKU (closest to compactness target width)
          2. If none and the zone is in _TPL_REPEATABLE_ZONES (corner / base /
             tall / wall_cab), allow reusing an already-placed SKU.
        """
        keywords = _TPL_ZONE_KEYWORDS.get(zone, (zone,))
        target_w = _TPL_TARGET_WIDTH.get(zone, {}).get(compactness, 600.0)
        is_repeatable = zone in _TPL_REPEATABLE_ZONES

        unused: list[SKU] = []
        reusable: list[SKU] = []
        seen: set[str] = set()
        for skus in preprocessing.zone_groups.values():
            for sku in skus:
                if sku.sku_id in seen:
                    continue
                seen.add(sku.sku_id)
                if max_width is not None and sku.width_mm > max_width + 1.0:
                    continue
                combined = (sku.category + " " + sku.name).lower()
                if zone == "base" and self._is_corner_cabinet(sku):
                    continue
                if zone == "corner" and not self._is_corner_cabinet(sku):
                    continue
                if not any(kw in combined for kw in keywords):
                    continue
                if sku.sku_id in used_ids:
                    if is_repeatable:
                        reusable.append(sku)
                else:
                    unused.append(sku)

        pool = unused if unused else (reusable if is_repeatable else [])
        if not pool:
            return None
        pool.sort(key=lambda s: abs(s.width_mm - target_w))
        return pool[0]

    @staticmethod
    def _unique_placement_id(sku_id: str, placed: dict[str, PlacedItem]) -> str:
        """Generate a unique key for `placed` dict when reusing a SKU.

        Catalog allows real-SKU reuse (e.g. two corner cabs both = SKU-C11).
        The PlacedItem.sku_id stays the original; only the dict key gets a
        numeric suffix to keep entries distinct.
        """
        if sku_id not in placed:
            return sku_id
        n = 2
        while f"{sku_id}_{n}" in placed:
            n += 1
        return f"{sku_id}_{n}"

    def _min_width_for_zone(
        self,
        zone: str,
        preprocessing: PreprocessingOutput,
        used_ids: set[str],
    ) -> float:
        """Return the smallest available SKU width for this zone, or 0 if none.

        For REPEATABLE zones (base / corner / tall / wall_cab), a SKU already
        placed can be reused, so 'available' = entire catalog matching the zone.
        For non-repeatable zones (appliances), used SKUs are excluded.
        """
        if zone == "hood":
            return 0.0  # hood is mounted above stove, doesn't consume floor width
        keywords = _TPL_ZONE_KEYWORDS.get(zone, (zone,))
        is_repeatable = zone in _TPL_REPEATABLE_ZONES
        widths: list[float] = []
        for skus in preprocessing.zone_groups.values():
            for sku in skus:
                if not is_repeatable and sku.sku_id in used_ids:
                    continue
                combined = (sku.category + " " + sku.name).lower()
                if zone == "base" and self._is_corner_cabinet(sku):
                    continue
                if zone == "corner" and not self._is_corner_cabinet(sku):
                    continue
                if any(kw in combined for kw in keywords):
                    widths.append(sku.width_mm)
        return min(widths) if widths else 0.0

    def _place_with_cursor(
        self,
        wall: Wall,
        template: WallRunTemplate,
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
        placed: dict[str, PlacedItem],
        spillover: list[str],
    ) -> float:
        """Walk template.zones in order, placing one SKU per zone via cursor.

        Reserves space for upcoming mandatory zones so wide cabs don't squeeze
        out appliances later in the run. Returns the final cursor position.
        """
        segs = spatial.free_segments.get(wall.name, [])
        if not segs:
            return 0.0

        if template.reverse_axis:
            cursor = segs[-1].end_mm - template.start_offset_mm
            run_limit = segs[0].start_mm
        else:
            cursor = segs[0].start_mm + template.start_offset_mm
            run_limit = segs[-1].end_mm

        # used_ids tracks original sku_ids (not placement_ids) so the
        # "prefer unused" logic in _pick_sku_for_zone works after reuse.
        used_ids: set[str] = {it.sku_id for it in placed.values()}

        for i, zone in enumerate(template.zones):
            # 'hood' is dependent (mounts above stove) — handled in a later step
            if zone == "hood":
                continue

            # Reserve space for MANDATORY upcoming zones (appliances/structural)
            # AND the trailing terminator "base" (LAYOUT-05: every run must end
            # at a base or corner). Mid-run "base" slots stay flexible — they
            # get skipped if no space, tail-fill handles them.
            _MANDATORY = {"fridge", "sink", "dishwasher", "stove", "tall", "corner"}
            last_idx = len(template.zones) - 1
            reserved = 0.0
            for j in range(i + 1, len(template.zones)):
                z = template.zones[j]
                is_terminator_base = (z == "base" and j == last_idx)
                if z in _MANDATORY or is_terminator_base:
                    reserved += self._min_width_for_zone(z, preprocessing, used_ids)
            remaining = (cursor - run_limit) if template.reverse_axis else (run_limit - cursor)
            max_w_here = max(0.0, remaining - reserved)

            sku = self._pick_sku_for_zone(
                zone, preprocessing, used_ids, template.compactness,
                max_width=max_w_here,
            )
            if sku is None:
                logger.info(
                    "TEMPLATE: no SKU available for zone '%s' on %s (max_w=%.0f) — skipping slot",
                    zone, wall.name, max_w_here,
                )
                continue

            if template.reverse_axis:
                x = cursor - sku.width_mm
            else:
                x = cursor

            if x < -1.0 or (x + sku.width_mm) > wall.length_mm + 1.0:
                logger.info(
                    "TEMPLATE: %s (%s, %.0fmm) overflows %s — skipping",
                    sku.sku_id, zone, sku.width_mm, wall.name,
                )
                continue

            zone_type = _TPL_ZONE_TYPE.get(zone, "preparation")
            placement_id = self._unique_placement_id(sku.sku_id, placed)
            placed[placement_id] = self._make_item(
                sku, zone_type, x, wall.thickness_mm, Z_FLOOR_MM, wall.name,
            )
            used_ids.add(sku.sku_id)
            logger.debug(
                "CURSOR: %s%s (%s, %.0fmm) at x=%.0f on %s",
                placement_id,
                "" if placement_id == sku.sku_id else f" [reusing {sku.sku_id}]",
                zone, sku.width_mm, x, wall.name,
            )

            if template.reverse_axis:
                cursor -= sku.width_mm
            else:
                cursor += sku.width_mm

        return cursor

    def _tail_fill_with_cap(
        self,
        wall: Wall,
        template: WallRunTemplate,
        cursor: float,
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
        placed: dict[str, PlacedItem],
        spillover: list[str],
    ) -> None:
        """Fill remaining wall space with base cabs up to compactness cap.

        Caps adopted from deterministic template engines: spacious fills more,
        compact fills less. Only catalog base cabinets are used (corner cabs
        excluded — structural).
        """
        segs = spatial.free_segments.get(wall.name, [])
        if not segs:
            return

        cap_mm = _TPL_FILL_CAP_MM.get(template.compactness, 1500.0)

        if template.reverse_axis:
            limit = segs[0].start_mm
            remaining = cursor - limit
        else:
            limit = segs[-1].end_mm
            remaining = limit - cursor

        if remaining <= 50.0:
            return

        # Tail fill may reuse the same base SKU multiple times (e.g. 3× 600mm
        # bases on a long secondary wall). We collect ALL catalog base cabs
        # (corners excluded), and the loop allows reuse — bounded by cap_mm.
        available = self._collect_template_base_cabs(preprocessing, set())

        # Sort by variant preference: spacious widest-first, compact narrowest.
        if template.compactness == "compact":
            available.sort(key=lambda s: s.width_mm)
        else:
            available.sort(key=lambda s: s.width_mm, reverse=True)

        mm_added = 0.0
        while remaining > 50.0 and mm_added < cap_mm:
            placed_one = False
            for sku in available:
                if sku.width_mm > remaining + 1.0:
                    continue
                if mm_added + sku.width_mm > cap_mm + 1.0:
                    continue
                x = cursor - sku.width_mm if template.reverse_axis else cursor
                if not self._position_clear(
                    x, sku.width_mm, wall.name, placed, Z_FLOOR_MM, wall.length_mm,
                ):
                    continue
                placement_id = self._unique_placement_id(sku.sku_id, placed)
                placed[placement_id] = self._make_item(
                    sku, "preparation", x, wall.thickness_mm, Z_FLOOR_MM, wall.name,
                )
                mm_added += sku.width_mm
                remaining -= sku.width_mm
                if template.reverse_axis:
                    cursor -= sku.width_mm
                else:
                    cursor += sku.width_mm
                logger.debug(
                    "TAIL-FILL: %s%s (%.0fmm) at x=%.0f on %s (%.0f/%.0f)",
                    placement_id,
                    "" if placement_id == sku.sku_id else f" [reusing {sku.sku_id}]",
                    sku.width_mm, x, wall.name, mm_added, cap_mm,
                )
                placed_one = True
                break
            if not placed_one:
                break  # nothing fits

    def _collect_template_base_cabs(
        self,
        preprocessing: PreprocessingOutput,
        used_ids: set[str],
    ) -> list[SKU]:
        """Return all unplaced base cabinets from zone_groups, excluding corners."""
        result: list[SKU] = []
        seen: set[str] = set()
        for skus in preprocessing.zone_groups.values():
            for sku in skus:
                if sku.sku_id in used_ids or sku.sku_id in seen:
                    continue
                seen.add(sku.sku_id)
                if "base_cabinet" not in sku.category.lower():
                    continue
                if self._is_corner_cabinet(sku):
                    continue
                result.append(sku)
        return result

    def _place_hood_above_stove(
        self,
        preprocessing: PreprocessingOutput,
        placed: dict[str, PlacedItem],
        spillover: list[str],
    ) -> None:
        """If a hood SKU exists in zone_groups, mount it directly above the stove."""
        stove_item: PlacedItem | None = next(
            (
                it for it in placed.values()
                if any(kw in (it.category + " " + it.name).lower()
                       for kw in ("stove", "range", "cooktop"))
                and it.position_mm.get("z", 0.0) < Z_LEVEL_SPLIT_MM
            ),
            None,
        )
        if stove_item is None:
            return

        used_ids = set(placed.keys())
        hood_sku: SKU | None = None
        for skus in preprocessing.zone_groups.values():
            for sku in skus:
                if sku.sku_id in used_ids:
                    continue
                if "hood" in sku.category.lower() or "hood" in sku.name.lower():
                    hood_sku = sku
                    break
            if hood_sku is not None:
                break
        if hood_sku is None:
            return

        # Centre hood horizontally over the stove. Mount at WALL-CAB level (or
        # NKBA-18 minimum clearance from cooktop, whichever is higher) so it
        # sits at the upper run with wall cabinets, not flat on the cooktop.
        stove_w = stove_item.dimensions_mm["width"]
        stove_h = stove_item.dimensions_mm["height"]
        x = stove_item.position_mm["x"] + (stove_w - hood_sku.width_mm) / 2.0
        y = stove_item.position_mm["y"]
        z = max(
            _WALL_CAB_Z_MM,
            stove_item.position_mm["z"] + stove_h + _HOOD_CLEARANCE_ABOVE_COOKTOP_MM,
        )
        placement_id = self._unique_placement_id(hood_sku.sku_id, placed)
        placed[placement_id] = self._make_item(
            hood_sku, "cooking", x, y, z, stove_item.anchor_wall,
        )
        logger.debug(
            "DEP: hood %s placed above stove at x=%.0f z=%.0f", placement_id, x, z,
        )

    def _place_wall_cabs_above_bases(
        self,
        preprocessing: PreprocessingOutput,
        placed: dict[str, PlacedItem],
        spillover: list[str],
    ) -> None:
        """Mount wall cabinets directly above base cabinets, one per base cab.

        Skips x-ranges where a tall cabinet exists (tall cabs already extend
        into the wall-cab z-zone — no room for an upper).
        """
        used_ids = set(placed.keys())
        # Floor-level base cabs grouped by wall
        bases_by_wall: dict[str, list[PlacedItem]] = {}
        # Tall-cab x-ranges per wall (wall cabs can't mount above these)
        tall_ranges_by_wall: dict[str, list[tuple[float, float]]] = {}
        for it in placed.values():
            combined = (it.category + " " + it.name).lower()
            if "tall_cabinet" in combined:
                x = it.position_mm["x"]
                tall_ranges_by_wall.setdefault(it.anchor_wall, []).append(
                    (x, x + it.dimensions_mm["width"])
                )
                continue
            if "base_cabinet" not in it.category.lower():
                continue
            if it.position_mm.get("z", 0.0) >= Z_LEVEL_SPLIT_MM:
                continue
            # Skip corner cabs for wall-cab mounting — corners get their own treatment
            if any(kw in combined for kw in _CORNER_KW):
                continue
            bases_by_wall.setdefault(it.anchor_wall, []).append(it)

        # Available wall cab SKUs (deduplicated by sku_id). Sorted widest-first
        # so wider bases get matched to wider wall cabs. Reuse is allowed —
        # multiple base cabs may share the same wall-cab SKU.
        wall_cabs: list[SKU] = []
        seen: set[str] = set()
        for skus in preprocessing.zone_groups.values():
            for sku in skus:
                if sku.sku_id in seen:
                    continue
                seen.add(sku.sku_id)
                if "wall_cabinet" in sku.category.lower():
                    wall_cabs.append(sku)
        wall_cabs.sort(key=lambda s: s.width_mm, reverse=True)

        for wall_name, bases in bases_by_wall.items():
            tall_ranges = tall_ranges_by_wall.get(wall_name, [])
            bases.sort(key=lambda b: b.position_mm["x"])
            for base in bases:
                if not wall_cabs:
                    break
                base_x1 = base.position_mm["x"]
                base_w = base.dimensions_mm["width"]
                # Pick a wall cab no wider than the base
                sku = next(
                    (s for s in wall_cabs if s.width_mm <= base_w + 1.0),
                    None,
                )
                if sku is None:
                    continue
                x = base_x1 + (base_w - sku.width_mm) / 2.0
                x2 = x + sku.width_mm
                # Skip if overlapping a tall cabinet's x-range
                if any(not (x2 <= t1 or x >= t2) for t1, t2 in tall_ranges):
                    continue
                y = base.position_mm["y"]
                placement_id = self._unique_placement_id(sku.sku_id, placed)
                placed[placement_id] = self._make_item(
                    sku, "storage", x, y, _WALL_CAB_Z_MM, wall_name,
                )
                logger.debug(
                    "WALL-CAB: %s above %s at x=%.0f", placement_id, base.sku_id, x,
                )

    def _place_with_templates(
        self,
        zone_plan: ZonePlannerOutput,
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
        templates: dict[str, WallRunTemplate],
    ) -> PlacementEngineOutput:
        """Deterministic template-based placement orchestrator.

        Pipeline:
          1. Cursor-place items per wall template (contiguous, no internal gaps).
          2. Tail-fill remaining space with capped base cabinets (variant-aware).
          3. Mount hood above stove.
          4. Mount wall cabinets above base cabinets.
          5. Run NKBA work-triangle check if requested.
        """
        placed: dict[str, PlacedItem] = {}
        spillover: list[str] = []

        landing_areas = self._compute_landing_areas(preprocessing, spatial)
        logger.info(
            "Landing areas allocated: %s",
            {k: round(v) for k, v in landing_areas.items()},
        )

        # 1 + 2: cursor placement + tail fill, per wall
        for wall_name, template in templates.items():
            wall = self._get_wall(wall_name, spatial)
            if wall is None:
                continue
            cursor = self._place_with_cursor(
                wall, template, preprocessing, spatial, placed, spillover,
            )
            self._tail_fill_with_cap(
                wall, template, cursor, preprocessing, spatial, placed, spillover,
            )

        # 3: hood above stove
        self._place_hood_above_stove(preprocessing, placed, spillover)

        # 4: wall cabs above base cabs
        self._place_wall_cabs_above_bases(preprocessing, placed, spillover)

        # 5: window safety — remove any wall cabinet that ended up over a window
        self._remove_wall_cabs_over_windows(placed, spatial, spillover)

        # 6: respect cabinet_preference (e.g. "base_only" removes wall/tall cabs)
        self._cleanup_isolated_optionals(
            placed, preprocessing, spillover, family=zone_plan.family,
        )

        # 7: log missing base support beside major appliances (informational)
        self._log_base_support_issues(placed, preprocessing, spatial, spillover)

        # 8: verify typology — log a warning if family wall-count not met
        self._verify_typology(placed, zone_plan.family, spillover)

        # 9: work triangle (best-effort log; doesn't move items)
        if zone_plan.work_triangle_priority:
            self._check_work_triangle(placed, spatial, spillover)

        return PlacementEngineOutput(
            variant_id=zone_plan.variant_id,
            positioned_items=placed,
            spillover_log=spillover,
            collision_flags=self._detect_collisions(placed),
        )

    # ------------------------------------------------------------------ #
    # item_hints placement (primary contract)                              #
    # ------------------------------------------------------------------ #

    # Map item_hints keys → keywords to find the matching SKU in zone_groups
    _ITEM_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
        "fridge":       ("fridge", "refrigerator"),
        "sink":         ("sink",),
        "dishwasher":   ("dishwasher",),
        "stove":        ("stove", "cooktop", "range"),
        "hood":         ("hood", "vent"),
        "oven":         ("oven",),
        "microwave":    ("microwave",),
        "tall_cabinet": ("tall_cabinet", "pantry", "tall cabinet"),
    }

    def _classify_sku_type(self, sku: SKU) -> str | None:
        """Map a SKU back to an item_hints key, or None if no match."""
        combined = (sku.category + " " + sku.name + " " + sku.sku_id).lower()
        for item_type, keywords in self._ITEM_TYPE_KEYWORDS.items():
            if any(kw in combined for kw in keywords):
                return item_type
        return None

    def _place_by_item_hints(
        self,
        zone_plan: ZonePlannerOutput,
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
        placed: dict[str, PlacedItem],
        spillover: list[str],
    ) -> None:
        """Place items using Agent 3's item_hints. Items without hints fall through
        to the existing wall_strategies passes."""
        valid_walls = {w.name for w in spatial.walls}

        # Build (sku, item_type, zone) list, then sort by placement priority
        # so fridge / tall claim corners before stove / sink need them.
        candidates: list[tuple[SKU, str, str]] = []
        for zone_name, skus in preprocessing.zone_groups.items():
            for sku in skus:
                if sku.sku_id in placed:
                    continue
                item_type = self._classify_sku_type(sku)
                if item_type is None:
                    continue
                if item_type not in zone_plan.item_hints:
                    continue
                candidates.append((sku, item_type, zone_name))

        candidates.sort(key=lambda t: self._priority_rank(t[0]))

        for sku, item_type, zone_name in candidates:
            hint = zone_plan.item_hints[item_type]
            wall_name = hint.get("wall", "")
            position = hint.get("position", "")
            if wall_name not in valid_walls:
                logger.info(
                    "item_hints[%s] references unknown wall %r — skipping (fallback)",
                    item_type, wall_name,
                )
                continue

            # Fix B: dependents must follow their anchor's actual wall, not the hint's wall.
            # If sink/stove were placed elsewhere than the hint suggests, override.
            wall_name, position = self._override_dependent_wall(
                item_type, wall_name, position, placed
            )

            wall = self._get_wall(wall_name, spatial)
            if wall is None:
                continue
            coords = self._resolve_term(position, wall, sku, placed, spatial)
            if coords is None:
                logger.info(
                    "item_hints[%s] position %r unresolvable — falling back",
                    item_type, position,
                )
                continue
            x, y, z = coords
            # Validate position is collision-free and within wall bounds (Fix A)
            if not self._position_clear(
                x, sku.width_mm, wall.name, placed, z, wall.length_mm
            ):
                logger.info(
                    "item_hints[%s] resolved to colliding position on %s — falling back",
                    item_type, wall.name,
                )
                continue
            placed[sku.sku_id] = self._make_item(sku, zone_name, x, y, z, wall.name)
            logger.debug(
                "Placed %s (%s) via item_hints on %s at %r (x=%.0f)",
                sku.sku_id, item_type, wall.name, position, x,
            )

    def _override_dependent_wall(
        self,
        item_type: str,
        hint_wall: str,
        position: str,
        placed: dict[str, PlacedItem],
    ) -> tuple[str, str]:
        """If a dependent's hint wall conflicts with its anchor's actual wall, follow the anchor.

        Returns (wall_name, position). Position may be rewritten so 'next to' / 'above'
        terms resolve against the right reference on the corrected wall.
        """
        anchor_map = {
            "dishwasher": ("sink",),
            "tap":        ("sink",),
            "hood":       ("stove", "range"),
        }
        anchors = anchor_map.get(item_type)
        if not anchors:
            return hint_wall, position
        for kw in anchors:
            anchor_item = self._find_by_cat(kw, placed)
            if anchor_item is None:
                continue
            if anchor_item.anchor_wall != hint_wall:
                logger.info(
                    "Override: %s wall %s -> %s (follows %s)",
                    item_type, hint_wall, anchor_item.anchor_wall, kw,
                )
                return anchor_item.anchor_wall, position
            return hint_wall, position
        return hint_wall, position

    # ------------------------------------------------------------------ #
    # Wall placement                                                       #
    # ------------------------------------------------------------------ #

    def _place_wall(
        self,
        items: list[tuple[SKU, str]],
        strategies: list[str],
        wall: Wall,
        spatial: SpatialEngineOutput,
        placed: dict[str, PlacedItem],
        spillover: list[str],
        family: str = "",
    ) -> None:
        """Place all items for one wall using available strategies."""
        # Sort: anchored first, then dependent, then fill
        sorted_items = sorted(items, key=lambda t: self._priority_rank(t[0]))

        for sku, zone_type in sorted_items:
            item_key = sku.sku_id

            # Fix F: corner cabinet MUST occupy a real corner — never falls through to
            # mid-wall placement. If both corners are taken, skip and log CORNER-SKIPPED.
            if self._is_corner_cabinet(sku):
                y = wall.thickness_mm
                placed_at_corner = False
                for corner_x in [max(0.0, wall.length_mm - sku.width_mm), 0.0]:
                    if self._position_clear(
                        corner_x, sku.width_mm, wall.name, placed, Z_FLOOR_MM, wall.length_mm
                    ):
                        placed[item_key] = self._make_item(
                            sku, zone_type, corner_x, y, Z_FLOOR_MM, wall.name
                        )
                        logger.debug("CORNER: %s at x=%.0f on %s", sku.sku_id, corner_x, wall.name)
                        placed_at_corner = True
                        break
                if not placed_at_corner:
                    logger.info(
                        "CORNER-SKIPPED: %s — no available corner on %s",
                        sku.sku_id, wall.name,
                    )
                    spillover.append(
                        f"CORNER-SKIPPED: {sku.sku_id} no available corner on {wall.name}"
                    )
                continue  # corner cab never placed mid-wall — go to next sku

            # Fridge / tall cabinet: try right wall-end first, then left.
            # Must happen BEFORE stove/sink are placed so the corner is still free.
            if self._is_fridge_or_tall(sku):
                y = wall.thickness_mm
                for corner_x in [max(0.0, wall.length_mm - sku.width_mm), 0.0]:
                    if self._position_clear(corner_x, sku.width_mm, wall.name, placed, Z_FLOOR_MM, wall.length_mm):
                        placed[item_key] = self._make_item(sku, zone_type, corner_x, y, Z_FLOOR_MM, wall.name)
                        logger.debug("CORNER: %s at x=%.0f on %s", sku.sku_id, corner_x, wall.name)
                        break
                if item_key in placed:
                    continue
                # Both corners occupied — fall through to normal strategy logic

            # Fix 3: tap/faucet co-locates on the sink (whitelisted collision)
            # instead of being placed independently "next to sink" which puts it off-wall
            if self._is_tap(sku):
                sink_item = self._find_by_cat("sink", placed)
                if sink_item is not None:
                    placed[item_key] = self._make_item(
                        sku,
                        zone_type,
                        sink_item.position_mm["x"],
                        sink_item.position_mm["y"],
                        sink_item.position_mm["z"],
                        sink_item.anchor_wall,
                    )
                    logger.debug("Tap '%s' co-located with sink at x=%.0f", sku.sku_id, sink_item.position_mm["x"])
                    continue
                # Sink not placed yet — fall through to normal logic

            # Dependents may carry inherent terms (hood above stove, DW next to sink)
            if self._is_dependent(sku):
                inherent = self._inherent_term(sku)
                result = self._resolve_term(inherent, wall, sku, placed, spatial)
                if result is not None:
                    x, y, z = result
                    # Hood-stove same-x is whitelisted (z-stack). For other dependents
                    # (e.g. dishwasher) reject same-x and fall through to strategies/first_free.
                    if self._dependent_position_ok(
                        sku, x, wall.name, placed, wall.length_mm
                    ):
                        placed[item_key] = self._make_item(sku, zone_type, x, y, z, wall.name)
                        continue

            # Try each strategy term in order; skip terms that collide with already-placed items
            resolved = False
            for strat in strategies:
                term = self._extract_pos_term(strat)
                result = self._resolve_term(term, wall, sku, placed, spatial)
                if result is None:
                    continue
                x, y, z = result
                if not self._position_clear(
                    x, sku.width_mm, wall.name, placed, z, wall.length_mm
                ):
                    continue
                placed[item_key] = self._make_item(sku, zone_type, x, y, z, wall.name)
                resolved = True
                break

            if not resolved:
                # Fall back to first free segment (already accounts for occupied space)
                result = self._first_free(wall, sku, placed, spatial)
                if result is not None:
                    x, y, z = result
                    placed[item_key] = self._make_item(sku, zone_type, x, y, z, wall.name)
                else:
                    self._no_space(sku, zone_type, wall, spatial, placed, spillover, family)

    def _position_clear(
        self,
        x: float,
        width: float,
        wall_name: str,
        placed: dict[str, PlacedItem],
        z_level: float = Z_FLOOR_MM,
        wall_length: float | None = None,
    ) -> bool:
        """Return True if [x, x+width] fits on wall AND doesn't overlap items at same z-level."""
        if x < 0:
            return False
        item_end = x + width
        if wall_length is not None and item_end > wall_length:
            return False
        occupied = self._occupied_ranges(wall_name, placed, z_level)
        return all(not (x < occ_end and item_end > occ_start) for occ_start, occ_end in occupied)

    def _dependent_position_ok(
        self,
        sku: SKU,
        x: float,
        wall_name: str,
        placed: dict[str, PlacedItem],
        wall_length: float | None = None,
    ) -> bool:
        """Same-x overlap allowed only if pair is whitelisted; also enforces wall bounds."""
        if x < 0:
            return False
        item_end = x + sku.width_mm
        if wall_length is not None and item_end > wall_length:
            return False
        sku_tag = (sku.category + " " + sku.name).lower()
        for item in placed.values():
            if item.anchor_wall != wall_name:
                continue
            ix = item.position_mm["x"]
            iw = item.dimensions_mm["width"]
            if x < ix + iw and item_end > ix:
                item_tag = (item.category + " " + item.name).lower()
                if not self._whitelisted(sku_tag, item_tag):
                    return False
        return True

    @staticmethod
    def _whitelisted(tag_a: str, tag_b: str) -> bool:
        """Return True if (tag_a, tag_b) match any COLLISION_WHITELIST pair by keyword."""
        for pair in COLLISION_WHITELIST:
            kw1, kw2 = list(pair)
            if (kw1 in tag_a and kw2 in tag_b) or (kw2 in tag_a and kw1 in tag_b):
                return True
        return False

    @staticmethod
    def _is_floor_run_unit(item: PlacedItem) -> bool:
        """True if item is a self-supporting floor-level run unit.

        These items (appliances, sink, base/tall cabinets) all occupy floor-level
        run space and count as part of the continuous counter run for LAYOUT-03.
        They do NOT need an adjacent separate base cabinet for LAYOUT-04 purposes.
        """
        combined = (item.category + " " + item.name).lower()
        return any(kw in combined for kw in _FLOOR_RUN_KW)

    def _no_space(
        self,
        sku: SKU,
        zone_type: str,
        wall: Wall,
        spatial: SpatialEngineOutput,
        placed: dict[str, PlacedItem],
        spillover: list[str],
        family: str = "",
    ) -> None:
        """Handle an item that has no free space on its assigned wall."""
        # I-shape: never spill to another wall — force-place on same wall even if crowded
        if family.upper() == "I":
            cat = sku.category.lower()
            name_lower = sku.name.lower()
            # Drop optional fill items (wall cabinets, prep cabinets) to preserve appliances
            for kw in _DROPPABLE_KW:
                if kw in cat or kw in name_lower:
                    spillover.append(f"SPILLOVER: {sku.sku_id} dropped from {wall.name} (I-shape, no space)")
                    return
            # Non-droppable appliance: force-place at leftmost free x, or overlap if necessary
            y = wall.thickness_mm
            for forced_x in (0.0, max(0.0, wall.length_mm - sku.width_mm)):
                if self._position_clear(forced_x, sku.width_mm, wall.name, placed, Z_FLOOR_MM, wall.length_mm):
                    placed[sku.sku_id] = self._make_item(sku, zone_type, forced_x, y, Z_FLOOR_MM, wall.name)
                    spillover.append(f"CONSTRAINT_VIOLATION: {sku.sku_id} forced to corner on {wall.name} (I-shape)")
                    return
            # Last resort: place at x=0 even with overlap to keep it on the wall
            placed[sku.sku_id] = self._make_item(sku, zone_type, 0.0, y, Z_FLOOR_MM, wall.name)
            spillover.append(f"CONSTRAINT_VIOLATION: {sku.sku_id} force-placed at x=0 on {wall.name} (I-shape overlap)")
            return

        # Step 1: try adjacent wall
        adj = self._adjacent_wall(wall.name, spatial)
        if adj is not None:
            result = self._first_free(adj, sku, placed, spatial)
            if result is not None:
                x, y, z = result
                placed[sku.sku_id] = self._make_item(sku, zone_type, x, y, z, adj.name)
                spillover.append(f"SPILLOVER: {sku.sku_id} moved from {wall.name} to {adj.name}")
                logger.info(
                    "SPILLOVER: '%s' moved from '%s' to adjacent wall '%s'",
                    sku.sku_id,
                    wall.name,
                    adj.name,
                )
                return

        # Step 2: no space on adjacent wall either — try ANY other wall before drop/force
        for other in spatial.walls:
            if other.name in (wall.name, adj.name if adj else ""):
                continue
            result = self._first_free(other, sku, placed, spatial)
            if result is not None:
                x, y, z = result
                placed[sku.sku_id] = self._make_item(sku, zone_type, x, y, z, other.name)
                spillover.append(f"SPILLOVER: {sku.sku_id} moved from {wall.name} to {other.name}")
                logger.info(
                    "SPILLOVER: '%s' moved from '%s' to wall '%s'",
                    sku.sku_id,
                    wall.name,
                    other.name,
                )
                return

        # Step 3: no space anywhere — drop droppables, force non-droppables to a corner
        cat = sku.category.lower()
        name = sku.name.lower()

        for kw in _DROPPABLE_KW:
            if kw in cat or kw in name:
                logger.warning(
                    "SPILLOVER: '%s' (%s) dropped — no space on any wall",
                    sku.sku_id,
                    sku.name,
                )
                spillover.append(f"SPILLOVER: {sku.sku_id} dropped from {wall.name} (no space)")
                return

        # Non-droppable: try x=0, then right end — only place if collision-free
        y = wall.thickness_mm
        z = Z_FLOOR_MM
        for forced_x in (0.0, max(0.0, wall.length_mm - sku.width_mm)):
            if self._position_clear(
                forced_x, sku.width_mm, wall.name, placed, z, wall.length_mm
            ):
                logger.warning(
                    "CONSTRAINT_VIOLATION: '%s' forced to x=%.0f on wall '%s'",
                    sku.sku_id,
                    forced_x,
                    wall.name,
                )
                spillover.append(
                    f"CONSTRAINT_VIOLATION: {sku.sku_id} forced to corner "
                    f"on {wall.name} (LAYOUT-06)"
                )
                placed[sku.sku_id] = self._make_item(
                    sku, zone_type, forced_x, y, z, wall.name
                )
                return
        # Fix C: required appliances are NEVER dropped — force-place with overlap
        # and log CONSTRAINT_VIOLATION so the validator can flag the layout.
        if self._is_required_appliance(sku):
            forced_x = 0.0
            logger.warning(
                "CONSTRAINT_VIOLATION: '%s' force-placed at x=%.0f on '%s' with overlap (no clean space)",
                sku.sku_id, forced_x, wall.name,
            )
            spillover.append(
                f"CONSTRAINT_VIOLATION: {sku.sku_id} force-placed on {wall.name} "
                f"with overlap (LAYOUT-06)"
            )
            placed[sku.sku_id] = self._make_item(
                sku, zone_type, forced_x, y, z, wall.name
            )
            return
        # Non-required, non-droppable (rare path) — drop rather than create silent collision
        logger.warning(
            "DROPPED: '%s' (%s) — no collision-free position on any wall",
            sku.sku_id,
            sku.name,
        )
        spillover.append(f"DROPPED: {sku.sku_id} from {wall.name} (no collision-free space)")

    # ------------------------------------------------------------------ #
    # Semantic term resolution                                             #
    # ------------------------------------------------------------------ #

    def _resolve_term(
        self,
        term: str,
        wall: Wall,
        sku: SKU,
        placed: dict[str, PlacedItem],
        spatial: SpatialEngineOutput,
    ) -> tuple[float, float, float] | None:
        """Resolve one semantic term to (x, y, z) mm triplet or None."""
        t = term.strip().lower()
        y = wall.thickness_mm
        z = Z_WALL_CAB_BOTTOM_MM if sku.category.lower() == "wall_cabinet" else Z_FLOOR_MM
        _ = 0  # rotation set during serialization based on wall anchor

        if t == "at north-west corner":
            return (0.0, y, z)
        if t == "at north-east corner":
            return (max(0.0, wall.length_mm - sku.width_mm), y, z)
        if t == "at south-west corner":
            return (0.0, 0.0, z)
        if t == "at south-east corner":
            return (max(0.0, wall.length_mm - sku.width_mm), 0.0, z)
        if re.match(r"centre of [\w\-]+", t) or re.match(r"center of [\w\-]+", t):
            cx = self._resolve_centre(wall, sku, placed, spatial, z)
            if cx is None:
                return None
            return (cx, y, z)
        if re.match(r"left end of [\w\-]+", t):
            lx = self._resolve_end(wall, sku, placed, spatial, z, side="left")
            if lx is None:
                return None
            return (lx, y, z)
        if re.match(r"right end of [\w\-]+", t):
            rx = self._resolve_end(wall, sku, placed, spatial, z, side="right")
            if rx is None:
                return None
            return (rx, y, z)
        if re.match(r"near [\w\-]+ window", t):
            return self._near_window(wall, sku, spatial, y, z)
        if t.startswith("next to "):
            ref_name = t[len("next to ") :]
            return self._resolve_next_to(ref_name, sku, wall, placed, z)
        if t.startswith("above "):
            ref_name = t[len("above ") :]
            return self._resolve_above(ref_name, sku, placed)
        if t.startswith("leave gap before "):
            ref_name = t[len("leave gap before ") :]
            return self._resolve_gap_before(ref_name, sku, placed, y, z)

        logger.info("Unrecognised position term %r — caller will fall back", term)
        return None

    def _free_subranges(
        self,
        wall: Wall,
        placed: dict[str, PlacedItem],
        spatial: SpatialEngineOutput,
        z: float,
    ) -> list[tuple[float, float]]:
        """Return collision-free (start, end) sub-ranges on wall at z-level.

        For wall-level items (z >= Z_LEVEL_SPLIT_MM) use `wall_free_segments`
        when available — that subtracts windows in addition to doors. Floor-level
        items use `free_segments` (windows allowed if the sill permits).
        """
        if z >= Z_LEVEL_SPLIT_MM and spatial.wall_free_segments:
            segs = spatial.wall_free_segments.get(wall.name, [])
        else:
            segs = spatial.free_segments.get(wall.name, [])
        occupied = self._occupied_ranges(wall.name, placed, z)
        sub: list[tuple[float, float]] = []
        for seg in segs:
            for fs, fe in self._subtract_occupied(seg, occupied):
                if fe - fs > 0:
                    sub.append((fs, fe))
        return sub

    def _resolve_centre(
        self,
        wall: Wall,
        sku: SKU,
        placed: dict[str, PlacedItem],
        spatial: SpatialEngineOutput,
        z: float,
    ) -> float | None:
        """Centre of wall, accounting for placed items.

        Picks the collision-free sub-range whose centre is closest to the true
        wall centre and that can fit the SKU. Returns x such that the SKU sits
        centred inside that sub-range.
        """
        candidates = [
            (fs, fe) for fs, fe in self._free_subranges(wall, placed, spatial, z)
            if fe - fs >= sku.width_mm
        ]
        if not candidates:
            return None
        wall_centre = wall.length_mm / 2.0
        best = min(candidates, key=lambda r: abs((r[0] + r[1]) / 2.0 - wall_centre))
        fs, fe = best
        return fs + (fe - fs - sku.width_mm) / 2.0

    def _resolve_end(
        self,
        wall: Wall,
        sku: SKU,
        placed: dict[str, PlacedItem],
        spatial: SpatialEngineOutput,
        z: float,
        side: str,
    ) -> float | None:
        """Leftmost / rightmost free position accounting for placed items."""
        candidates = [
            (fs, fe) for fs, fe in self._free_subranges(wall, placed, spatial, z)
            if fe - fs >= sku.width_mm
        ]
        if not candidates:
            return None
        if side == "left":
            fs, _ = min(candidates, key=lambda r: r[0])
            return fs
        fs, fe = max(candidates, key=lambda r: r[1])
        return fe - sku.width_mm

    def _near_window(
        self,
        wall: Wall,
        sku: SKU,
        spatial: SpatialEngineOutput,
        y: float,
        z: float,
    ) -> tuple[float, float, float] | None:
        """Place item near a window on the wall; clamp to free segment."""
        windows = [o for o in spatial.exclusions if o.wall == wall.anchor and o.kind == "window"]
        if not windows:
            return None
        win = windows[0]
        cx = win.offset_mm + win.width_mm / 2.0
        x = cx - sku.width_mm / 2.0
        x = self._clamp_to_seg(x, sku.width_mm, wall.name, spatial)
        return (x, y, z)

    def _resolve_next_to(
        self,
        ref_name: str,
        sku: SKU,
        wall: Wall,
        placed: dict[str, PlacedItem],
        z: float,
    ) -> tuple[float, float, float] | None:
        """Place adjacent to named item — right side first, then left.

        Enforces same-wall placement: if the reference item is on a different
        wall than the placement wall, returns None so the caller can fall back
        or override.
        """
        ref = self._find_by_name(ref_name, placed) or self._find_by_cat(ref_name, placed)
        if ref is None:
            return None
        if ref.anchor_wall != wall.name:
            return None
        y = ref.position_mm["y"]
        ref_x = ref.position_mm["x"]
        ref_w = ref.dimensions_mm["width"]

        x_right = ref_x + ref_w
        if (
            x_right + sku.width_mm <= wall.length_mm
            and self._position_clear(x_right, sku.width_mm, wall.name, placed, z, wall.length_mm)
        ):
            return (x_right, y, z)

        x_left = ref_x - sku.width_mm
        if (
            x_left >= 0
            and self._position_clear(x_left, sku.width_mm, wall.name, placed, z, wall.length_mm)
        ):
            return (x_left, y, z)

        return None

    def _resolve_above(
        self,
        ref_name: str,
        sku: SKU,
        placed: dict[str, PlacedItem],
    ) -> tuple[float, float, float] | None:
        """Place centred above named item.

        For range hoods, mounts at NKBA minimum clearance (610mm) above the
        cooktop surface (top of stove) so NKBA-18 is satisfied.
        """
        ref = self._find_by_name(ref_name, placed)
        if ref is None:
            ref = self._find_by_cat(ref_name, placed)
        if ref is None:
            return None
        ref_cx = ref.position_mm["x"] + ref.dimensions_mm["width"] / 2.0
        x = ref_cx - sku.width_mm / 2.0
        y = ref.position_mm["y"]
        combined = (sku.category + " " + sku.name).lower()
        if "hood" in combined:
            # Mount at NKBA clearance above cooktop top surface
            stove_top = ref.position_mm["z"] + ref.dimensions_mm["height"]
            z = max(stove_top + Z_HOOD_CLEARANCE_MM, Z_WALL_CAB_BOTTOM_MM)
        else:
            z = ref.position_mm["z"] + ref.dimensions_mm["height"]
        return (x, y, z)

    def _resolve_gap_before(
        self,
        ref_name: str,
        sku: SKU,
        placed: dict[str, PlacedItem],
        y: float,
        z: float,
    ) -> tuple[float, float, float] | None:
        """Place with GAP_LEAVE_BEFORE_MM buffer before named item."""
        ref = self._find_by_name(ref_name, placed)
        if ref is None:
            ref = self._find_by_cat(ref_name, placed)
        if ref is None:
            return None
        x = ref.position_mm["x"] - sku.width_mm - GAP_LEAVE_BEFORE_MM
        return (max(0.0, x), y, z)

    # ------------------------------------------------------------------ #
    # Free-segment helpers                                                 #
    # ------------------------------------------------------------------ #

    def _first_free(
        self,
        wall: Wall,
        sku: SKU,
        placed: dict[str, PlacedItem],
        spatial: SpatialEngineOutput,
    ) -> tuple[float, float, float] | None:
        """Find the first segment on wall with enough room for sku."""
        y = wall.thickness_mm
        z = Z_WALL_CAB_BOTTOM_MM if sku.category.lower() == "wall_cabinet" else Z_FLOOR_MM
        if z >= Z_LEVEL_SPLIT_MM and spatial.wall_free_segments:
            segs = spatial.wall_free_segments.get(wall.name, [])
        else:
            segs = spatial.free_segments.get(wall.name, [])
        occupied = self._occupied_ranges(wall.name, placed, z)

        for seg in segs:
            free = self._subtract_occupied(seg, occupied)
            for start, end in free:
                if end - start >= sku.width_mm + MIN_SEGMENT_MM:
                    return (start, y, z)
        return None

    def _clamp_to_seg(
        self,
        x: float,
        width: float,
        wall_name: str,
        spatial: SpatialEngineOutput,
    ) -> float:
        """Clamp x so item fits within any free segment on the wall."""
        segs = spatial.free_segments.get(wall_name, [])
        if not segs:
            return max(0.0, x)
        # Find enclosing segment
        for seg in segs:
            if seg.start_mm <= x <= seg.end_mm:
                return max(seg.start_mm, min(x, seg.end_mm - width))
        # No enclosing segment: clamp to whichever segment is nearest
        nearest = min(segs, key=lambda s: abs(s.start_mm - x))
        return max(nearest.start_mm, min(x, nearest.end_mm - width))

    def _occupied_ranges(
        self,
        wall_name: str,
        placed: dict[str, PlacedItem],
        z_level: float = Z_FLOOR_MM,
    ) -> list[tuple[float, float]]:
        """Return sorted (start, end) x-ranges on wall at the same z-level band.

        Floor-level items (z < 500) only block other floor items.
        Wall-level items (z >= 500) are blocked by other wall-level items AND by
        tall floor items whose top surface extends into the wall cabinet zone
        (Fix 4: fridge at z=0, height=1700mm extends to 1700mm > 1510mm wall-cab bottom).
        """
        is_floor = z_level < Z_LEVEL_SPLIT_MM
        ranges: list[tuple[float, float]] = []
        for item in placed.values():
            if item.anchor_wall != wall_name:
                continue
            item_z = item.position_mm["z"]
            item_h = item.dimensions_mm["height"]
            item_is_floor = item_z < Z_LEVEL_SPLIT_MM
            x = item.position_mm["x"]
            w = item.dimensions_mm["width"]

            if is_floor:
                # Floor level: only block other floor items
                if item_is_floor:
                    ranges.append((x, x + w))
            else:
                # Wall level: block wall items directly
                if not item_is_floor:
                    ranges.append((x, x + w))
                # Also block if a floor item is tall enough to reach wall-cab zone
                elif (item_z + item_h) > Z_WALL_CAB_BOTTOM_MM:
                    ranges.append((x, x + w))
        ranges.sort()
        return ranges

    def _subtract_occupied(
        self,
        seg: Segment,
        occupied: list[tuple[float, float]],
    ) -> list[tuple[float, float]]:
        """Split a segment by subtracting occupied ranges; return free sub-ranges."""
        free: list[tuple[float, float]] = [(seg.start_mm, seg.end_mm)]
        for occ_start, occ_end in occupied:
            next_free: list[tuple[float, float]] = []
            for fs, fe in free:
                if occ_end <= fs or occ_start >= fe:
                    next_free.append((fs, fe))
                else:
                    if fs < occ_start:
                        next_free.append((fs, occ_start))
                    if occ_end < fe:
                        next_free.append((occ_end, fe))
            free = next_free
        return free

    # ------------------------------------------------------------------ #
    # Collision detection                                                  #
    # ------------------------------------------------------------------ #

    def _detect_collisions(self, placed: dict[str, PlacedItem]) -> list[str]:
        """Return list of collision flag strings for non-whitelisted overlaps.

        Collisions are checked SAME-WALL only because position_mm is wall-local
        — comparing local x of an item on north_wall with local x of an item
        on east_wall produces false positives. Cross-wall corner overlaps in
        L/U layouts are handled by structural corner cabinets.
        """
        flags: list[str] = []
        items = list(placed.items())
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                id_a, a = items[i]
                id_b, b = items[j]
                if a.anchor_wall != b.anchor_wall:
                    continue
                tag_a = (a.category + " " + a.name).lower()
                tag_b = (b.category + " " + b.name).lower()
                if self._whitelisted(tag_a, tag_b):
                    continue
                if not self._overlap3d(a, b):
                    continue
                flags.append(f"COLLISION: {id_a} <-> {id_b}")
        return flags

    @staticmethod
    def _at_shared_corner(a: PlacedItem, b: PlacedItem) -> bool:
        """Return True if items on different walls overlap only near the shared corner.

        Two items on adjacent walls overlap in 3D when each one's depth-extrusion
        reaches into the wall the other is on. This is the L-corner — a normal
        kitchen detail, not a real collision.
        """
        a_depth = a.dimensions_mm["depth"]
        b_depth = b.dimensions_mm["depth"]
        # If the overlap region is bounded by both items' depths near the corner,
        # it's a corner-fit. We detect this by checking if each item extends only
        # within the other's depth-shadow.
        ax, ay = a.position_mm["x"], a.position_mm["y"]
        aw = a.dimensions_mm["width"]
        ad = a_depth
        bx, by = b.position_mm["x"], b.position_mm["y"]
        bw = b.dimensions_mm["width"]
        bd = b_depth
        ox = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
        oy = max(0.0, min(ay + ad, by + bd) - max(ay, by))
        # If the overlap is small enough to fit inside both depths, it's the corner
        return ox <= max(ad, bd) + 1.0 and oy <= max(ad, bd) + 1.0

    def _overlap3d(self, a: PlacedItem, b: PlacedItem) -> bool:
        """Return True if two PlacedItems overlap in 3D AABB space."""

        def _interval_overlap(a_min: float, a_max: float, b_min: float, b_max: float) -> bool:
            return a_min < b_max and b_min < a_max

        ax, ay, az = a.position_mm["x"], a.position_mm["y"], a.position_mm["z"]
        bx, by, bz = b.position_mm["x"], b.position_mm["y"], b.position_mm["z"]
        return (
            _interval_overlap(ax, ax + a.dimensions_mm["width"], bx, bx + b.dimensions_mm["width"])
            and _interval_overlap(
                ay, ay + a.dimensions_mm["depth"], by, by + b.dimensions_mm["depth"]
            )
            and _interval_overlap(
                az, az + a.dimensions_mm["height"], bz, bz + b.dimensions_mm["height"]
            )
        )

    # ------------------------------------------------------------------ #
    # Post-placement corrections                                           #
    # ------------------------------------------------------------------ #

    # How many cabinet walls each family is supposed to use.
    _FAMILY_WALL_COUNT: dict[str, int] = {"I": 1, "L": 2, "U": 3}

    def _cleanup_isolated_optionals(
        self,
        placed: dict[str, PlacedItem],
        preprocessing: PreprocessingOutput,
        spillover: list[str],
        family: str = "",
    ) -> None:
        """Remove cabinets that look isolated or violate user preferences.

        Rules (applied in order):
          1. base_only — if cabinet_preference == "base_only", remove every
             wall_cabinet and tall_cabinet.
          2. isolated optional — base/wall cabinet on a wall with no anchored
             appliance/sink is dropped (corner cabinets exempt; protected
             secondary walls also exempt so requested family is preserved).
          3. unsupported wall cab — wall_cabinet with no base/anchored item
             below at the same x-range is dropped.
        """
        intent = preprocessing.intent
        base_only = (intent.cabinet_preference or "").lower() == "base_only"
        required_walls = self._FAMILY_WALL_COUNT.get(family.upper(), 1)

        appliance_keys = (
            "fridge", "refrigerator", "sink", "stove", "range", "cooktop", "oven",
        )
        appliance_walls: set[str] = set()
        for item in placed.values():
            combined = (item.category + " " + item.name).lower()
            if any(k in combined for k in appliance_keys):
                appliance_walls.add(item.anchor_wall)

        # Build set of walls that MUST stay active to preserve the requested
        # family topology. Start with appliance walls; if family needs more,
        # promote the most-populated non-appliance walls to "protected".
        protected_walls: set[str] = set(appliance_walls)
        if len(protected_walls) < required_walls:
            wall_counts: dict[str, int] = {}
            for item in placed.values():
                if item.position_mm["z"] < Z_LEVEL_SPLIT_MM:
                    wall_counts[item.anchor_wall] = wall_counts.get(item.anchor_wall, 0) + 1
            extras = sorted(
                (w for w in wall_counts if w not in protected_walls),
                key=lambda w: wall_counts[w],
                reverse=True,
            )
            need = required_walls - len(protected_walls)
            for w in extras[:need]:
                protected_walls.add(w)
                logger.info(
                    "TYPOLOGY-PROTECT: %s spared from isolated cleanup (family=%s)",
                    w, family,
                )

        def _kind(item: PlacedItem) -> tuple[bool, bool, bool, bool]:
            cat = item.category.lower()
            name = item.name.lower()
            combined = cat + " " + name
            is_wall_cab = "wall_cabinet" in cat or "wall cabinet" in combined
            is_tall = any(kw in combined for kw in _TALL_KW)
            is_base = "base_cabinet" in cat or "base cabinet" in combined
            is_corner = any(kw in combined for kw in _CORNER_KW)
            return is_wall_cab, is_tall, is_base, is_corner

        # Rule 1: base_only — strip uppers and tall
        if base_only:
            for sku_id, item in list(placed.items()):
                is_wall_cab, is_tall, _, _ = _kind(item)
                if is_wall_cab or is_tall:
                    placed.pop(sku_id, None)
                    spillover.append(
                        f"BASE-ONLY-CLEANUP: {sku_id} removed (cabinet_preference=base_only)"
                    )
                    logger.info("BASE-ONLY-CLEANUP: removed %s", sku_id)

        # Rule 2: isolated optional on appliance-free, non-protected wall.
        # Only enforce when the layout actually has appliances somewhere; an empty
        # `appliance_walls` (e.g. unit tests of isolated cabinet placement) means
        # there's no main-run reference, so the rule cannot meaningfully apply.
        # `protected_walls` keeps secondary L/U walls from being stripped bare.
        if appliance_walls:
            for sku_id, item in list(placed.items()):
                is_wall_cab, _, is_base, is_corner = _kind(item)
                if is_corner:
                    continue
                if not (is_wall_cab or is_base):
                    continue
                if item.anchor_wall in protected_walls:
                    continue
                placed.pop(sku_id, None)
                spillover.append(
                    f"ISOLATED-CABINET: {sku_id} removed (no appliance on {item.anchor_wall})"
                )
                logger.info(
                    "ISOLATED-CABINET: removed %s from %s",
                    sku_id, item.anchor_wall,
                )

        # Rule 3: wall cab with no base/anchored item below at same x-range
        for sku_id, item in list(placed.items()):
            is_wall_cab, _, _, _ = _kind(item)
            if not is_wall_cab:
                continue
            wc_x = item.position_mm["x"]
            wc_w = item.dimensions_mm["width"]
            has_support = False
            for other in placed.values():
                if other is item:
                    continue
                if other.anchor_wall != item.anchor_wall:
                    continue
                if other.position_mm["z"] >= Z_LEVEL_SPLIT_MM:
                    continue  # only floor-level items count as support
                ow_is_wall_cab, _, _, _ = _kind(other)
                if ow_is_wall_cab:
                    continue
                ox = other.position_mm["x"]
                ow = other.dimensions_mm["width"]
                if wc_x < ox + ow and (wc_x + wc_w) > ox:
                    has_support = True
                    break
            if not has_support:
                placed.pop(sku_id, None)
                spillover.append(
                    f"UNSUPPORTED-WALL-CAB: {sku_id} removed (no base cabinet below)"
                )
                logger.info("UNSUPPORTED-WALL-CAB: removed %s", sku_id)

    # ------------------------------------------------------------------ #
    # L-shape secondary-wall repair                                        #
    # ------------------------------------------------------------------ #

    def _variant_l_strategy(self, variant_id: str) -> str:
        """Map variant_id to L-shape secondary-wall strategy.

        v1/vA → "cleaning"  (move sink+DW+tap to secondary)
        v2/vB → "cooking"   (move stove+hood to secondary)
        v3/vC → "minimal"   (keep appliances on primary; rely on protected wall)
        """
        if not variant_id:
            return "cleaning"
        last = variant_id[-1].upper()
        if last in ("1", "A"):
            return "cleaning"
        if last in ("2", "B"):
            return "cooking"
        if last in ("3", "C"):
            return "minimal"
        return "cleaning"

    def _wall_has_window(self, wall_name: str, spatial: SpatialEngineOutput) -> bool:
        """True if the named cabinet wall has at least one window opening."""
        wall = self._get_wall(wall_name, spatial)
        if wall is None:
            return False
        return any(o.kind == "window" and o.wall == wall.anchor for o in spatial.exclusions)

    def _maybe_repair_u_distribution(
        self,
        zone_plan: ZonePlannerOutput,
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
        placed: dict[str, PlacedItem],
        spillover: list[str],
    ) -> None:
        """Distribute cooling/cleaning/cooking across 3 walls for U-shape.

        No-op when family != U or fewer than 3 cabinet walls exist (capacity
        gating is done upstream; this is the safety net at placement time).
        """
        if zone_plan.family.upper() != "U":
            return
        cabinet_walls = [w for w in spatial.walls if w.has_cabinets]
        if len(cabinet_walls) < 3:
            return

        fridge_wall = sink_wall = stove_wall = None
        for item in placed.values():
            c = (item.category + " " + item.name).lower()
            if "dishwasher" in c or "hood" in c or "tap" in c:
                continue
            if "fridge" in c or "refrigerator" in c:
                fridge_wall = item.anchor_wall
            elif "sink" in c:
                sink_wall = item.anchor_wall
            elif "stove" in c or "range" in c or "cooktop" in c:
                stove_wall = item.anchor_wall

        used = {w for w in (fridge_wall, sink_wall, stove_wall) if w}
        if len(used) >= 3:
            return  # already a proper U

        cabinet_names = {w.name for w in cabinet_walls}
        unused = list(cabinet_names - used)
        if not unused:
            return

        # Prefer a window wall for the cleaning move (sink loves windows)
        window_unused = [w for w in unused if self._wall_has_window(w, spatial)]
        target = window_unused[0] if window_unused else unused[0]

        # First move: try cleaning to target
        if self._try_move_zone("sink", target, placed, preprocessing, spatial):
            spillover.append(f"U-REPAIR: moved cleaning to {target} (variant {zone_plan.variant_id})")
            logger.info("U-REPAIR: cleaning -> %s", target)
            used.add(target)
            if self._wall_has_window(target, spatial):
                spillover.append(f"SINK-WINDOW-PLACED: sink on {target}")
            # Second move (if still <3): cooking to remaining wall
            unused2 = list(cabinet_names - used)
            if unused2 and len(used) < 3:
                target2 = unused2[0]
                if self._try_move_zone("stove", target2, placed, preprocessing, spatial):
                    spillover.append(f"U-REPAIR: moved cooking to {target2} (variant {zone_plan.variant_id})")
                    logger.info("U-REPAIR: cooking -> %s", target2)
            return

        # First-move fallback: try cooking to target
        if self._try_move_zone("stove", target, placed, preprocessing, spatial):
            spillover.append(f"U-REPAIR: moved cooking to {target} (variant {zone_plan.variant_id})")
            logger.info("U-REPAIR: cooking -> %s", target)
            return

        spillover.append(f"TYPOLOGY-WEAK-U: could not distribute zones across 3 walls")
        logger.info("TYPOLOGY-WEAK-U: variant %s", zone_plan.variant_id)

    # ------------------------------------------------------------------ #
    # Family run template                                                  #
    # ------------------------------------------------------------------ #

    def _apply_family_run_template(
        self,
        zone_plan: ZonePlannerOutput,
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
        placed: dict[str, PlacedItem],
        spillover: list[str],
    ) -> None:
        """Enforce canonical family wall assignments; remove base cabs outside run span.

        Called after L/U repair passes but before gap-fill.

        L-shape safety net: if ALL major appliances are still on one wall after the
        repair pass (happens when variant_id maps to "minimal" strategy), force-move
        the sink cluster to the secondary wall so the L is genuine.

        Run-span cleanup (all families): any plain base cabinet already placed by Pass 1
        that lies entirely outside the span [leftmost_anchor_x … rightmost_anchor_x+w]
        on its wall is removed.  This prevents prep-zone base cabs from being scattered
        far from the appliance run before gap-fill fills in the correct positions.
        """
        family = zone_plan.family.upper()
        cabinet_walls = [w for w in spatial.walls if w.has_cabinets]

        # ---- L-shape: ensure sink is on secondary wall -----------------------
        if family == "L" and len(cabinet_walls) >= 2:
            fridge_wall = sink_wall = stove_wall = None
            for item in placed.values():
                c = (item.category + " " + item.name).lower()
                if "dishwasher" in c or "hood" in c or "tap" in c:
                    continue
                if "fridge" in c or "refrigerator" in c:
                    fridge_wall = item.anchor_wall
                elif "sink" in c:
                    sink_wall = item.anchor_wall
                elif "stove" in c or "range" in c or "cooktop" in c:
                    stove_wall = item.anchor_wall

            anchor_walls = {w for w in (fridge_wall, sink_wall, stove_wall) if w}
            if len(anchor_walls) < 2:
                primary = max(cabinet_walls, key=lambda w: w.length_mm).name
                secondary_names = [w.name for w in cabinet_walls if w.name != primary]
                if secondary_names:
                    window_sec = [w for w in secondary_names if self._wall_has_window(w, spatial)]
                    target = window_sec[0] if window_sec else secondary_names[0]
                    if self._try_move_zone("sink", target, placed, preprocessing, spatial):
                        spillover.append(
                            f"RUN-TEMPLATE-L: force-moved cleaning to {target} "
                            f"(L-shape requires 2 walls)"
                        )
                        logger.info("RUN-TEMPLATE-L: cleaning forced to %s", target)
                        if self._wall_has_window(target, spatial):
                            spillover.append(f"SINK-WINDOW-PLACED: sink on {target}")

        # ---- Run-span cleanup (all families) ---------------------------------
        # Keywords that act as anchors defining the run span on a wall.
        _SPAN_KW = (
            "fridge", "refrigerator", "sink", "stove", "range", "cooktop",
            "dishwasher", "oven", "microwave",
        )

        # Build run span for each wall: [leftmost_anchor_x, rightmost_anchor_end_x]
        run_spans: dict[str, tuple[float, float]] = {}
        for item in placed.values():
            combined = (item.category + " " + item.name).lower()
            if item.position_mm.get("z", 0.0) >= Z_LEVEL_SPLIT_MM:
                continue
            if not any(kw in combined for kw in _SPAN_KW):
                continue
            wall = item.anchor_wall
            x1 = item.position_mm["x"]
            x2 = x1 + item.dimensions_mm["width"]
            if wall in run_spans:
                s, e = run_spans[wall]
                run_spans[wall] = (min(s, x1), max(e, x2))
            else:
                run_spans[wall] = (x1, x2)

        # Remove plain base cabinets placed entirely outside the run span.
        for sku_id, item in list(placed.items()):
            combined = (item.category + " " + item.name).lower()
            if "base_cabinet" not in combined:
                continue
            # Corner / blind-corner cabinets are STRUCTURAL — they belong at the
            # corner of the wall (intentionally outside the appliance run span).
            # Removing them undoes the corner-cabinet pre-pass placement.
            if any(kw in combined for kw in _CORNER_KW):
                continue
            if item.position_mm.get("z", 0.0) >= Z_LEVEL_SPLIT_MM:
                continue
            wall = item.anchor_wall
            if wall not in run_spans:
                continue
            run_start, run_end = run_spans[wall]
            item_x1 = item.position_mm["x"]
            item_x2 = item_x1 + item.dimensions_mm["width"]
            if item_x2 <= run_start or item_x1 >= run_end:
                placed.pop(sku_id, None)
                spillover.append(
                    f"RUN-CLEANUP: {sku_id} removed (x=[{item_x1:.0f}-{item_x2:.0f}] "
                    f"outside run span [{run_start:.0f}-{run_end:.0f}] on {wall})"
                )
                logger.info(
                    "RUN-CLEANUP: %s at x=[%.0f-%.0f] outside span [%.0f-%.0f] on %s",
                    sku_id, item_x1, item_x2, run_start, run_end, wall,
                )

    def _maybe_repair_l_secondary_wall(
        self,
        zone_plan: ZonePlannerOutput,
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
        placed: dict[str, PlacedItem],
        spillover: list[str],
    ) -> None:
        """Move one major zone to the secondary wall if the L has collapsed.

        No-op when family != L, when only one cabinet wall exists, when
        appliances are already spread across walls, or when the variant
        strategy is "minimal" (v3).
        """
        if zone_plan.family.upper() != "L":
            return
        cabinet_walls = [w for w in spatial.walls if w.has_cabinets]
        if len(cabinet_walls) < 2:
            return

        fridge_wall = sink_wall = stove_wall = None
        for item in placed.values():
            combined = (item.category + " " + item.name).lower()
            if "dishwasher" in combined or "hood" in combined or "tap" in combined:
                continue
            if "fridge" in combined or "refrigerator" in combined:
                fridge_wall = item.anchor_wall
            elif "sink" in combined:
                sink_wall = item.anchor_wall
            elif "stove" in combined or "range" in combined or "cooktop" in combined:
                stove_wall = item.anchor_wall

        anchor_walls = {w for w in (fridge_wall, sink_wall, stove_wall) if w}
        if len(anchor_walls) >= 2:
            return  # already a real L

        if not anchor_walls:
            return  # nothing placed yet
        primary = next(iter(anchor_walls))
        # Prefer a window wall as the secondary when moving cleaning — sinks
        # benefit from window placement (NKBA preference, LAYOUT-01).
        candidates = [w.name for w in cabinet_walls if w.name != primary]
        if not candidates:
            return
        window_candidates = [w for w in candidates if self._wall_has_window(w, spatial)]

        strategy = self._variant_l_strategy(zone_plan.variant_id)
        if strategy == "minimal":
            return  # v3: don't move appliances

        first_choice = "sink" if strategy == "cleaning" else "stove"
        fallback    = "stove" if strategy == "cleaning" else "sink"

        secondary = window_candidates[0] if (strategy == "cleaning" and window_candidates) else candidates[0]

        for choice in (first_choice, fallback):
            if self._try_move_zone(choice, secondary, placed, preprocessing, spatial):
                spillover.append(
                    f"L-REPAIR: moved {choice} zone to {secondary} (variant {zone_plan.variant_id})"
                )
                logger.info(
                    "L-REPAIR: moved %s zone to %s for %s",
                    choice, secondary, zone_plan.variant_id,
                )
                if choice == "sink" and self._wall_has_window(secondary, spatial):
                    spillover.append(f"SINK-WINDOW-PLACED: sink on {secondary}")
                    logger.info("SINK-WINDOW-PLACED: %s on %s", zone_plan.variant_id, secondary)
                return

        spillover.append(
            f"TYPOLOGY-WEAK-L: could not move cleaning/cooking to {secondary}"
        )
        logger.info(
            "TYPOLOGY-WEAK-L: %s — no zone fits %s", zone_plan.variant_id, secondary,
        )

    def _try_move_zone(
        self,
        anchor_kind: str,
        target_wall_name: str,
        placed: dict[str, PlacedItem],
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
    ) -> bool:
        """Snapshot, remove anchor+dependents, re-place on target_wall, revert on collision."""
        target_wall = self._get_wall(target_wall_name, spatial)
        if target_wall is None:
            return False

        anchor_kw = {"sink": ("sink",), "stove": ("stove", "range", "cooktop")}[anchor_kind]
        dep_kw    = {
            "sink":  ("dishwasher", "tap", "faucet", "mixer"),
            "stove": ("hood",),
        }[anchor_kind]

        anchor_id: str | None = None
        dep_ids: list[str] = []
        for sid, item in placed.items():
            combined = (item.category + " " + item.name).lower()
            if any(kw in combined for kw in dep_kw):
                dep_ids.append(sid)
                continue
            if anchor_id is None and any(kw in combined for kw in anchor_kw):
                # don't mis-classify "dishwasher" as "sink"; dep_kw is checked first
                anchor_id = sid

        if anchor_id is None:
            return False

        anchor_sku = preprocessing.skus.get(anchor_id)
        if anchor_sku is None:
            return False
        dep_skus = {sid: preprocessing.skus.get(sid) for sid in dep_ids}
        if any(s is None for s in dep_skus.values()):
            return False

        # Snapshot for revert
        snapshot = dict(placed)
        snap_zone = {sid: placed[sid].zone_type for sid in [anchor_id, *dep_ids]}

        # Remove from placed so re-placement sees a fresh wall
        placed.pop(anchor_id, None)
        for sid in dep_ids:
            placed.pop(sid, None)

        # Place anchor at centre of target wall — or near window when moving sink
        # to a wall that has one (LAYOUT-01).
        anchor_x: float | None = None
        if anchor_kind == "sink" and self._wall_has_window(target_wall.name, spatial):
            win_coords = self._near_window(
                target_wall, anchor_sku, spatial,
                target_wall.thickness_mm, Z_FLOOR_MM,
            )
            if win_coords is not None:
                anchor_x = win_coords[0]
        if anchor_x is None:
            anchor_x = self._resolve_centre(
                target_wall, anchor_sku, placed, spatial, Z_FLOOR_MM
            )
        if anchor_x is None:
            placed.clear(); placed.update(snapshot)
            return False
        placed[anchor_id] = self._make_item(
            anchor_sku, snap_zone[anchor_id],
            anchor_x, target_wall.thickness_mm, Z_FLOOR_MM, target_wall.name,
        )

        # Place dependents
        for sid in dep_ids:
            dep_sku = dep_skus[sid]
            assert dep_sku is not None
            combined = (dep_sku.category + " " + dep_sku.name).lower()
            coords: tuple[float, float, float] | None
            dep_wall_name = target_wall.name
            if any(kw in combined for kw in ("tap", "faucet", "mixer")):
                a = placed[anchor_id]
                coords = (a.position_mm["x"], a.position_mm["y"], a.position_mm["z"])
                dep_wall_name = a.anchor_wall
            elif "dishwasher" in combined:
                coords = self._resolve_next_to(
                    "sink", dep_sku, target_wall, placed, Z_FLOOR_MM
                )
            elif "hood" in combined:
                coords = self._resolve_above("stove", dep_sku, placed)
                dep_wall_name = placed[anchor_id].anchor_wall
            else:
                coords = None

            if coords is None:
                placed.clear(); placed.update(snapshot)
                return False
            x, y, z = coords
            placed[sid] = self._make_item(
                dep_sku, snap_zone[sid], x, y, z, dep_wall_name,
            )

        # Reject if the move introduced any collision
        if self._detect_collisions(placed):
            placed.clear(); placed.update(snapshot)
            return False

        return True

    def _verify_typology(
        self,
        placed: dict[str, PlacedItem],
        family: str,
        spillover: list[str],
    ) -> None:
        """Verify the post-cleanup layout still matches the requested family.

        Counts the number of cabinet walls with at least one floor-level placed
        item. If the count is below the family's expected wall count, log a
        TYPOLOGY-VIOLATION so the validator can flag it. We do not attempt to
        manufacture items here — repair is left to upstream passes.
        """
        required = self._FAMILY_WALL_COUNT.get(family.upper(), 1)
        active_walls: set[str] = set()
        for item in placed.values():
            if item.position_mm["z"] < Z_LEVEL_SPLIT_MM:
                active_walls.add(item.anchor_wall)
        if len(active_walls) < required:
            logger.warning(
                "TYPOLOGY-VIOLATION: family=%s expects %d active wall(s); only %d present (%s)",
                family, required, len(active_walls), sorted(active_walls),
            )
            spillover.append(
                f"TYPOLOGY-VIOLATION: family={family} expects {required} active walls, "
                f"got {len(active_walls)} ({sorted(active_walls)})"
            )

    def _align_wall_cabs_above_base_cabs(
        self,
        placed: dict[str, PlacedItem],
        spatial: SpatialEngineOutput,
        spillover: list[str],
    ) -> None:
        """Snap wall cabinets so they sit above placed base cabinets.

        TDD rule: storage zone (wall cabinets) mounts ABOVE base cabinets at z=1510mm.
        A wall cabinet with no base cabinet below it looks floating in the 2D view.
        This pass aligns each offending wall cabinet to the nearest base-cabinet cluster.
        """
        for sku_id, item in list(placed.items()):
            if "wall_cabinet" not in item.category.lower():
                continue
            wall_name = item.anchor_wall

            # Target: any floor item except corner cabinets (they're already cluttered)
            # and except other wall cabinets.  Corner cabs must_attach_to corner —
            # stacking a wall cab directly above one makes the corner look more jammed.
            floor_items: list[PlacedItem] = [
                other
                for other in placed.values()
                if other.anchor_wall == wall_name
                and other.position_mm["z"] < Z_LEVEL_SPLIT_MM
                and "wall_cabinet" not in other.category.lower()
                and not any(
                    kw in (other.category + " " + other.name).lower()
                    for kw in _CORNER_KW
                )
            ]

            if not floor_items:
                continue

            wc_x = item.position_mm["x"]
            wc_w = item.dimensions_mm["width"]

            already_above = any(
                wc_x < (b.position_mm["x"] + b.dimensions_mm["width"])
                and (wc_x + wc_w) > b.position_mm["x"]
                for b in floor_items
            )
            if already_above:
                continue

            # Snap to nearest floor item by centre distance
            wc_cx = wc_x + wc_w / 2.0
            nearest = min(
                floor_items,
                key=lambda b: abs(
                    (b.position_mm["x"] + b.dimensions_mm["width"] / 2.0) - wc_cx
                ),
            )
            new_x = nearest.position_mm["x"]

            wall = self._get_wall(wall_name, spatial)
            if wall is not None:
                new_x = min(new_x, max(0.0, wall.length_mm - wc_w))
            new_x = max(0.0, new_x)

            if abs(new_x - wc_x) > 1.0:
                item.position_mm["x"] = new_x
                logger.info(
                    "ALIGN-WALL-CAB: %s x=%.0f -> %.0f on %s (snapped above base cabinet)",
                    sku_id,
                    wc_x,
                    new_x,
                    wall_name,
                )

    def _remove_wall_cabs_over_windows(
        self,
        placed: dict[str, PlacedItem],
        spatial: SpatialEngineOutput,
        spillover: list[str],
    ) -> None:
        """Remove wall cabinets whose x-span overlaps any window on that wall.

        Wall cabinets are placed using wall_free_segments (which excludes windows),
        but _align_wall_cabs_above_base_cabs may snap them into a window zone.
        This post-pass re-enforces the window exclusion.
        """
        for sku_id, item in list(placed.items()):
            if "wall_cabinet" not in item.category.lower():
                continue
            wall_obj = self._get_wall(item.anchor_wall, spatial)
            if wall_obj is None:
                continue
            wc_x = item.position_mm["x"]
            wc_w = item.dimensions_mm["width"]
            windows = [
                o for o in spatial.exclusions
                if o.kind == "window" and o.wall == wall_obj.anchor
            ]
            for win in windows:
                if wc_x < (win.offset_mm + win.width_mm) and (wc_x + wc_w) > win.offset_mm:
                    placed.pop(sku_id, None)
                    spillover.append(
                        f"WALL-CABINET-REMOVED: {sku_id} overlaps window on {item.anchor_wall}"
                    )
                    logger.info(
                        "WALL-CABINET-REMOVED: %s overlaps window [%.0f-%.0f] on %s",
                        sku_id, win.offset_mm, win.offset_mm + win.width_mm, item.anchor_wall,
                    )
                    break

    def _fill_all_gaps_with_base_cabinets(
        self,
        placed: dict[str, PlacedItem],
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
        spillover: list[str],
        assigned_walls: set[str] | None = None,
        variant_id: str = "",
        family: str = "",
    ) -> None:
        """Pass 2: fill every gap > 50mm on zone-assigned cabinet walls with base cabinets.

        Collects ALL unplaced base cabinets from every zone and distributes them
        to fill spaces between appliances before Pass 3 assigns wall cabinets.
        Prioritises walls that already have appliances (to close continuous-run gaps).
        Only fills walls that appear in the zone plan (respects I-shape single-wall layouts).
        Cabinet size preference is variant-aware:
          v1 → largest first (maximise counter run)
          v2 → medium first (balanced)
          v3 → smallest first (minimal cost, matches "use narrower SKUs" seed)
        """
        CONTINUOUS_RUN_GAP_MM: float = 50.0
        placed_ids: set[str] = set(placed.keys())

        # Collect unplaced regular base cabinets (exclude corner cabs — they require corner placement)
        unplaced: list[SKU] = []
        for zone_skus in preprocessing.zone_groups.values():
            for sku in zone_skus:
                if (
                    sku.sku_id not in placed_ids
                    and "base_cabinet" in sku.category.lower()
                    and not self._is_corner_cabinet(sku)
                ):
                    unplaced.append(sku)

        # Variant-aware size preference: v3 prefers narrow cabs, v2 medium, v1 widest.
        vidx = self._i_variant_index(variant_id)
        if vidx == 3:
            unplaced.sort(key=lambda s: s.width_mm)           # smallest first
        elif vidx == 2:
            mid = sum(s.width_mm for s in unplaced) / max(len(unplaced), 1)
            unplaced.sort(key=lambda s: abs(s.width_mm - mid))  # closest to median
        else:
            unplaced.sort(key=lambda s: s.width_mm, reverse=True)  # largest first

        # Minimum base_cabinet width across ALL base cabs (placed + unplaced) — used
        # to detect gaps that are fillable in principle but have no candidate that fits.
        all_base_widths = [
            sku.width_mm
            for zone_skus in preprocessing.zone_groups.values()
            for sku in zone_skus
            if "base_cabinet" in sku.category.lower() and not self._is_corner_cabinet(sku)
        ]
        min_base_width: float = min(all_base_widths, default=0.0)

        if not unplaced:
            return

        # Walls with appliances first, then other cabinet walls
        appliance_walls: list[str] = []
        other_walls: list[str] = []
        for wall in spatial.walls:
            if not wall.has_cabinets:
                continue
            has_appliance = any(
                item.anchor_wall == wall.name
                and any(kw in (item.category + " " + item.name).lower()
                        for kw in ("stove", "fridge", "sink", "range", "refrigerator"))
                for item in placed.values()
            )
            (appliance_walls if has_appliance else other_walls).append(wall.name)

        # Anchor keywords that define the run span on each wall.
        _SPAN_ANCHORS = (
            "fridge", "refrigerator", "sink", "stove", "range", "cooktop",
            "dishwasher", "oven", "microwave",
        )

        # Per-wall fill cap based on family + variant + role (primary/secondary).
        # I-shape uses no cap (fills its single wall fully).
        fam_upper = (family or "").upper()
        cap_active = fam_upper in ("L", "U")

        for wall_name in appliance_walls + other_walls:
            # Skip walls not in the active zone plan (e.g. east_wall for I-shape layouts)
            if assigned_walls and wall_name not in assigned_walls:
                continue
            wall = self._get_wall(wall_name, spatial)
            if wall is None:
                continue

            # Determine wall role + cap for this variant.
            role = "primary" if wall_name in appliance_walls else "secondary"
            cap_mm = (
                _FILL_CAP_MM[role].get(vidx, _FILL_CAP_MM[role][2])
                if cap_active else float("inf")
            )
            mm_added_this_wall: float = 0.0

            # Run-span: only fill gaps WITHIN the span of anchor appliances already
            # placed on this wall.  Prevents base cabs from being scattered in empty
            # areas far from the appliance run.
            span_items = [
                it for it in placed.values()
                if it.anchor_wall == wall_name
                and it.position_mm.get("z", 0.0) < Z_LEVEL_SPLIT_MM
                and any(kw in (it.category + " " + it.name).lower() for kw in _SPAN_ANCHORS)
            ]
            if span_items:
                run_start = min(it.position_mm["x"] for it in span_items)
                run_end = max(
                    it.position_mm["x"] + it.dimensions_mm["width"] for it in span_items
                )
            else:
                run_start = 0.0
                run_end = wall.length_mm

            segs = spatial.free_segments.get(wall.name, [])
            changed = True
            while changed and unplaced and mm_added_this_wall < cap_mm:
                changed = False
                occupied = self._occupied_ranges(wall.name, placed, Z_FLOOR_MM)
                for seg in segs:
                    if mm_added_this_wall >= cap_mm:
                        break
                    for free_start, free_end in self._subtract_occupied(seg, occupied):
                        if mm_added_this_wall >= cap_mm:
                            break
                        # Clamp to run span — don't scatter base cabs outside appliance bounds
                        fill_start = max(free_start, run_start)
                        fill_end = min(free_end, run_end)
                        if fill_end - fill_start <= CONTINUOUS_RUN_GAP_MM:
                            continue
                        for sku in list(unplaced):
                            if mm_added_this_wall + sku.width_mm > cap_mm:
                                continue  # skip — would overshoot cap; try a smaller cab
                            if sku.width_mm <= (fill_end - fill_start):
                                # Safety net: verify no overlap with any floor-level run unit.
                                if not self._position_clear(
                                    fill_start, sku.width_mm, wall.name, placed,
                                    Z_FLOOR_MM, wall.length_mm,
                                ):
                                    logger.warning(
                                        "GAP-FILL: %s at x=%.0f on %s would overlap — skipped",
                                        sku.sku_id, fill_start, wall.name,
                                    )
                                    break
                                placed[sku.sku_id] = self._make_item(
                                    sku, "preparation",
                                    fill_start, wall.thickness_mm, Z_FLOOR_MM, wall.name,
                                )
                                placed_ids.add(sku.sku_id)
                                unplaced.remove(sku)
                                mm_added_this_wall += sku.width_mm
                                logger.debug(
                                    "GAP-FILL: %s at x=%.0f on %s (filled %.0f/%.0f mm)",
                                    sku.sku_id, fill_start, wall.name,
                                    mm_added_this_wall, cap_mm,
                                )
                                changed = True
                                break

            # Log unfillable gaps within the run span — gaps > tolerance but smaller than
            # the smallest available cabinet.  Gaps outside the run span are intentionally
            # empty (run-bounded fill) and are NOT logged as END-FILLER.
            if min_base_width > 0:
                occupied_final = self._occupied_ranges(wall.name, placed, Z_FLOOR_MM)
                for seg in segs:
                    for gap_start, gap_end in self._subtract_occupied(seg, occupied_final):
                        # Only log gaps within the run span
                        clamped_start = max(gap_start, run_start)
                        clamped_end = min(gap_end, run_end)
                        gap = clamped_end - clamped_start
                        if CONTINUOUS_RUN_GAP_MM < gap < min_base_width:
                            spillover.append(
                                f"END-FILLER: {gap:.0f}mm gap on {wall_name} "
                                f"(smallest base_cab {min_base_width:.0f}mm)"
                            )
                            logger.info(
                                "END-FILLER: %.0fmm unfillable gap on %s "
                                "(smallest base_cab=%.0fmm)",
                                gap, wall_name, min_base_width,
                            )
                            break  # one per wall is enough

    def _log_base_support_issues(
        self,
        placed: dict[str, PlacedItem],
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
        spillover: list[str],
    ) -> None:
        """After Pass 2, log missing landing support for fridge and sink.

        Semantics:
        - Fridge: freestanding unit; logs LANDING-MISSING if no adjacent base_cabinet.
        - Sink: self-supporting as a floor-level unit; logs SINK-BASE-IMPLIED when no
          adjacent base_cabinet is present (the sink footprint acts as its own base).
        - Stove/dishwasher: fully standalone floor-level units — no logging needed.
        Only logs — does not move or remove items.
        """
        LANDING_ADJ_MM: float = 1200.0
        base_cabs = [
            item for item in placed.values()
            if "base_cabinet" in item.category.lower()
        ]

        def _has_adjacent_base(appl: PlacedItem) -> bool:
            ax1 = appl.position_mm["x"]
            ax2 = ax1 + appl.dimensions_mm["width"]
            return any(
                bc.anchor_wall == appl.anchor_wall
                and max(
                    0.0,
                    max(ax1, bc.position_mm["x"])
                    - min(ax2, bc.position_mm["x"] + bc.dimensions_mm["width"]),
                ) <= LANDING_ADJ_MM
                for bc in base_cabs
            )

        # Fridge: needs adjacent landing counter (NKBA-LA-01 semantics)
        for item in placed.values():
            combined = (item.category + " " + item.name).lower()
            if "fridge" in combined or "refrigerator" in combined:
                if not _has_adjacent_base(item):
                    spillover.append(
                        f"LANDING-MISSING: {item.sku_id} (fridge) has no adjacent "
                        f"base_cabinet within {LANDING_ADJ_MM:.0f}mm on {item.anchor_wall}"
                    )
                    logger.info(
                        "LANDING-MISSING: %s on %s (no adjacent base_cabinet)",
                        item.sku_id, item.anchor_wall,
                    )

        # Sink: self-supporting floor unit; log if no adjacent base for landing space
        for item in placed.values():
            combined = (item.category + " " + item.name).lower()
            if "sink" in combined and "dishwasher" not in combined:
                if not _has_adjacent_base(item):
                    spillover.append(
                        f"SINK-BASE-IMPLIED: {item.sku_id} sink treated as supported "
                        f"base-level unit on {item.anchor_wall} (no adjacent base_cabinet)"
                    )
                    logger.info(
                        "SINK-BASE-IMPLIED: %s on %s (no adjacent base_cabinet)",
                        item.sku_id, item.anchor_wall,
                    )
        # Note: stove/range and dishwasher are fully standalone floor-level units
        # and do not need adjacent base cabinet support — no logging.

    def _enforce_stove_fridge_gap(
        self,
        placed: dict[str, PlacedItem],
        spatial: SpatialEngineOutput,
        spillover: list[str],
    ) -> None:
        """Fix 2: Ensure stove and fridge are >= GAP_FRIDGE_STOVE_MM apart on same wall."""
        stove = self._find_by_cat("stove", placed) or self._find_by_cat("range", placed)
        fridge = self._find_by_cat("fridge", placed) or self._find_by_cat("refrigerator", placed)
        if not (stove and fridge):
            return
        if stove.anchor_wall != fridge.anchor_wall:
            return  # Different walls — gap handled by room geometry

        wall = self._get_wall(stove.anchor_wall, spatial)
        if wall is None:
            return

        # Find fridge ID
        fridge_id = next((k for k, v in placed.items() if v is fridge), None)
        if fridge_id is None:
            return

        stove_x1 = stove.position_mm["x"]
        stove_x2 = stove_x1 + stove.dimensions_mm["width"]
        fridge_x1 = fridge.position_mm["x"]
        fridge_x2 = fridge_x1 + fridge.dimensions_mm["width"]

        # Gap = distance between the two intervals (positive = no overlap)
        if fridge_x1 >= stove_x2:
            gap = fridge_x1 - stove_x2
        else:
            gap = stove_x1 - fridge_x2

        if gap >= GAP_FRIDGE_STOVE_MM:
            return  # Already OK

        needed = GAP_FRIDGE_STOVE_MM - gap
        if fridge_x1 >= stove_x1:
            # Fridge is to the right — push it further right
            new_x = fridge_x1 + needed
            if new_x + fridge.dimensions_mm["width"] <= wall.length_mm:
                fridge.position_mm["x"] = new_x
                logger.info("GAP-ENFORCE: moved %s right to x=%.0f (gap was %.0fmm)", fridge_id, new_x, gap)
                spillover.append(f"GAP-ENFORCE: {fridge_id} moved to maintain {GAP_FRIDGE_STOVE_MM:.0f}mm stove-fridge gap")
                return
        else:
            # Fridge is to the left — push it further left
            new_x = fridge_x1 - needed
            if new_x >= 0:
                fridge.position_mm["x"] = new_x
                logger.info("GAP-ENFORCE: moved %s left to x=%.0f (gap was %.0fmm)", fridge_id, new_x, gap)
                spillover.append(f"GAP-ENFORCE: {fridge_id} moved to maintain {GAP_FRIDGE_STOVE_MM:.0f}mm stove-fridge gap")
                return

        logger.warning("GAP-ENFORCE: cannot achieve %.0fmm stove-fridge gap on %s — layout too tight", GAP_FRIDGE_STOVE_MM, wall.name)

    # ------------------------------------------------------------------ #
    # Run compactor                                                        #
    # ------------------------------------------------------------------ #

    def _compact_wall_runs(
        self,
        placed: dict[str, PlacedItem],
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
        spillover: list[str],
        variant_id: str = "",
        family: str = "",
    ) -> None:
        """Pack floor-level run items per wall into consecutive free segments.

        Moves gaps from between appliances to the end of the run.
        Corner cabs are exempted and validated in-place.
        Sink preserves window proximity when applicable.
        Hood and tap are re-anchored after packing.
        For I-shape, variant_id drives canonical order diversity.
        """
        for wall in spatial.walls:
            if not wall.has_cabinets:
                continue
            self._compact_single_wall(wall, placed, preprocessing, spatial, spillover, variant_id, family)
        self._reposition_dependents_after_compaction(placed, spillover)

    def _compact_single_wall(
        self,
        wall: Wall,
        placed: dict[str, PlacedItem],
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
        spillover: list[str],
        variant_id: str = "",
        family: str = "",
    ) -> None:
        """Compact all floor-level run items on one wall into free segments."""
        floor_items: list[tuple[str, PlacedItem]] = []
        for sid, it in placed.items():
            if it.anchor_wall != wall.name:
                continue
            if it.position_mm.get("z", 0.0) >= Z_LEVEL_SPLIT_MM:
                continue
            combined = (it.category + " " + it.name).lower()
            if any(kw in combined for kw in _COMPACT_EXEMPT_KW):
                continue
            floor_items.append((sid, it))

        if not floor_items:
            return

        # Corner/blind-corner cabs: validate position, then exempt from reordering.
        corner_ids: set[str] = set()
        pack_items: list[tuple[str, PlacedItem]] = []
        for sid, it in floor_items:
            sku = preprocessing.skus.get(sid)
            is_corner = (
                self._is_corner_cabinet(sku)
                if sku is not None
                else any(kw in (it.category + " " + it.name).lower() for kw in _CORNER_KW)
            )
            if is_corner:
                x, w = it.position_mm["x"], it.dimensions_mm["width"]
                at_edge = (
                    x <= WALL_END_TOLERANCE_MM
                    or (x + w) >= (wall.length_mm - WALL_END_TOLERANCE_MM)
                )
                if not at_edge:
                    spillover.append(
                        f"CORNER-SKIPPED: {sid} not at wall edge on {wall.name} "
                        f"(x={x:.0f})"
                    )
                    logger.info(
                        "CORNER-SKIPPED: %s not at wall edge on %s (x=%.0f)",
                        sid, wall.name, x,
                    )
                corner_ids.add(sid)
            else:
                pack_items.append((sid, it))

        if not pack_items:
            return

        segs = spatial.free_segments.get(wall.name, [])
        if not segs:
            return

        # Identify key anchor items
        sink_sid: str | None = next(
            (sid for sid, it in pack_items
             if "sink" in (it.category + " " + it.name).lower()
             and "dishwasher" not in (it.category + " " + it.name).lower()),
            None,
        )
        fridge_sid: str | None = next(
            (sid for sid, it in pack_items
             if "fridge" in (it.category + " " + it.name).lower()
             or "refrigerator" in (it.category + " " + it.name).lower()),
            None,
        )
        stove_sid: str | None = next(
            (sid for sid, it in pack_items
             if "stove" in (it.category + " " + it.name).lower()
             or "range" in (it.category + " " + it.name).lower()
             or "cooktop" in (it.category + " " + it.name).lower()),
            None,
        )

        # Window-sink check: if the wall has a window AND a sink, always attempt
        # window-anchored packing regardless of where the sink currently sits.
        # The sink may have been forced away from the window by a door constraint at
        # anchor time — we still want it as close to the window center as free segments allow.
        # _pack_window_anchored falls back to sequential if no valid anchor is achievable.
        window_center = self._get_wall_window_center(wall, spatial)
        sink_near_window = window_center is not None and sink_sid is not None

        # Fridge side: right if the fridge centre is past the wall midpoint.
        fridge_at_right = (
            fridge_sid is not None
            and placed[fridge_sid].position_mm["x"]
            + placed[fridge_sid].dimensions_mm["width"] / 2.0
            > wall.length_mm / 2.0
        )

        # Canonical sort: fridge first (or last if right-side), stove at end.
        # Base/tall cabs: left-of-sink -> rank 1, right-of-sink -> rank 5.
        sink_x = placed[sink_sid].position_mm["x"] if sink_sid else wall.length_mm / 2.0

        def _run_rank(sid_it: tuple[str, PlacedItem]) -> tuple[int, float]:
            sid, it = sid_it
            c = (it.category + " " + it.name).lower()
            ox = it.position_mm["x"]
            if "fridge" in c or "refrigerator" in c:
                return (9 if fridge_at_right else 0, ox)
            if "stove" in c or "range" in c or "cooktop" in c:
                return (8, ox)
            if "sink" in c and "dishwasher" not in c:
                return (2, ox)
            if "dishwasher" in c:
                return (3, ox)
            return (1 if ox < sink_x else 5, ox)

        # Variant diversity: each variant uses a different sink/DW order on the
        # cleaning wall so v1/v2/v3 look visually distinct.
        # I-shape: applied on the single active wall (all items here).
        # L/U-shape: applied on any wall that has the sink (cleaning wall only);
        #            other walls always use the standard _run_rank.
        # Window-anchor walls always collapse to v1 (window position dominates).
        is_i_shape = bool(family) and family.upper() == "I"
        is_lu = bool(family) and family.upper() in ("L", "U")
        wall_has_sink = sink_sid is not None
        vidx = self._i_variant_index(variant_id) if (is_i_shape or is_lu) else 1

        if (is_i_shape or (is_lu and wall_has_sink)) and not sink_near_window:
            i_rank = self._i_run_rank(vidx, sink_x, fridge_at_right)
            if vidx in (2, 3):
                default_order = [s for s, _ in sorted(pack_items, key=_run_rank)]
                variant_order = [s for s, _ in sorted(pack_items, key=i_rank)]
                if default_order == variant_order:
                    shape_label = "I-shape" if is_i_shape else family.upper() + "-shape"
                    spillover.append(
                        "VARIANT-COLLAPSED: I-shape compacted to same feasible order"
                    )
                    logger.info(
                        "VARIANT-COLLAPSED: %s v%d order same as v1 on %s",
                        shape_label, vidx, wall.name,
                    )
            pack_items.sort(key=i_rank)
        else:
            pack_items.sort(key=_run_rank)
            if (is_i_shape or (is_lu and wall_has_sink)) and sink_near_window and vidx in (2, 3):
                spillover.append(
                    "VARIANT-COLLAPSED: I-shape compacted to same feasible order"
                )
                logger.info(
                    "VARIANT-COLLAPSED: v%d window-anchor overrides on %s",
                    vidx, wall.name,
                )

        # Record stove's pre-compact position to detect wall-end pinning.
        # Applies to all families: if the stove was originally at the right end of
        # the wall (e.g. "right end of north_wall"), pin it back there after packing
        # so sequential compaction does not leave a gap at the wall end.
        stove_at_wall_end = False
        if stove_sid is not None and stove_sid in placed:
            stove_it = placed[stove_sid]
            stove_pre_x = stove_it.position_mm["x"]
            stove_w = stove_it.dimensions_mm["width"]
            wall_end = segs[-1].end_mm
            stove_at_wall_end = (stove_pre_x + stove_w) >= (wall_end - WALL_END_TOLERANCE_MM)

        # Pack
        new_positions: dict[str, float] = {}
        if sink_near_window and window_center is not None and sink_sid is not None:
            self._pack_window_anchored(
                pack_items, segs, window_center, sink_sid,
                placed, fridge_sid, stove_sid, new_positions, wall,
            )
        else:
            self._pack_sequential_run(
                pack_items, segs, placed,
                fridge_sid, stove_sid, new_positions, wall,
            )

        # Re-pin stove to wall right end if it was originally there.
        # Sequential packing places stove at cursor position (after all other items),
        # leaving a gap at the wall end. This restores the original pinned position.
        if stove_at_wall_end and stove_sid is not None and stove_sid in placed:
            stove_w = placed[stove_sid].dimensions_mm["width"]
            pinned_x = segs[-1].end_mm - stove_w
            if pinned_x >= segs[-1].start_mm:
                new_positions[stove_sid] = pinned_x
                logger.debug(
                    "COMPACT-PIN: stove %s re-pinned to wall end x=%.0f on %s",
                    stove_sid, pinned_x, wall.name,
                )

        for sid, nx in new_positions.items():
            if sid in placed:
                old_x = placed[sid].position_mm["x"]
                if abs(nx - old_x) > 0.5:
                    placed[sid].position_mm["x"] = nx
                    logger.debug(
                        "COMPACT: %s x=%.0f->%.0f on %s", sid, old_x, nx, wall.name,
                    )

    @staticmethod
    def _i_variant_index(variant_id: str) -> int:
        """Extract 1-based variant index from variant_id ('v1'->'1', 'variant_3'->'3')."""
        digits = "".join(c for c in variant_id if c.isdigit())
        return int(digits[-1]) if digits else 1

    def _i_run_rank(
        self,
        variant_idx: int,
        sink_x: float,
        fridge_at_right: bool,
    ) -> Callable[[tuple[str, PlacedItem]], tuple[int, float]]:
        """Return a sort key implementing I-shape canonical run order for variant_idx.

        v1 (default):  fridge | base_left | sink | DW    | base_right | stove
        v2:            fridge | base_left | DW   | sink   | base_right | stove
        v3:            fridge | all_bases         | sink  | DW         | stove
        """
        def rank(sid_it: tuple[str, PlacedItem]) -> tuple[int, float]:
            sid, it = sid_it
            c = (it.category + " " + it.name).lower()
            ox = it.position_mm["x"]
            if "fridge" in c or "refrigerator" in c:
                return (9 if fridge_at_right else 0, ox)
            if "stove" in c or "range" in c or "cooktop" in c:
                return (8, ox)
            is_sink = "sink" in c and "dishwasher" not in c
            is_dw = "dishwasher" in c
            if variant_idx == 2:
                if is_dw:
                    return (2, ox)
                if is_sink:
                    return (3, ox)
            else:
                if is_sink:
                    return (2, ox)
                if is_dw:
                    return (3, ox)
            # Base / prep / storage cabs
            if variant_idx == 3:
                return (1, ox)          # all bases pack left of sink
            return (1 if ox < sink_x else 5, ox)  # v1/v2: split at initial sink pos
        return rank

    def _wall_endpoint_global(
        self, wall: Wall, local_x: float
    ) -> tuple[float, float] | None:
        """Convert a wall-local x-offset to global (x, y) of the wall's front face.

        Used to find which end of a wall meets another cabinet wall (the L/U
        corner-join). Returns None if the wall geometry is malformed.
        """
        anchor = wall.anchor.lower()
        try:
            if anchor in ("north", "south"):
                xs = [p["x"] for p in wall.points]
                ys = [p["y"] for p in wall.points]
                wall_y = max(ys) if anchor == "north" else min(ys)
                return (min(xs) + local_x, wall_y)
            if anchor in ("east", "west"):
                xs = [p["x"] for p in wall.points]
                ys = [p["y"] for p in wall.points]
                wall_x = max(xs) if anchor == "east" else min(xs)
                return (wall_x, min(ys) + local_x)
        except (KeyError, ValueError, IndexError):
            pass
        return None

    def _get_meeting_corner_x(
        self, wall: Wall, spatial: SpatialEngineOutput
    ) -> float | None:
        """Return wall-local x (0.0 or wall.length_mm) of the corner that meets
        another cabinet wall, or None if this wall is isolated.

        Used in L/U packing so items pack AWAY from the corner-join, leaving any
        tail gap at the outer end of the wall (not at the corner — that's ugly).
        """
        start_global = self._wall_endpoint_global(wall, 0.0)
        end_global = self._wall_endpoint_global(wall, wall.length_mm)
        if start_global is None or end_global is None:
            return None
        TOL = 150.0  # mm
        for other in spatial.walls:
            if not other.has_cabinets or other.name == wall.name:
                continue
            for ox_local in (0.0, other.length_mm):
                o_global = self._wall_endpoint_global(other, ox_local)
                if o_global is None:
                    continue
                if (abs(start_global[0] - o_global[0]) < TOL
                        and abs(start_global[1] - o_global[1]) < TOL):
                    return 0.0
                if (abs(end_global[0] - o_global[0]) < TOL
                        and abs(end_global[1] - o_global[1]) < TOL):
                    return wall.length_mm
        return None

    def _get_wall_window_center(
        self, wall: Wall, spatial: SpatialEngineOutput
    ) -> float | None:
        """Return the x-offset of the first window centre on this wall, or None."""
        for exc in spatial.exclusions:
            if exc.kind == "window" and exc.wall == wall.anchor:
                return exc.offset_mm + exc.width_mm / 2.0
        return None

    def _pack_sequential_run(
        self,
        pack_items: list[tuple[str, PlacedItem]],
        segs: list[Segment],
        placed: dict[str, PlacedItem],
        fridge_sid: str | None,
        stove_sid: str | None,
        new_positions: dict[str, float],
        wall: Wall,
    ) -> None:
        """Pack items consecutively through free segments, respecting door/opening gaps.

        The cursor advances through segments in order; items that don't fit in the
        current segment skip to the next segment start.  Stove-fridge gap is enforced
        by advancing the cursor before whichever of the pair arrives second.
        Items that cannot fit in any segment are left at their original x.
        """
        seg_idx = 0
        cursor = segs[0].start_mm

        for sid, it in pack_items:
            w = it.dimensions_mm["width"]

            # Enforce stove-fridge gap: whichever arrives second advances the cursor.
            if sid == stove_sid and fridge_sid in new_positions:
                fridge_right = (
                    new_positions[fridge_sid]
                    + placed[fridge_sid].dimensions_mm["width"]
                )
                gap = cursor - fridge_right
                if 0.0 <= gap < GAP_FRIDGE_STOVE_MM:
                    cursor += GAP_FRIDGE_STOVE_MM - gap
            elif sid == fridge_sid and stove_sid in new_positions:
                stove_right = (
                    new_positions[stove_sid]
                    + placed[stove_sid].dimensions_mm["width"]
                )
                gap = cursor - stove_right
                if 0.0 <= gap < GAP_FRIDGE_STOVE_MM:
                    cursor += GAP_FRIDGE_STOVE_MM - gap

            placed_ok = False
            while seg_idx < len(segs):
                seg = segs[seg_idx]
                if cursor < seg.start_mm:
                    cursor = seg.start_mm
                if cursor + w <= seg.end_mm:
                    new_positions[sid] = cursor
                    cursor += w
                    placed_ok = True
                    break
                seg_idx += 1
                if seg_idx < len(segs):
                    cursor = segs[seg_idx].start_mm

            if not placed_ok:
                logger.warning(
                    "COMPACT: %s (w=%.0f) cannot fit in any segment on %s",
                    sid, w, wall.name,
                )

    def _pack_window_anchored(
        self,
        pack_items: list[tuple[str, PlacedItem]],
        segs: list[Segment],
        window_center: float,
        sink_sid: str,
        placed: dict[str, PlacedItem],
        fridge_sid: str | None,
        stove_sid: str | None,
        new_positions: dict[str, float],
        wall: Wall,
    ) -> None:
        """Pack around a window-anchored sink: items left of sink pack toward the window,
        items right of sink pack away from it.  Falls back to sequential if the window
        anchor position is not achievable within the wall's free segments.
        """
        sink_w = placed[sink_sid].dimensions_mm["width"]
        ideal_sink_x = window_center - sink_w / 2.0

        # Find a valid segment for the sink at or near the window centre.
        sink_anchor: float | None = None
        for seg in segs:
            clamped = max(seg.start_mm, min(ideal_sink_x, seg.end_mm - sink_w))
            if clamped + sink_w <= seg.end_mm:
                sink_anchor = clamped
                break

        if sink_anchor is None:
            logger.info(
                "COMPACT-WIN: window anchor %.0f not achievable on %s — sequential fallback",
                window_center, wall.name,
            )
            self._pack_sequential_run(
                pack_items, segs, placed, fridge_sid, stove_sid, new_positions, wall,
            )
            return

        sink_pos = next(i for i, (sid, _) in enumerate(pack_items) if sid == sink_sid)
        dw_pos = next(
            (i for i, (sid, it) in enumerate(pack_items)
             if "dishwasher" in (it.category + " " + it.name).lower()),
            None,
        )

        left_items = [
            (sid, it) for i, (sid, it) in enumerate(pack_items)
            if i < sink_pos and (dw_pos is None or i != dw_pos)
        ]
        sink_dw_items = [
            (sid, it) for i, (sid, it) in enumerate(pack_items)
            if i == sink_pos or (dw_pos is not None and i == dw_pos)
        ]
        right_items = [
            (sid, it) for i, (sid, it) in enumerate(pack_items)
            if i > sink_pos and (dw_pos is None or i != dw_pos)
        ]

        # Pack left items left-to-right, stopping at sink_anchor.
        cursor = segs[0].start_mm
        for sid, it in left_items:
            w = it.dimensions_mm["width"]
            if cursor + w <= sink_anchor:
                new_positions[sid] = cursor
                cursor += w
            # else: item doesn't fit before window — leave original x

        # Place sink+DW block at the window anchor.
        cursor = sink_anchor
        for sid, it in sink_dw_items:
            new_positions[sid] = cursor
            cursor += it.dimensions_mm["width"]

        # Pack right items from cursor onward through remaining segments.
        r_cursor = cursor
        r_seg_idx = 0
        while r_seg_idx < len(segs) and segs[r_seg_idx].end_mm <= r_cursor:
            r_seg_idx += 1
        for sid, it in right_items:
            w = it.dimensions_mm["width"]
            placed_ok = False
            while r_seg_idx < len(segs):
                seg = segs[r_seg_idx]
                if r_cursor < seg.start_mm:
                    r_cursor = seg.start_mm
                if r_cursor + w <= seg.end_mm:
                    new_positions[sid] = r_cursor
                    r_cursor += w
                    placed_ok = True
                    break
                r_seg_idx += 1
                if r_seg_idx < len(segs):
                    r_cursor = segs[r_seg_idx].start_mm
            if not placed_ok:
                logger.warning(
                    "COMPACT-WIN: %s (w=%.0f) cannot fit right of sink on %s",
                    sid, w, wall.name,
                )

    def _reposition_dependents_after_compaction(
        self,
        placed: dict[str, PlacedItem],
        spillover: list[str],
    ) -> None:
        """Re-anchor hood to stove centre and tap to sink x after compaction."""
        stove = next(
            (
                it for it in placed.values()
                if (
                    "stove" in (it.category + " " + it.name).lower()
                    or "range" in (it.category + " " + it.name).lower()
                    or "cooktop" in (it.category + " " + it.name).lower()
                )
                and it.position_mm.get("z", 0.0) < Z_LEVEL_SPLIT_MM
            ),
            None,
        )
        sink = next(
            (
                it for it in placed.values()
                if "sink" in (it.category + " " + it.name).lower()
                and "dishwasher" not in (it.category + " " + it.name).lower()
                and it.position_mm.get("z", 0.0) < Z_LEVEL_SPLIT_MM
            ),
            None,
        )

        for sid, it in placed.items():
            combined = (it.category + " " + it.name).lower()
            if (
                "hood" in combined
                and stove is not None
                and it.anchor_wall == stove.anchor_wall
            ):
                new_x = stove.position_mm["x"] + (
                    stove.dimensions_mm["width"] - it.dimensions_mm["width"]
                ) / 2.0
                if abs(new_x - it.position_mm["x"]) > 0.5:
                    it.position_mm["x"] = new_x
                    logger.debug("COMPACT-DEP: hood %s -> x=%.0f", sid, new_x)
            elif (
                any(kw in combined for kw in ("tap", "faucet", "mixer"))
                and sink is not None
                and it.anchor_wall == sink.anchor_wall
            ):
                new_x = sink.position_mm["x"]
                if abs(new_x - it.position_mm["x"]) > 0.5:
                    it.position_mm["x"] = new_x
                    logger.debug("COMPACT-DEP: tap %s -> x=%.0f", sid, new_x)

    # ------------------------------------------------------------------ #
    # Work triangle                                                        #
    # ------------------------------------------------------------------ #

    def _check_work_triangle(
        self,
        placed: dict[str, PlacedItem],
        spatial: SpatialEngineOutput,
        spillover: list[str],
    ) -> None:
        """Log WORKFLOW-03 violation when work triangle perimeter is out of range."""
        sink = self._find_by_cat("sink", placed)
        fridge = self._find_by_cat("fridge", placed) or self._find_by_cat("refrigerator", placed)
        stove = self._find_by_cat("stove", placed) or self._find_by_cat("range", placed)

        if not (sink and fridge and stove):
            return

        perimeter = (
            self._dist2d_global(sink, fridge, spatial)
            + self._dist2d_global(fridge, stove, spatial)
            + self._dist2d_global(stove, sink, spatial)
        )

        if perimeter < WORK_TRIANGLE_MIN_MM or perimeter > WORK_TRIANGLE_MAX_MM:
            logger.warning(
                "WORKFLOW-03: work triangle perimeter %.0fmm outside [%.0f, %.0f]mm",
                perimeter,
                WORK_TRIANGLE_MIN_MM,
                WORK_TRIANGLE_MAX_MM,
            )
            spillover.append(
                f"WORKFLOW-03: triangle {perimeter:.0f}mm"
                f" (valid {WORK_TRIANGLE_MIN_MM:.0f}-{WORK_TRIANGLE_MAX_MM:.0f}mm)"
            )

    def _dist2d(self, a: PlacedItem, b: PlacedItem) -> float:
        """Local-coord 2D distance (same-wall only)."""
        ax = a.position_mm["x"] + a.dimensions_mm["width"] / 2.0
        ay = a.position_mm["y"] + a.dimensions_mm["depth"] / 2.0
        bx = b.position_mm["x"] + b.dimensions_mm["width"] / 2.0
        by = b.position_mm["y"] + b.dimensions_mm["depth"] / 2.0
        return float(((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5)

    def _global_xy(self, item: PlacedItem, spatial: SpatialEngineOutput) -> tuple[float, float]:
        """Convert wall-local left-edge coords to global 2D room center (x, y)."""
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

    def _dist2d_global(self, a: PlacedItem, b: PlacedItem, spatial: SpatialEngineOutput) -> float:
        """Global 2D Euclidean distance between item centers (works across walls)."""
        ax, ay = self._global_xy(a, spatial)
        bx, by = self._global_xy(b, spatial)
        return float(((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5)

    # ------------------------------------------------------------------ #
    # Item assembly helpers                                                #
    # ------------------------------------------------------------------ #

    def _place_corner_cabs_first(
        self,
        zone_plan: ZonePlannerOutput,
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
        placed: dict[str, PlacedItem],
        spillover: list[str],
    ) -> None:
        """Place corner cabinets at wall corners BEFORE item_hints claims them.

        For L/U layouts, corner cabs (SKU-C11 etc.) need a real corner. If fridge
        or tall cab via item_hints claims x=0 or x=wall_length-w first, the corner
        cab gets skipped with CORNER-SKIPPED. Running this pre-pass ensures corner
        cabs land first; fridge/stove then fall through to non-corner positions in
        Pass 1's corner-fallback logic.
        """
        family = zone_plan.family.upper()
        if family not in ("L", "U"):
            return  # I-shape has no meeting corner — corner cabs N/A

        for wall_name in set(zone_plan.zone_assignments.values()):
            wall = self._get_wall(wall_name, spatial)
            if wall is None:
                continue
            for sku, zone_type in self._items_for_wall(wall_name, zone_plan, preprocessing):
                if not self._is_corner_cabinet(sku):
                    continue
                if sku.sku_id in placed:
                    continue
                y = wall.thickness_mm
                # Try right end first (typical L/U meeting), then left end.
                for corner_x in (max(0.0, wall.length_mm - sku.width_mm), 0.0):
                    if self._position_clear(
                        corner_x, sku.width_mm, wall.name, placed, Z_FLOOR_MM, wall.length_mm
                    ):
                        placed[sku.sku_id] = self._make_item(
                            sku, zone_type, corner_x, y, Z_FLOOR_MM, wall.name
                        )
                        logger.info(
                            "CORNER-FIRST: %s placed at x=%.0f on %s",
                            sku.sku_id, corner_x, wall.name,
                        )
                        break

    def _items_for_wall(
        self,
        wall_name: str,
        zone_plan: ZonePlannerOutput,
        preprocessing: PreprocessingOutput,
    ) -> list[tuple[SKU, str]]:
        """Return (SKU, zone_type) pairs assigned to this wall, sorted by priority."""
        result: list[tuple[SKU, str]] = []
        for zone_name, assigned_wall in zone_plan.zone_assignments.items():
            if assigned_wall != wall_name:
                continue
            skus_in_zone = preprocessing.zone_groups.get(zone_name.lower().strip(), [])
            for sku in skus_in_zone:
                result.append((sku, zone_name))
        result.sort(key=lambda t: self._priority_rank(t[0]))
        return result

    def _priority_rank(self, sku: SKU) -> int:
        """Return placement priority.

        -2 = corner cabinet (must be placed first — structural, claims L-corner)
        -1 = fridge / tall cabinet (claims corner end before anchored items)
         0 = anchored (sink, stove — fixed to utilities)
         1 = dependent (hood, dishwasher, tap — follows an anchor)
         2 = fill (base/wall cabinets)
        """
        combined = (sku.category + " " + sku.name).lower()
        # Corner cabinets are structural — must claim their corner before ANYTHING else
        if sku.must_attach_to == "corner" or any(kw in combined for kw in _CORNER_KW):
            return -2
        # Fridge and tall cabinets claim a corner/end before stove and sink are placed
        if any(kw in combined for kw in _FRIDGE_KW) or any(kw in combined for kw in _TALL_KW):
            return -1
        for kw in _ANCHORED_KW:
            if kw in combined:
                return 0
        for kw in _DEPENDENT_KW:
            if kw in combined:
                return 1
        return 2

    def _is_dependent(self, sku: SKU) -> bool:
        """Return True if sku is a dependent item (must follow an anchor)."""
        combined = (sku.category + " " + sku.name).lower()
        return any(kw in combined for kw in _DEPENDENT_KW)

    def _is_fridge_or_tall(self, sku: SKU) -> bool:
        """Return True if sku is a fridge or tall cabinet that should claim a corner."""
        combined = (sku.category + " " + sku.name).lower()
        return any(kw in combined for kw in _FRIDGE_KW) or any(kw in combined for kw in _TALL_KW)

    def _is_corner_cabinet(self, sku: SKU) -> bool:
        """Return True if sku must be placed at a wall corner (must_attach_to=corner)."""
        if sku.must_attach_to == "corner":
            return True
        combined = (sku.category + " " + sku.name).lower()
        return any(kw in combined for kw in _CORNER_KW)

    def _is_tap(self, sku: SKU) -> bool:
        """Return True if sku is a tap/faucet that should co-locate with the sink."""
        combined = (sku.category + " " + sku.name).lower()
        return any(kw in combined for kw in _TAP_KW)

    def _is_required_appliance(self, sku: SKU) -> bool:
        """Return True if sku is a required appliance that must never be dropped."""
        combined = (sku.category + " " + sku.name).lower()
        return any(kw in combined for kw in _REQUIRED_APPLIANCE_KW)

    def _inherent_term(self, sku: SKU) -> str:
        """Return the inherent semantic term for a dependent item."""
        combined = (sku.category + " " + sku.name).lower()
        if "hood" in combined:
            return "above stove"
        if "dishwasher" in combined:
            return "next to sink"
        if "tap" in combined:
            return "next to sink"
        return "next to sink"

    def _extract_pos_term(self, strategy: str) -> str:
        """Extract the positional semantic term from a strategy string."""
        return strategy.strip().lower()

    # ------------------------------------------------------------------ #
    # Lookup helpers                                                       #
    # ------------------------------------------------------------------ #

    def _find_by_name(self, ref_name: str, placed: dict[str, PlacedItem]) -> PlacedItem | None:
        """Find placed item whose name contains ref_name (case-insensitive)."""
        ref_lower = ref_name.lower()
        for item in placed.values():
            if ref_lower in item.name.lower():
                return item
        return None

    def _find_by_cat(self, keyword: str, placed: dict[str, PlacedItem]) -> PlacedItem | None:
        """Find placed item whose category contains keyword (case-insensitive)."""
        kw_lower = keyword.lower()
        for item in placed.values():
            if kw_lower in item.category.lower() or kw_lower in item.name.lower():
                return item
        return None

    def _colocate_corner_cabinets_with_fridge(
        self,
        zone_plan: ZonePlannerOutput,
        preprocessing: PreprocessingOutput,
    ) -> ZonePlannerOutput:
        """Move any zone containing a corner cabinet to the same wall as the fridge.

        Corner cabinets on a different wall than the fridge both try to claim the
        L-corner from their respective walls, causing 3D overlap that per-wall
        position checks cannot detect.  Colocating on one wall lets the sequential
        sort (priority -2 before -1) handle corner allocation cleanly.
        """
        cooling_wall = zone_plan.zone_assignments.get("cooling")
        if not cooling_wall:
            return zone_plan

        for zone_name, skus in preprocessing.zone_groups.items():
            if not any(self._is_corner_cabinet(sku) for sku in skus):
                continue
            current_wall = zone_plan.zone_assignments.get(zone_name)
            if current_wall and current_wall != cooling_wall:
                zone_plan.zone_assignments[zone_name] = cooling_wall
                logger.info(
                    "COLOCATE: zone '%s' (corner cabinet) reassigned %s -> %s",
                    zone_name,
                    current_wall,
                    cooling_wall,
                )

        return zone_plan

    def _normalize_zone_plan(
        self, zone_plan: ZonePlannerOutput, spatial: SpatialEngineOutput
    ) -> ZonePlannerOutput:
        """Canonicalize wall names and zone names so Agent 3 output matches spatial keys."""

        def canonical_wall(raw: str) -> str:
            w = self._find_wall_fuzzy(raw, spatial)
            return w.name if w else raw

        zone_plan.zone_assignments = {
            z.lower().strip(): canonical_wall(w) for z, w in zone_plan.zone_assignments.items()
        }
        zone_plan.wall_strategies = {
            canonical_wall(w): s for w, s in zone_plan.wall_strategies.items()
        }
        return zone_plan

    def _find_wall_fuzzy(self, name: str, spatial: SpatialEngineOutput) -> Wall | None:
        """Find a Wall by exact name, anchor, or partial match (case-insensitive)."""
        n = name.lower().strip().replace(" ", "_").replace("-", "_")
        for wall in spatial.walls:
            if wall.name.lower() == n or wall.anchor.lower() == n:
                return wall
        # Partial: "north" → "north_wall", or "north_wall" → anchor "north"
        for wall in spatial.walls:
            if n in wall.name.lower() or wall.anchor.lower() in n:
                return wall
        return None

    def _get_wall(self, name: str, spatial: SpatialEngineOutput) -> Wall | None:
        """Return Wall by name (exact after normalization) or fuzzy fallback."""
        for wall in spatial.walls:
            if wall.name == name:
                return wall
        return self._find_wall_fuzzy(name, spatial)

    def _adjacent_wall(self, wall_name: str, spatial: SpatialEngineOutput) -> Wall | None:
        """Return the next wall in flow_order after wall_name, or None."""
        flow = spatial.flow_order
        if wall_name not in flow:
            return None
        idx = flow.index(wall_name)
        if idx + 1 < len(flow):
            return self._get_wall(flow[idx + 1], spatial)
        return None

    def _compute_landing_areas(
        self,
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
    ) -> dict[str, float]:
        """Allocate landing area widths per zone, proportionally when space is tight."""
        total_available = sum(
            seg.length_mm for segs in spatial.free_segments.values() for seg in segs
        )
        total_needed = sum(preprocessing.zone_min_widths.values())

        if total_needed <= total_available:
            return dict(preprocessing.zone_min_widths)

        # Weighted proportional allocation
        total_weight = sum(ZONE_WEIGHTS.values())
        return {
            zone: (ZONE_WEIGHTS.get(zone, 0.4) / total_weight) * total_available
            for zone in preprocessing.zone_min_widths
        }

    # ------------------------------------------------------------------ #
    # Factory                                                              #
    # ------------------------------------------------------------------ #

    def _make_item(
        self,
        sku: SKU,
        zone_type: str,
        x: float,
        y: float,
        z: float,
        wall_name: str,
    ) -> PlacedItem:
        """Construct a PlacedItem from a SKU and resolved coordinates."""
        return PlacedItem(
            sku_id=sku.sku_id,
            name=sku.name,
            category=sku.category,
            position_mm={"x": x, "y": y, "z": z},
            dimensions_mm={
                "width": sku.width_mm,
                "depth": sku.depth_mm,
                "height": sku.height_mm,
            },
            rotation_z_deg=0.0,  # overridden to correct angle during serialization
            anchor_wall=wall_name,
            zone_type=zone_type,
        )
