"""Unit tests for agents/rationale_writer.py — mocked API, no real calls."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

from dtos.contracts import VariantSummaryDTO

# ============================================================================
# Helpers
# ============================================================================


def _variant(
    vid: str = "v1",
    score: float = 0.85,
    violations: list[dict[str, Any]] | None = None,
) -> VariantSummaryDTO:
    return VariantSummaryDTO(
        id=vid,
        family="L",
        score=score,
        placement_count=5,
        nkba_compliance_pct=0.9,
        spillover_count=0,
        warnings=[],
        violations=violations or [],
        rationale=[],
        layout={},
        environment={},
    )


def _tool_use_response(rationale_list: list[dict[str, Any]]) -> MagicMock:
    """Build a mock messages.create response with one tool_use block."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = "write_rationale"
    block.input = {"rationale": rationale_list}
    response = MagicMock()
    response.content = [block]
    return response


# ============================================================================
# Test 1 — successful write returns rationale list
# ============================================================================


def test_write_returns_rationale_list() -> None:
    """Successful API call returns a list of rationale dicts with rule_id and text."""
    expected = [
        {"rule_id": "LAYOUT-01", "text": "Sink placed near window as required."},
        {"rule_id": "WORKFLOW-03", "text": "Work triangle perimeter within range."},
    ]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _tool_use_response(expected)

    from agents.rationale_writer import RationaleWriter

    writer = RationaleWriter(mock_client)
    result = asyncio.run(writer.write(_variant()))

    assert isinstance(result, list)
    assert len(result) == 2
    for item in result:
        assert "rule_id" in item
        assert "text" in item


# ============================================================================
# Test 2 — fallback on API exception
# ============================================================================


def test_write_fallback_on_api_error() -> None:
    """Exception during API call returns non-empty fallback list with rule_id key."""
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("timeout")

    from agents.rationale_writer import RationaleWriter

    writer = RationaleWriter(mock_client)
    result = asyncio.run(writer.write(_variant()))

    assert isinstance(result, list)
    assert len(result) > 0
    assert "rule_id" in result[0]


# ============================================================================
# Test 3 — fallback when no tool_use block in response
# ============================================================================


def test_write_fallback_on_no_tool_block() -> None:
    """Response with empty content triggers fallback list with rule_id key."""
    mock_client = MagicMock()
    empty_response = MagicMock()
    empty_response.content = []
    mock_client.messages.create.return_value = empty_response

    from agents.rationale_writer import RationaleWriter

    writer = RationaleWriter(mock_client)
    result = asyncio.run(writer.write(_variant()))

    assert isinstance(result, list)
    assert len(result) > 0
    assert "rule_id" in result[0]
