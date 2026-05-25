"""Resolve natural language color descriptions to catalog hex codes.

Uses a static lookup table for keyword → hex resolution (zero LLM cost),
then matches against catalog colors using CIE76 delta-E distance in Lab color space.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from utils.logger import get_logger

logger = get_logger(__name__)

# Delta-E tolerance for color matching (CIE Lab distance)
DELTA_E_TOLERANCE = 15.0

# Static color keyword → hex lookup table.
# Kept in sync with Agent 1's system prompt color reference table.
# Keys are lowercase, spaces normalised to hyphens.
# Kept in sync with COLOR_KEYWORD_HEX in agents/prompt_parser.py and the catalog
_COLOR_TABLE: dict[str, str] = {
    "white": "FFFFFF",
    "matte white": "EDEDE9",
    "matte-white": "EDEDE9",
    "shaker white": "E8E2D5",
    "shaker-white": "E8E2D5",
    "off white": "F5F0E8",
    "off-white": "F5F0E8",
    "warm white": "FAF8F5",
    "warm-white": "FAF8F5",
    "cream": "F5E6CA",
    "soft grey": "B0B8BE",
    "soft-grey": "B0B8BE",
    "soft gray": "B0B8BE",
    "soft-gray": "B0B8BE",
    "grey": "9CA3AF",
    "gray": "9CA3AF",
    "charcoal": "3D3D3D",
    "graphite": "2A2A2A",
    "matte black": "2E2E2E",
    "matte-black": "2E2E2E",
    "composite black": "2F2F2F",
    "composite-black": "2F2F2F",
    "black": "1A1A1A",
    "oak": "D4A574",
    "maple": "C8A878",
    "birch": "DBC59A",
    "walnut": "6F4E37",
    "espresso": "4A3328",
    "stainless steel": "BFC1C2",
    "stainless-steel": "BFC1C2",
    "stainless": "BFC1C2",
    "brushed steel": "B8BABC",
    "brushed-steel": "B8BABC",
    "chrome": "D6D8DA",
    "navy": "1F3A5F",
    "navy blue": "1F3A5F",
    "navy-blue": "1F3A5F",
    "forest green": "2F5233",
    "forest-green": "2F5233",
    "sage green": "9CAF88",
    "sage-green": "9CAF88",
    "sage": "9CAF88",
    "terracotta": "C76A4A",
}

# Fallback for unknown colors
_FALLBACK_HEX = "808080"


@dataclass
class ColorResolution:
    """Result of resolving a color keyword to a hex code.

    Carries metadata about match quality so callers can decide whether to
    warn the user that a substitution was made.
    """

    hex_code: str
    """6-char uppercase hex WITHOUT '#' (e.g. '9CA3AF')."""

    exact_match: bool
    """True only if the keyword was an exact key in _COLOR_TABLE."""

    matched_keyword: str
    """The _COLOR_TABLE key that was actually used.
    Empty string when no match was found and _FALLBACK_HEX was used.
    """


def resolve_color_keyword(keyword: str) -> ColorResolution:
    """Resolve a color keyword with metadata about match quality.

    Checks in order:
    1. Exact key in ``_COLOR_TABLE`` → ``exact_match=True``
    2. Prefix / substring match    → ``exact_match=False``
    3. No match at all             → ``exact_match=False``, uses ``_FALLBACK_HEX``

    Never raises. Always returns a ``ColorResolution`` with a valid 6-char hex.

    Args:
        keyword: Color description supplied by the user (any case, any spacing).

    Returns:
        ``ColorResolution`` with ``hex_code``, ``exact_match``, and ``matched_keyword``.
    """
    key = keyword.strip().lower()

    # 1. Exact match
    if key in _COLOR_TABLE:
        logger.debug("Exact color match '%s' → #%s", keyword, _COLOR_TABLE[key])
        return ColorResolution(
            hex_code=_COLOR_TABLE[key],
            exact_match=True,
            matched_keyword=key,
        )

    # 2. Prefix / substring match (same logic as the original keyword_to_hex)
    for table_key, table_hex in _COLOR_TABLE.items():
        if table_key in key or key in table_key:
            logger.debug(
                "Partial color match '%s' → #%s (via table key '%s')",
                keyword,
                table_hex,
                table_key,
            )
            return ColorResolution(
                hex_code=table_hex,
                exact_match=False,
                matched_keyword=table_key,
            )

    # 3. No match — neutral fallback
    logger.warning(
        "Unknown color keyword '%s' — no table match; falling back to #%s",
        keyword,
        _FALLBACK_HEX,
    )
    return ColorResolution(
        hex_code=_FALLBACK_HEX,
        exact_match=False,
        matched_keyword="",
    )


def keyword_to_hex(keyword: str) -> str:
    """Convert natural language color keyword to 6-char uppercase hex.

    Delegates to ``resolve_color_keyword()`` — zero LLM calls, zero cost, deterministic.
    Falls back to neutral grey if keyword is not in the table.

    Args:
        keyword: Color description (e.g., "navy blue", "light gray")

    Returns:
        6-char uppercase hex code without # (e.g., "1F3A5F")
    """
    return resolve_color_keyword(keyword).hex_code


def _hex_to_lab(hex_color: str) -> tuple[float, float, float]:
    """Convert 6-char hex to CIE Lab (D65 illuminant)."""
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0

    def linearize(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = linearize(r), linearize(g), linearize(b)
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = (0.2126729 * r + 0.7151522 * g + 0.0721750 * b) / 1.0
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1.0 / 3.0) if t > 0.008856 else 7.787 * t + 16.0 / 116.0

    lab_l = 116.0 * f(y) - 16.0
    lab_a = 500.0 * (f(x) - f(y))
    lab_b = 200.0 * (f(y) - f(z))
    return lab_l, lab_a, lab_b


def delta_e(hex1: str, hex2: str) -> float:
    """Calculate CIE76 delta-E distance between two hex colors.

    Args:
        hex1: First color as 6-char hex (without #)
        hex2: Second color as 6-char hex (without #)

    Returns:
        Delta-E distance (0 = identical, higher = more different)
    """
    try:
        l1, a1, b1 = _hex_to_lab(hex1.lstrip("#"))
        l2, a2, b2 = _hex_to_lab(hex2.lstrip("#"))
        return math.sqrt((l1 - l2) ** 2 + (a1 - a2) ** 2 + (b1 - b2) ** 2)
    except (ValueError, IndexError) as e:
        logger.warning("Failed to parse hex colors %s, %s: %s", hex1, hex2, e)
        return float("inf")


def match_catalog_color(
    hex_code: str, catalog: dict[str, dict[str, Any]], tolerance: float = DELTA_E_TOLERANCE
) -> tuple[str, float] | None:
    """Find nearest catalog color within tolerance.

    Args:
        hex_code: Target color as 6-char hex (without #)
        catalog: Catalog dict keyed by sku_id
        tolerance: Max delta-E distance to match

    Returns:
        Tuple of (matched_sku_id, delta_e_distance) or None if no match within tolerance
    """
    best_match: tuple[str, float] | None = None
    best_distance = tolerance

    for sku_id, sku_data in catalog.items():
        catalog_hex = sku_data.get("color", "000000")
        distance = delta_e(hex_code, catalog_hex)

        if distance < best_distance:
            best_distance = distance
            best_match = (sku_id, distance)

    if best_match:
        logger.debug(
            "Matched color %s to SKU %s (delta-E %.2f)",
            hex_code,
            best_match[0],
            best_match[1],
        )

    return best_match
