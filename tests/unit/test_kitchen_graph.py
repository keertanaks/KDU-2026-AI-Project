"""Unit tests for graph/kitchen_graph.py — tests helper methods directly, no graph invocation."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from dtos.contracts import (
    IntentDTO,
    PlacementEngineOutput,
    PreprocessingOutput,
    SpatialEngineOutput,
    VariantSummaryDTO,
)

# ============================================================================
# Helpers
# ============================================================================


def _make_preprocessing() -> PreprocessingOutput:
    intent = IntentDTO(
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
    return PreprocessingOutput(
        intent=intent,
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


def _make_placed(vid: str = "v1") -> PlacementEngineOutput:
    return PlacementEngineOutput(
        variant_id=vid,
        positioned_items={},
        spillover_log=[],
        collision_flags=[],
    )


def _make_validated(vid: str = "v1", score: float = 0.4) -> VariantSummaryDTO:
    return VariantSummaryDTO(
        id=vid,
        family="L",
        score=score,
        placement_count=0,
        nkba_compliance_pct=0.5,
        spillover_count=0,
        warnings=[],
        violations=[{"rule_id": "WORKFLOW-03", "detail": "triangle too small"}],
        rationale=[],
        layout={},
        environment={},
    )


def _build_state(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "input_json": {},
        "spatial_output": _make_spatial(),
        "preprocessing_output": _make_preprocessing(),
        "variants": [],
        "placed_variants": [],
        "validated_variants": [],
        "retry_context": {},
        "final_output": None,
    }
    base.update(overrides)
    return base


def _make_graph() -> Any:
    """Construct KitchenGraph with _build patched to a no-op MagicMock."""
    mock_client = MagicMock()
    with patch("graph.kitchen_graph.KitchenGraph._build", return_value=MagicMock()):
        from graph.kitchen_graph import KitchenGraph

        return KitchenGraph(mock_client)


# ============================================================================
# Test 1 — _should_retry returns "retry" when context non-empty
# ============================================================================


def test_should_retry_when_context_non_empty() -> None:
    """_should_retry returns 'retry' when retry_context is non-empty."""
    graph = _make_graph()
    state = _build_state(retry_context={"v1": ["WORKFLOW-03"]})
    assert graph._should_retry(state) == "retry"  # type: ignore[arg-type]


# ============================================================================
# Test 2 — _should_retry returns "done" when context empty
# ============================================================================


def test_should_not_retry_when_context_empty() -> None:
    """_should_retry returns 'done' when retry_context is empty."""
    graph = _make_graph()
    state = _build_state(retry_context={})
    assert graph._should_retry(state) == "done"  # type: ignore[arg-type]


# ============================================================================
# Test 3 — validation node clears retry on second pass (no infinite loop)
# ============================================================================


def test_validation_node_clears_retry_on_second_pass() -> None:
    """On retry pass (retry_context already set), _node_validation always clears retry_context."""
    graph = _make_graph()

    # Simulate state after first retry was triggered — retry_context is already populated
    state = _build_state(
        retry_context={"v1": ["WORKFLOW-03"]},
        placed_variants=[_make_placed("v1")],
    )

    # Validator returns a still-bad variant (score=0.4, WORKFLOW-03 violated)
    with patch.object(
        graph._validator,
        "validate",
        return_value=_make_validated("v1", score=0.4),
    ):
        result = graph._node_validation(state)  # type: ignore[arg-type]

    # retry_context must be empty → routes to "done", preventing infinite loop
    assert result["retry_context"] == {}
    assert len(result["validated_variants"]) == 1
