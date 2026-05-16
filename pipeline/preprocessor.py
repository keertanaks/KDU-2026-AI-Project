"""Layer 2 orchestrator: Agent 1 → catalog load → Agent 2, sequential."""

from __future__ import annotations

from typing import Any

import anthropic

from agents.catalog_selector import CatalogSelector
from agents.prompt_parser import PromptParser
from dtos.contracts import PreprocessingOutput, SpatialEngineOutput
from mcp_server.catalog_loader import get_catalog
from utils.logger import get_logger

logger = get_logger(__name__)


class Preprocessor:
    """Sequential Layer 2: parse intent, load catalog, select SKUs."""

    def __init__(self, client: anthropic.Anthropic) -> None:
        """Initialise with Anthropic client."""
        self._client = client

    def run(
        self,
        input_json: dict[str, Any],
        spatial: SpatialEngineOutput,
    ) -> PreprocessingOutput:
        """Run Layer 2 sequentially and return PreprocessingOutput."""
        preferences = input_json.get("preferences", {})
        catalog_id = preferences.get("catalogId", "catalog")

        intent = PromptParser(self._client).parse(preferences)
        logger.info("Intent parsed: layout_family=%s style=%s", intent.layout_family, intent.style)

        catalog = get_catalog(catalog_id)
        logger.info("Catalog '%s' loaded: %d SKUs", catalog_id, len(catalog))

        result = CatalogSelector(self._client, catalog).select(intent, spatial)
        logger.info("Preprocessing complete: %d SKUs selected", len(result.skus))
        return result
