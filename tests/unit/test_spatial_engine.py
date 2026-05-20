"""Unit tests for SpatialEngine — pure math, no API calls."""

from __future__ import annotations

import pytest
from tests.fixtures.sample_inputs import INPUT1, INPUT2, INPUT3


class TestSpatialEngineInput1:
    """3600×3200mm, no openings, north+east walls have cabinets."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from pipeline.spatial_engine import SpatialEngine

        self.engine = SpatialEngine()
        self.result = self.engine.parse(INPUT1)

    def test_layout_capacity_is_L(self):
        assert self.result.layout_capacity == "L"

    def test_two_cabinet_walls(self):
        assert len(self.result.walls) == 2

    def test_north_wall_full_segment(self):
        segs = self.result.free_segments["north_wall"]
        assert len(segs) == 1
        assert segs[0].start_mm == 0
        assert segs[0].end_mm == pytest.approx(3600, abs=1)

    def test_east_wall_full_segment(self):
        segs = self.result.free_segments["east_wall"]
        assert len(segs) == 1
        assert segs[0].end_mm == pytest.approx(3200, abs=1)

    def test_no_exclusions(self):
        assert len(self.result.exclusions) == 0

    def test_flow_order_longest_first(self):
        # north_wall (3600) > east_wall (3200)
        assert self.result.flow_order[0] == "north_wall"
        assert self.result.flow_order[1] == "east_wall"


class TestSpatialEngineInput3:
    """4200×3000mm, door on south + 2 windows, north+east cabinet walls."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from pipeline.spatial_engine import SpatialEngine

        self.engine = SpatialEngine()
        self.result = self.engine.parse(INPUT3)

    def test_layout_capacity_is_L(self):
        assert self.result.layout_capacity == "L"

    def test_north_wall_split_by_window(self):
        # Windows block ONLY wall-level items. `wall_free_segments` is the
        # restrictive map for uppers; `free_segments` (floor) is unaffected.
        segs = self.result.wall_free_segments["north_wall"]
        assert len(segs) == 2
        assert segs[0].end_mm == pytest.approx(1500, abs=1)
        assert segs[1].start_mm == pytest.approx(2700, abs=1)
        assert segs[1].end_mm == pytest.approx(4200, abs=1)
        # Floor-level segment remains unbroken under the window
        floor = self.result.free_segments["north_wall"]
        assert len(floor) == 1
        assert floor[0].end_mm == pytest.approx(4200, abs=1)

    def test_east_wall_split_by_window(self):
        # Same split rule — uppers blocked, floor unaffected.
        segs = self.result.wall_free_segments["east_wall"]
        assert len(segs) == 2
        assert segs[0].end_mm == pytest.approx(600, abs=1)
        assert segs[1].start_mm == pytest.approx(1400, abs=1)
        floor = self.result.free_segments["east_wall"]
        assert len(floor) == 1

    def test_three_exclusions(self):
        # door on south + 2 windows
        assert len(self.result.exclusions) == 3

    def test_door_exclusion_includes_swing_arc(self):
        door = next(e for e in self.result.exclusions if e.kind == "door")
        # offset=600, width=900, swing arc=900 → blocked_end = 600+900+900=2400
        assert door.blocked_start_mm == pytest.approx(600, abs=1)
        assert door.blocked_end_mm == pytest.approx(2400, abs=1)

    def test_south_wall_not_in_segments(self):
        # south_wall has has_cabinets=false
        assert "south_wall" not in self.result.free_segments


class TestSpatialEngineInput2:
    """4200×4200mm — U-capable room (3 cabinet walls)."""

    def test_large_room_layout_capacity(self):
        from pipeline.spatial_engine import SpatialEngine

        result = SpatialEngine().parse(INPUT2)
        assert result.layout_capacity == "U"
        segs = result.free_segments["north_wall"]
        assert segs[0].end_mm == pytest.approx(4200, abs=1)
