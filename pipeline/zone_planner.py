"""Layer 3 orchestrator: wraps LayoutStrategist for parallel variant generation."""

from __future__ import annotations

from typing import Any

import anthropic

from agents.layout_strategist import LayoutStrategist
from dtos.contracts import PreprocessingOutput, SpatialEngineOutput, ZonePlannerOutput
from utils.logger import get_logger

logger = get_logger(__name__)


class ZonePlanner:
    """Layer 3: produce layout variants via LayoutStrategist."""

    def __init__(self, client: anthropic.Anthropic) -> None:
        """Initialise with Anthropic client."""
        self._strategist = LayoutStrategist(client)

    async def run(
        self,
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
        input_json: dict[str, Any],
        retry_context: dict[str, list[str]] | None = None,
    ) -> list[ZonePlannerOutput]:
        """Run LayoutStrategist and return a list of zone plan variants."""
        preferences = input_json.get("preferences", {})
        variants = await self._strategist.run(
            preprocessing.intent,
            preprocessing,
            spatial,
            preferences,
            retry_context or None,
        )
        logger.info(
            "Zone planner produced %d variants (retry=%s)",
            len(variants),
            retry_context is not None and len(retry_context) > 0,
        )
        return variants
