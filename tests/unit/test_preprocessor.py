"""Unit tests for pipeline/preprocessor.py — all API calls mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dtos.contracts import (
    IntentDTO,
    PreprocessingOutput,
    SpatialEngineOutput,
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


# ============================================================================
# Test 1 — run returns PreprocessingOutput
# ============================================================================


def test_run_returns_preprocessing_output() -> None:
    """Preprocessor.run() returns a PreprocessingOutput instance."""
    mock_client = MagicMock()
    spatial = _make_spatial()
    preprocessing = _make_preprocessing()

    with (
        patch("pipeline.preprocessor.PromptParser") as mock_parser,
        patch("pipeline.preprocessor.get_catalog", return_value={}) as _mock_catalog,
        patch("pipeline.preprocessor.CatalogSelector") as mock_selector,
    ):
        mock_parser.return_value.parse.return_value = _make_intent()
        mock_selector.return_value.select.return_value = preprocessing

        from pipeline.preprocessor import Preprocessor

        result = Preprocessor(mock_client).run({"preferences": {}}, spatial)

    assert isinstance(result, PreprocessingOutput)


# ============================================================================
# Test 2 — catalog_id passed to get_catalog
# ============================================================================


def test_catalog_id_passed_to_get_catalog() -> None:
    """Custom catalogId in preferences is forwarded to get_catalog."""
    mock_client = MagicMock()
    spatial = _make_spatial()

    with (
        patch("pipeline.preprocessor.PromptParser") as mock_parser,
        patch("pipeline.preprocessor.get_catalog", return_value={}) as mock_catalog,
        patch("pipeline.preprocessor.CatalogSelector") as mock_selector,
    ):
        mock_parser.return_value.parse.return_value = _make_intent()
        mock_selector.return_value.select.return_value = _make_preprocessing()

        from pipeline.preprocessor import Preprocessor

        Preprocessor(mock_client).run(
            {"preferences": {"catalogId": "custom_catalog"}},
            spatial,
        )

    mock_catalog.assert_called_once_with("custom_catalog")


# ============================================================================
# Test 3 — default catalog_id when missing
# ============================================================================


def test_default_catalog_id_when_missing() -> None:
    """Missing catalogId in preferences defaults to 'catalog'."""
    mock_client = MagicMock()
    spatial = _make_spatial()

    with (
        patch("pipeline.preprocessor.PromptParser") as mock_parser,
        patch("pipeline.preprocessor.get_catalog", return_value={}) as mock_catalog,
        patch("pipeline.preprocessor.CatalogSelector") as mock_selector,
    ):
        mock_parser.return_value.parse.return_value = _make_intent()
        mock_selector.return_value.select.return_value = _make_preprocessing()

        from pipeline.preprocessor import Preprocessor

        Preprocessor(mock_client).run({"preferences": {}}, spatial)

    mock_catalog.assert_called_once_with("catalog")
