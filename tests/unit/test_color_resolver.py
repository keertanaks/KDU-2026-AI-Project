"""Unit tests for mcp_server/color_resolver.py — color fallback behaviour.

Tests verify that:
- Unknown color keywords never crash
- Nearest-match substitutions are flagged with exact_match=False
- Resolved hex always maps to a real catalog SKU
- Case-insensitive matching works
- Exact keywords get exact_match=True (no spurious warnings)
"""

from __future__ import annotations

import pytest

from mcp_server.catalog_loader import get_catalog
from mcp_server.color_resolver import (
    ColorResolution,
    match_catalog_color,
    resolve_color_keyword,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_CATALOG: dict | None = None


def _get_catalog() -> dict:
    """Load the real catalog once for the test session."""
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = get_catalog()
    return _CATALOG


# ---------------------------------------------------------------------------
# test_unknown_keyword_returns_nearest_match
# ---------------------------------------------------------------------------


def test_unknown_keyword_returns_nearest_match() -> None:
    """'dark grey' is not an exact keyword — should return a valid non-empty hex."""
    result = resolve_color_keyword("dark grey")
    assert isinstance(result, ColorResolution)
    assert len(result.hex_code) == 6, f"Expected 6-char hex, got: {result.hex_code!r}"
    assert result.hex_code != "", "hex_code must not be empty"


# ---------------------------------------------------------------------------
# test_unknown_keyword_no_crash
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "keyword",
    [
        "dark grey",
        "midnight blue",
        "forest fog",
        "deep mahogany",
        "burnt sienna",
        "electric violet",
        "",  # empty string — edge case
        "   ",  # whitespace only — edge case
        "DARK GREY",  # uppercase variant
    ],
)
def test_unknown_keyword_no_crash(keyword: str) -> None:
    """No color keyword — however unusual — should ever raise an exception."""
    try:
        result = resolve_color_keyword(keyword)
        assert isinstance(result, ColorResolution)
        assert len(result.hex_code) == 6
    except Exception as exc:
        pytest.fail(f"resolve_color_keyword({keyword!r}) raised {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# test_resolved_color_has_real_sku
# ---------------------------------------------------------------------------


def test_resolved_color_has_real_sku() -> None:
    """The hex returned for 'dark grey' must match a real catalog SKU."""
    catalog = _get_catalog()
    result = resolve_color_keyword("dark grey")

    match = match_catalog_color(result.hex_code, catalog)
    assert match is not None, (
        f"Hex #{result.hex_code} from 'dark grey' matched no catalog SKU. "
        "Resolved color must always map to a real SKU (skill: color-resolution rule 1)."
    )
    sku_id, distance = match
    assert sku_id in catalog, f"Matched SKU '{sku_id}' not found in catalog"
    assert distance >= 0.0, "Delta-E distance must be non-negative"


# ---------------------------------------------------------------------------
# test_nearest_match_flag_is_set
# ---------------------------------------------------------------------------


def test_nearest_match_flag_is_set() -> None:
    """'dark grey' is not in _COLOR_TABLE — exact_match must be False."""
    result = resolve_color_keyword("dark grey")
    assert result.exact_match is False, (
        "expected exact_match=False for 'dark grey' (not an exact color table entry)"
    )


# ---------------------------------------------------------------------------
# test_exact_keyword_no_warning
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "keyword",
    ["white", "grey", "navy blue", "oak", "charcoal", "sage green"],
)
def test_exact_keyword_no_warning(keyword: str) -> None:
    """Keywords that ARE in _COLOR_TABLE must return exact_match=True."""
    result = resolve_color_keyword(keyword)
    assert result.exact_match is True, (
        f"Expected exact_match=True for known keyword '{keyword}', got False. "
        "Exact keywords must not trigger the nearest-match warning."
    )


# ---------------------------------------------------------------------------
# test_case_insensitive_matching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "variant",
    ["white", "White", "WHITE", " white ", "wHiTe"],
)
def test_case_insensitive_matching(variant: str) -> None:
    """All case variants of a known keyword must resolve to the same hex."""
    canonical = resolve_color_keyword("white")
    result = resolve_color_keyword(variant)
    assert result.hex_code == canonical.hex_code, (
        f"Case variant {variant!r} resolved to #{result.hex_code} "
        f"but expected #{canonical.hex_code}"
    )


# ---------------------------------------------------------------------------
# test_dark_grey_variants_are_nearest_match
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "keyword",
    ["dark grey", "Dark Grey", "DARK GREY", "dark gray", "Dark Gray"],
)
def test_dark_grey_variants_are_nearest_match(keyword: str) -> None:
    """All spellings / cases of 'dark grey' must flag exact_match=False."""
    result = resolve_color_keyword(keyword)
    assert result.exact_match is False, (
        f"'{keyword}' should be a nearest-match substitution, not exact"
    )
    # Must still return a valid 6-char hex (never crashes, never empty)
    assert len(result.hex_code) == 6
