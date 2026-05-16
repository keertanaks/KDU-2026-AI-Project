"""Unit tests for pipeline/zone_planner.py — LayoutStrategist mocked."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from dtos.contracts import (
    IntentDTO,
    PreprocessingOutput,
    SpatialEngineOutput,
    ZonePlannerOutput,
)

# ============================================================================
# Helpers
# ============================================================================


def _make_intent() -> IntentDTO:
    return IntentDTO(
        color_keyword=None,
        color_hex=None,
        layout_family=None,
        style=None,
        cabinet_preference=None,
        special_requests=[],
        ignored=[],
        budget_tier=None,
        must_have=[],
        avoid=[],
    )


def _make_preprocessing() -> PreprocessingOutput:
    return PreprocessingOutput(
        intent=_make_intent(),
        skus={},
        zone_groups={},
        zone_min_widths={},
        nkba_constraints={},
    )


def _make_spatial() -> SpatialEngineOutput:
    return SpatialEngineOutput(
        walls=[],
        free_segments={},
        flow_order=[],
        exclusions=[],
        layout_capacity="medium",
    )


def _make_zone(vid: str = "v1", family: str = "L") -> ZonePlannerOutput:
    return ZonePlannerOutput(
        variant_id=vid,
        family=family,
        wall_strategies={},
        zone_assignments={},
    )


# ============================================================================
# Test 1 — run returns list of ZonePlannerOutput
# ============================================================================


def test_run_returns_variants() -> None:
    """ZonePlanner.run() returns the list of ZonePlannerOutput from LayoutStrategist."""
    mock_client = MagicMock()
    expected = [_make_zone("v1"), _make_zone("v2"), _make_zone("v3")]

    with patch(
        "pipeline.zone_planner.LayoutStrategist.run",
        new=AsyncMock(return_value=expected),
    ):
        from pipeline.zone_planner import ZonePlanner

        result = asyncio.run(
            ZonePlanner(mock_client).run(
                _make_preprocessing(),
                _make_spatial(),
                {"preferences": {}},
            )
        )

    assert isinstance(result, list)
    assert len(result) == 3
    assert all(isinstance(v, ZonePlannerOutput) for v in result)


# ============================================================================
# Test 2 — retry_context passed through to LayoutStrategist
# ============================================================================


def test_retry_context_passed_through() -> None:
    """retry_context dict is forwarded unchanged to LayoutStrategist.run."""
    mock_client = MagicMock()
    retry_ctx: dict[str, list[str]] = {"v1": ["WORKFLOW-03"]}

    with patch(
        "pipeline.zone_planner.LayoutStrategist.run",
        new=AsyncMock(return_value=[_make_zone("v1")]),
    ) as mock_run:
        from pipeline.zone_planner import ZonePlanner

        asyncio.run(
            ZonePlanner(mock_client).run(
                _make_preprocessing(),
                _make_spatial(),
                {"preferences": {}},
                retry_context=retry_ctx,
            )
        )

    # retry_context is the 5th positional arg passed to LayoutStrategist.run
    # (intent, preprocessing, spatial, preferences, retry_context)
    _call_args = mock_run.call_args
    last_positional = (
        _call_args.args[-1] if _call_args.args else _call_args.kwargs.get("retry_context")
    )
    assert last_positional == retry_ctx
