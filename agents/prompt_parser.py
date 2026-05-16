"""Agent 1: Prompt Parser — extract structured kitchen intent from user input.

Converts free-form user prompts into structured IntentDTO with color,
layout, style, and cabinet preferences. Always returns valid DTO — never fails.
"""

from __future__ import annotations

from typing import Any

import anthropic

from dtos.contracts import IntentDTO
from utils.logger import get_logger
from utils.model_selector import for_agent

logger = get_logger(__name__)


class PromptParser:
    """Extract structured kitchen design intent from user prompt."""

    def __init__(self, client: anthropic.Anthropic) -> None:
        """Initialize parser with Anthropic client."""
        self.client = client
        self._tools = [self._build_tool_schema()]
        self._system = self._build_system()

    def parse(self, preferences: dict[str, Any]) -> IntentDTO:
        """Parse user intent from prompt in preferences dict.

        Args:
            preferences: Dict with 'prompt' and fallback fields
                (budget_tier, must_have, avoid, etc.)

        Returns:
            IntentDTO with parsed fields — never raises, always returns valid DTO
        """
        prompt = preferences.get("prompt", "")

        if not prompt:
            logger.warning("Empty prompt — returning fallback IntentDTO")
            return self._fallback_intent(preferences)

        try:
            model = for_agent("prompt_parser")
            logger.debug("Parsing prompt with %s", model)

            # Call API with tool forcing
            message = self.client.messages.create(
                model=model,
                max_tokens=1000,
                system=[
                    {"type": "text", "text": self._system, "cache_control": {"type": "ephemeral"}}
                ],
                tools=self._tools,
                tool_choice={"type": "tool", "name": "extract_intent"},
                messages=[{"role": "user", "content": prompt}],
            )

            # Extract tool use block
            tool_use = None
            for block in message.content:
                if block.type == "tool_use":
                    tool_use = block
                    break

            if not tool_use:
                logger.warning("No tool_use block in response — returning fallback")
                return self._fallback_intent(preferences)

            # Parse tool input as dict
            extracted = tool_use.input

            # Merge with preferences fallback
            return self._merge_with_preferences(extracted, preferences)

        except Exception as e:
            logger.error("Agent 1 API failed: %s — returning fallback IntentDTO", e)
            return self._fallback_intent(preferences)

    def _build_system(self) -> str:
        """Build system prompt for intent extraction."""
        return """You are a kitchen design intent extractor.
Your task is to extract structured information from a user's kitchen design request.

Rules:
- NEVER fail or return an error — always extract best-effort information
- If field not determined from prompt, set to null and use preferences JSON fallback
- Extract kitchen-related requests ONLY — log non-kitchen in "ignored" array
- Color keywords resolved to hex code (navy, white, oak, etc.)
- Layout family: L (two walls), U (three walls), I/one_wall (single wall),
  galley (two parallel walls), island (open plan with island)
  — only if user explicitly mentions a shape
- Style: capture any style words (modern, traditional, minimalist, rustic, etc.)
- Cabinet preference: base_only, with_uppers, with_tall — only if explicitly stated
- special_requests: island, pantry, extra storage, etc.
- must_have: do NOT extract — pass empty array, merged from preferences
- avoid: do NOT extract — pass empty array, merged from preferences

Always respond using the extract_intent tool with all required fields."""

    def _build_tool_schema(self) -> dict[str, Any]:
        """Build tool schema for structured extraction."""
        return {
            "name": "extract_intent",
            "description": "Extract structured kitchen design intent from user prompt",
            "input_schema": {
                "type": "object",
                "properties": {
                    "color_keyword": {
                        "type": ["string", "null"],
                        "description": "Color name from prompt, e.g. 'navy blue'",
                    },
                    "color_hex": {
                        "type": ["string", "null"],
                        "description": "Hex code resolved from color_keyword, e.g. '1f3a5f'",
                    },
                    "layout_family": {
                        "type": ["string", "null"],
                        "enum": ["L", "U", "I", "galley", "island", "one_wall", None],
                        "description": (
                            "Layout shape if explicitly mentioned: "
                            "L=two walls, U=three walls, I/one_wall=single wall, "
                            "galley=two parallel walls, island=open plan with island"
                        ),
                    },
                    "style": {
                        "type": ["string", "null"],
                        "description": "Style (modern, traditional, minimalist, rustic, etc.)",
                    },
                    "cabinet_preference": {
                        "type": ["string", "null"],
                        "enum": ["base_only", "with_uppers", "with_tall", None],
                        "description": "Cabinet type preference if explicitly stated",
                    },
                    "special_requests": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "e.g. ['island', 'pantry', 'extra storage']",
                    },
                    "ignored": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Non-kitchen requests from prompt, e.g. ['AC', 'TV']",
                    },
                    "budget_tier": {
                        "type": ["string", "null"],
                        "description": "Budget tier if mentioned: low, mid, high, premium",
                    },
                },
                "required": [
                    "color_keyword",
                    "color_hex",
                    "layout_family",
                    "style",
                    "cabinet_preference",
                    "special_requests",
                    "ignored",
                    "budget_tier",
                ],
            },
        }

    def _merge_with_preferences(
        self, extracted: dict[str, Any], preferences: dict[str, Any]
    ) -> IntentDTO:
        """Merge extracted intent with preferences fallback."""
        return IntentDTO(
            color_keyword=extracted.get("color_keyword"),
            color_hex=extracted.get("color_hex"),
            layout_family=extracted.get("layout_family"),
            style=extracted.get("style") or preferences.get("style"),
            cabinet_preference=extracted.get("cabinet_preference"),
            special_requests=(extracted.get("special_requests") or []),
            ignored=extracted.get("ignored", []),
            budget_tier=extracted.get("budget_tier") or preferences.get("budget_tier"),
            must_have=preferences.get("must_have", []),
            avoid=preferences.get("avoid", []),
        )

    def _fallback_intent(self, preferences: dict[str, Any]) -> IntentDTO:
        """Return empty IntentDTO with preferences fallback on budget/must_have/avoid."""
        return IntentDTO(
            color_keyword=None,
            color_hex=None,
            layout_family=None,
            style=None,
            cabinet_preference=None,
            special_requests=[],
            ignored=[],
            budget_tier=preferences.get("budget_tier", "mid"),
            must_have=preferences.get("must_have", []),
            avoid=preferences.get("avoid", []),
        )
