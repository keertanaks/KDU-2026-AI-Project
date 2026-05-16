"""Spatial Engine — parse room geometry and compute free segments for cabinet placement.

Pure deterministic geometry. No API calls. All measurements in mm.
"""

from __future__ import annotations

import logging
from typing import Any

from dtos.contracts import Opening, Segment, SpatialEngineOutput, Wall

logger = logging.getLogger(__name__)

# Minimum segment length to include (anything smaller is too small for cabinets)
MIN_SEGMENT_LENGTH_MM = 100

# Adjacent wall anchor pairs (define L-shape)
ADJACENT_WALL_PAIRS = {("north", "east"), ("east", "south"), ("south", "west"), ("west", "north")}


def _merge_ranges(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Merge overlapping ranges and return sorted non-overlapping list."""
    if not ranges:
        return []

    sorted_ranges = sorted(ranges)
    merged = [sorted_ranges[0]]

    for start, end in sorted_ranges[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            # Overlapping — merge
            merged[-1] = (last_start, max(last_end, end))
        else:
            # Non-overlapping — add as new range
            merged.append((start, end))

    return merged


def _subtract_ranges(
    total_start: float, total_end: float, blocked_ranges: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Subtract blocked ranges from [total_start, total_end] and return free ranges."""
    if not blocked_ranges:
        return [(total_start, total_end)]

    merged = _merge_ranges(blocked_ranges)
    free = []
    current = total_start

    for block_start, block_end in merged:
        # Clamp block to total range
        block_start = max(block_start, total_start)
        block_end = min(block_end, total_end)

        if block_start > current:
            # Gap before this block is free
            free.append((current, block_start))

        current = max(current, block_end)

    if current < total_end:
        # Remaining space after last block
        free.append((current, total_end))

    return free


class SpatialEngine:
    """Parse room geometry and compute free segments for cabinet placement."""

    def parse(self, input_json: dict[str, Any]) -> SpatialEngineOutput:
        """Parse input JSON into SpatialEngineOutput.

        Args:
            input_json: Raw input with environment.wall and environment.openings

        Returns:
            SpatialEngineOutput with walls, free_segments, flow_order, exclusions, layout_capacity
        """
        walls = self._parse_walls(input_json["environment"]["wall"])
        exclusions = self._parse_openings(input_json["environment"].get("openings", []))
        free_segments = self._compute_free_segments(walls, exclusions)
        flow_order = self._compute_flow_order(walls)
        layout_capacity = self._determine_layout_capacity(walls)

        logger.info(
            f"Parsed room: {len(walls)} cabinet walls, {len(exclusions)} openings, "
            f"capacity={layout_capacity}"
        )

        return SpatialEngineOutput(
            walls=walls,
            free_segments=free_segments,
            flow_order=flow_order,
            exclusions=exclusions,
            layout_capacity=layout_capacity,
        )

    def _parse_walls(self, wall_list: list[dict[str, Any]]) -> list[Wall]:
        """Extract walls from input, return only those with has_cabinets=true."""
        walls = []

        for wall_dict in wall_list:
            if not wall_dict.get("has_cabinets", False):
                continue

            wall = Wall(
                name=wall_dict["name"],
                anchor=wall_dict["anchor"],
                length_mm=float(wall_dict["dimensions"]["length_mm"]),
                height_mm=float(wall_dict["dimensions"]["height"]),
                thickness_mm=float(wall_dict.get("thickness_mm", 100)),
                has_cabinets=True,
                points=wall_dict.get("points", []),
            )
            walls.append(wall)

        logger.debug(f"Parsed {len(walls)} cabinet walls")
        return walls

    def _parse_openings(self, opening_list: list[dict[str, Any]]) -> list[Opening]:
        """Extract doors and windows, compute blocked ranges."""
        exclusions = []

        for opening_dict in opening_list:
            kind = opening_dict["kind"]  # "door" or "window"
            offset = float(opening_dict["offset_mm"])
            width = float(opening_dict["width_mm"])
            height = float(opening_dict.get("height_mm", 2000))
            wall = opening_dict["wall"]
            sill = float(opening_dict.get("sill_mm", 0))

            # Compute blocked range
            if kind == "door":
                # Door: offset + width (footprint) + width (swing arc)
                blocked_start = offset
                blocked_end = offset + 2 * width
            else:  # window
                # Window: offset + width
                blocked_start = offset
                blocked_end = offset + width

            opening = Opening(
                id=opening_dict.get("id", f"{kind}-{wall}-{offset}"),
                kind=kind,
                wall=wall,
                offset_mm=offset,
                width_mm=width,
                height_mm=height,
                sill_mm=sill,
                blocked_start_mm=blocked_start,
                blocked_end_mm=blocked_end,
            )
            exclusions.append(opening)

        logger.debug(f"Parsed {len(exclusions)} openings")
        return exclusions

    def _compute_free_segments(
        self, walls: list[Wall], exclusions: list[Opening]
    ) -> dict[str, list[Segment]]:
        """Compute free segments for each wall by subtracting blocked ranges."""
        free_segments: dict[str, list[Segment]] = {}

        for wall in walls:
            # Find all openings that block this wall
            wall_openings = [e for e in exclusions if e.wall == wall.anchor]
            blocked_ranges = [(e.blocked_start_mm, e.blocked_end_mm) for e in wall_openings]

            # Subtract blocked from full wall length
            free_ranges = _subtract_ranges(0, wall.length_mm, blocked_ranges)

            # Convert to Segment objects, drop segments < MIN_SEGMENT_LENGTH_MM
            segments = [
                Segment(start_mm=s, end_mm=e)
                for s, e in free_ranges
                if (e - s) >= MIN_SEGMENT_LENGTH_MM
            ]
            free_segments[wall.name] = segments

            logger.debug(
                f"Wall {wall.name}: {len(wall_openings)} openings, {len(segments)} free segments"
            )

        return free_segments

    def _compute_flow_order(self, walls: list[Wall]) -> list[str]:
        """Return wall names sorted by length descending (longest first)."""
        sorted_walls = sorted(walls, key=lambda w: w.length_mm, reverse=True)
        return [w.name for w in sorted_walls]

    def _determine_layout_capacity(self, walls: list[Wall]) -> str:
        """Determine layout capacity based on number and adjacency of cabinet walls.

        Returns:
            "U" if 3+ walls, "L" if 2 adjacent walls, "I" if 1 wall
        """
        cabinet_walls = walls
        n = len(cabinet_walls)

        if n >= 3:
            return "U"
        elif n == 2:
            # Check if walls are adjacent (share a corner)
            anchors = {w.anchor for w in cabinet_walls}
            for a1, a2 in ADJACENT_WALL_PAIRS:
                if (a1 in anchors and a2 in anchors) or (a2 in anchors and a1 in anchors):
                    return "L"
            # Two non-adjacent walls (opposite) → treat as "L" for now
            return "L"
        else:
            return "I"
