"""Resolve natural language color descriptions to catalog hex codes.

Uses Claude to interpret color keywords, then matches against catalog colors
using CIE76 delta-E distance in Lab color space.
"""

from __future__ import annotations

from typing import Any

import anthropic
from colormath.color_conversions import convert_color
from colormath.color_diff import delta_e_cie76
from colormath.color_objects import LabColor, sRGBColor

from utils.logger import get_logger
from utils.model_selector import for_agent

logger = get_logger(__name__)

# Delta-E tolerance for color matching (CIE Lab distance)
DELTA_E_TOLERANCE = 15.0


def keyword_to_hex(keyword: str, client: anthropic.Anthropic) -> str:
    """Convert natural language color keyword to 6-char hex using Claude.

    Args:
        keyword: Color description (e.g., "navy blue", "light gray")
        client: Anthropic API client

    Returns:
        6-char lowercase hex code (e.g., "1f3a5f")

    Raises:
        anthropic.APIError: If API call fails
    """
    prompt = f"""Convert this color description to a 6-digit hex color code (without the # symbol).
Return ONLY the hex code, nothing else.

Color description: {keyword}"""

    try:
        model = for_agent("catalog_selector")
        message = client.messages.create(
            model=model,
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )

        result = message.content[0].text.strip().lower()
        # Remove # if present and validate
        if result.startswith("#"):
            result = result[1:]
        # Ensure 6 chars
        hex_code: str = result.zfill(6)[:6]

        logger.debug("Resolved color '%s' to hex %s", keyword, hex_code)
        return hex_code

    except anthropic.APIError as e:
        logger.error("Failed to resolve color keyword '%s': %s", keyword, e)
        # Fallback to neutral gray
        return "808080"


def delta_e(hex1: str, hex2: str) -> float:
    """Calculate CIE76 delta-E distance between two hex colors.

    Args:
        hex1: First color as 6-char hex (without #)
        hex2: Second color as 6-char hex (without #)

    Returns:
        Delta-E distance (0 = identical, higher = more different)
    """
    try:
        # Parse hex to RGB
        r1 = int(hex1[0:2], 16) / 255.0
        g1 = int(hex1[2:4], 16) / 255.0
        b1 = int(hex1[4:6], 16) / 255.0

        r2 = int(hex2[0:2], 16) / 255.0
        g2 = int(hex2[2:4], 16) / 255.0
        b2 = int(hex2[4:6], 16) / 255.0

        # Convert to Lab
        color1 = convert_color(sRGBColor(r1, g1, b1), LabColor)
        color2 = convert_color(sRGBColor(r2, g2, b2), LabColor)

        # Calculate delta-E
        distance: float = delta_e_cie76(color1, color2)
        return distance

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
