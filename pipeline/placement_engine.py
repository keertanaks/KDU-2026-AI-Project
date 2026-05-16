"""Layer 4: Placement Engine — resolve semantic terms to exact mm coordinates.

Pure Python math module. No LLM calls, no Anthropic imports.
Consumes ZonePlannerOutput (semantic) and emits PlacementEngineOutput (mm).
"""

from __future__ import annotations

import re

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
# Constants
# ============================================================================

Z_FLOOR_MM: float = 0.0
Z_WALL_CAB_MM: float = 900.0
GAP_LEAVE_BEFORE_MM: float = 600.0
GAP_FRIDGE_STOVE_MM: float = 600.0
WORK_TRIANGLE_MIN_MM: float = 3962.0
WORK_TRIANGLE_MAX_MM: float = 6600.0
MIN_SEGMENT_MM: float = 100.0
SINK_WINDOW_TOLERANCE_MM: float = 300.0

ZONE_WEIGHTS: dict[str, float] = {
    "cooling": 1.0,
    "cleaning": 1.0,
    "cooking": 0.9,
    "preparation": 0.7,
    "storage": 0.4,
}

COLLISION_WHITELIST: set[frozenset[str]] = {
    frozenset({"hood", "stove"}),
    frozenset({"tap", "sink"}),
    frozenset({"wall_cabinet", "base_cabinet"}),
    frozenset({"dishwasher", "base_cabinet"}),
}

_ANCHORED_KW: tuple[str, ...] = ("sink", "refrigerator", "fridge", "stove", "range")
_DEPENDENT_KW: tuple[str, ...] = ("hood", "dishwasher", "tap")
_DROPPABLE_KW: tuple[str, ...] = ("wall_cabinet", "island")


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

        Processes each wall in priority order (anchored → dependent → fill).
        Handles spillover and checks work triangle when requested.
        """
        placed: dict[str, PlacedItem] = {}
        spillover: list[str] = []

        all_walls: set[str] = set(zone_plan.zone_assignments.values())
        all_walls.update(zone_plan.wall_strategies.keys())

        for wall_name in sorted(all_walls):
            wall = self._get_wall(wall_name, spatial)
            if wall is None:
                logger.warning("Wall '%s' not in spatial output — skipping", wall_name)
                continue
            items = self._items_for_wall(wall_name, zone_plan, preprocessing)
            if not items:
                continue
            strategies = zone_plan.wall_strategies.get(wall_name, [])
            self._place_wall(items, strategies, wall, spatial, placed, spillover)

        if zone_plan.work_triangle_priority:
            self._check_work_triangle(placed, spillover)

        return PlacementEngineOutput(
            variant_id=zone_plan.variant_id,
            positioned_items=placed,
            spillover_log=spillover,
            collision_flags=self._detect_collisions(placed),
        )

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
    ) -> None:
        """Place all items for one wall using available strategies."""
        # Sort: anchored first, then dependent, then fill
        sorted_items = sorted(items, key=lambda t: self._priority_rank(t[0]))

        for sku, zone_type in sorted_items:
            item_key = sku.sku_id

            # Dependents may carry inherent terms (hood above stove, DW next to sink)
            if self._is_dependent(sku):
                inherent = self._inherent_term(sku)
                result = self._resolve_term(inherent, wall, sku, placed, spatial)
                if result is not None:
                    x, y, z = result
                    placed[item_key] = self._make_item(sku, zone_type, x, y, z, wall.name)
                    continue

            # Try each strategy term in order
            resolved = False
            for strat in strategies:
                term = self._extract_pos_term(strat)
                result = self._resolve_term(term, wall, sku, placed, spatial)
                if result is not None:
                    x, y, z = result
                    placed[item_key] = self._make_item(sku, zone_type, x, y, z, wall.name)
                    resolved = True
                    break

            if not resolved:
                # Fall back to first free segment
                result = self._first_free(wall, sku, placed, spatial)
                if result is not None:
                    x, y, z = result
                    placed[item_key] = self._make_item(sku, zone_type, x, y, z, wall.name)
                else:
                    self._no_space(sku, zone_type, wall, spatial, placed, spillover)

    def _no_space(
        self,
        sku: SKU,
        zone_type: str,
        wall: Wall,
        spatial: SpatialEngineOutput,
        placed: dict[str, PlacedItem],
        spillover: list[str],
    ) -> None:
        """Handle an item that has no free space on its assigned wall."""
        cat = sku.category.lower()
        name = sku.name.lower()

        # Droppable items: wall_cabinet → island → skip
        for kw in _DROPPABLE_KW:
            if kw in cat or kw in name:
                logger.warning(
                    "SPILLOVER: '%s' (%s) dropped — no space on wall '%s'",
                    sku.sku_id,
                    sku.name,
                    wall.name,
                )
                spillover.append(
                    f"SPILLOVER: {sku.sku_id} dropped from {wall.name} (no space)"
                )
                return

        # Non-droppable: force to nearest corner and log constraint violation
        x = 0.0
        y = wall.thickness_mm
        z = Z_FLOOR_MM
        logger.warning(
            "CONSTRAINT_VIOLATION: '%s' forced to corner on wall '%s' — no free segment",
            sku.sku_id,
            wall.name,
        )
        spillover.append(
            f"CONSTRAINT_VIOLATION: {sku.sku_id} forced to corner on {wall.name} (LAYOUT-06)"
        )
        placed[sku.sku_id] = self._make_item(sku, zone_type, x, y, z, wall.name)

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
        z = Z_WALL_CAB_MM if sku.category.lower() == "wall_cabinet" else Z_FLOOR_MM
        rotation = 180.0 if "south" in wall.name.lower() else 0.0
        _ = rotation  # rotation used in _make_item, not here

        if t == "at north-west corner":
            return (0.0, y, z)
        if t == "at north-east corner":
            return (max(0.0, wall.length_mm - sku.width_mm), y, z)
        if t == "at south-west corner":
            return (0.0, 0.0, z)
        if t == "at south-east corner":
            return (max(0.0, wall.length_mm - sku.width_mm), 0.0, z)
        if t == "centre of " + wall.name.lower() or re.match(r"centre of \w+", t):
            cx = (wall.length_mm - sku.width_mm) / 2.0
            cx = self._clamp_to_seg(cx, sku.width_mm, wall.name, spatial)
            return (cx, y, z)
        if t == "left end of " + wall.name.lower() or re.match(r"left end of \w+", t):
            segs = spatial.free_segments.get(wall.name, [])
            if not segs:
                return None
            return (segs[0].start_mm, y, z)
        if t == "right end of " + wall.name.lower() or re.match(r"right end of \w+", t):
            segs = spatial.free_segments.get(wall.name, [])
            if not segs:
                return None
            return (max(0.0, segs[-1].end_mm - sku.width_mm), y, z)
        if re.match(r"near \w+ window", t):
            return self._near_window(wall, sku, spatial, y, z)
        if t.startswith("next to "):
            ref_name = t[len("next to ") :]
            return self._resolve_next_to(ref_name, placed, z)
        if t.startswith("above "):
            ref_name = t[len("above ") :]
            return self._resolve_above(ref_name, sku, placed)
        if t.startswith("leave gap before "):
            ref_name = t[len("leave gap before ") :]
            return self._resolve_gap_before(ref_name, sku, placed, y, z)

        return None

    def _near_window(
        self,
        wall: Wall,
        sku: SKU,
        spatial: SpatialEngineOutput,
        y: float,
        z: float,
    ) -> tuple[float, float, float] | None:
        """Place item near a window on the wall; clamp to free segment."""
        windows = [o for o in spatial.exclusions if o.wall == wall.name and o.kind == "window"]
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
        placed: dict[str, PlacedItem],
        z: float,
    ) -> tuple[float, float, float] | None:
        """Place immediately to the right of named item."""
        ref = self._find_by_name(ref_name, placed)
        if ref is None:
            ref = self._find_by_cat(ref_name, placed)
        if ref is None:
            return None
        x = ref.position_mm["x"] + ref.dimensions_mm["width"]
        y = ref.position_mm["y"]
        return (x, y, z)

    def _resolve_above(
        self,
        ref_name: str,
        sku: SKU,
        placed: dict[str, PlacedItem],
    ) -> tuple[float, float, float] | None:
        """Place centred above named item."""
        ref = self._find_by_name(ref_name, placed)
        if ref is None:
            ref = self._find_by_cat(ref_name, placed)
        if ref is None:
            return None
        ref_cx = ref.position_mm["x"] + ref.dimensions_mm["width"] / 2.0
        x = ref_cx - sku.width_mm / 2.0
        y = ref.position_mm["y"]
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
        segs = spatial.free_segments.get(wall.name, [])
        occupied = self._occupied_ranges(wall.name, placed)
        y = wall.thickness_mm
        z = Z_WALL_CAB_MM if sku.category.lower() == "wall_cabinet" else Z_FLOOR_MM

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
        self, wall_name: str, placed: dict[str, PlacedItem]
    ) -> list[tuple[float, float]]:
        """Return sorted list of (start, end) x-ranges already placed on wall."""
        ranges: list[tuple[float, float]] = []
        for item in placed.values():
            if item.anchor_wall == wall_name:
                x = item.position_mm["x"]
                w = item.dimensions_mm["width"]
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
        """Return list of collision flag strings for non-whitelisted overlaps."""
        flags: list[str] = []
        items = list(placed.items())
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                id_a, a = items[i]
                id_b, b = items[j]
                cat_a = a.category.lower()
                cat_b = b.category.lower()
                pair: frozenset[str] = frozenset({cat_a, cat_b})
                if pair in COLLISION_WHITELIST:
                    continue
                if self._overlap3d(a, b):
                    flags.append(f"COLLISION: {id_a} ↔ {id_b}")
        return flags

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
    # Work triangle                                                        #
    # ------------------------------------------------------------------ #

    def _check_work_triangle(
        self,
        placed: dict[str, PlacedItem],
        spillover: list[str],
    ) -> None:
        """Log WORKFLOW-03 violation when work triangle perimeter is out of range."""
        sink = self._find_by_cat("sink", placed)
        fridge = self._find_by_cat("fridge", placed) or self._find_by_cat("refrigerator", placed)
        stove = self._find_by_cat("stove", placed) or self._find_by_cat("range", placed)

        if not (sink and fridge and stove):
            return

        perimeter = (
            self._dist2d(sink, fridge) + self._dist2d(fridge, stove) + self._dist2d(stove, sink)
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
        """Euclidean distance between item centres in the x-y plane."""
        ax = a.position_mm["x"] + a.dimensions_mm["width"] / 2.0
        ay = a.position_mm["y"] + a.dimensions_mm["depth"] / 2.0
        bx = b.position_mm["x"] + b.dimensions_mm["width"] / 2.0
        by = b.position_mm["y"] + b.dimensions_mm["depth"] / 2.0
        return float(((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5)

    # ------------------------------------------------------------------ #
    # Item assembly helpers                                                #
    # ------------------------------------------------------------------ #

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
            skus_in_zone = preprocessing.zone_groups.get(zone_name, [])
            for sku in skus_in_zone:
                result.append((sku, zone_name))
        result.sort(key=lambda t: self._priority_rank(t[0]))
        return result

    def _priority_rank(self, sku: SKU) -> int:
        """Return placement priority: 0=anchored, 1=dependent, 2=fill."""
        combined = (sku.category + " " + sku.name).lower()
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

    def _get_wall(self, name: str, spatial: SpatialEngineOutput) -> Wall | None:
        """Return Wall by name or None."""
        for wall in spatial.walls:
            if wall.name == name:
                return wall
        return None

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
        self, preprocessing: PreprocessingOutput, spatial: SpatialEngineOutput
    ) -> dict[str, float]:
        """Return minimum landing area widths per zone from zone_min_widths."""
        return dict(preprocessing.zone_min_widths)

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
        rotation = 180.0 if "south" in wall_name.lower() else 0.0
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
            rotation_z_deg=rotation,
            anchor_wall=wall_name,
            zone_type=zone_type,
        )
