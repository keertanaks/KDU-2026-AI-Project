"""Agent 4: Rationale Writer — explains layout decisions in plain English.

Uses claude-haiku-4-5 with a forced write_rationale tool call.
Always returns a valid list — never raises.
"""

from __future__ import annotations

import asyncio
from typing import Any

import anthropic

from dtos.contracts import VariantSummaryDTO
from utils.logger import get_logger
from utils.model_selector import for_agent

logger = get_logger(__name__)


class RationaleWriter:
    """Generate plain-English rationale for a scored kitchen layout variant."""

    def __init__(self, client: anthropic.Anthropic) -> None:
        """Initialise with Anthropic client."""
        self.client = client
        self._tools = [self._build_tool_schema()]
        self._system = self._build_system()

    async def write(self, variant: VariantSummaryDTO) -> list[dict[str, Any]]:
        """Write rationale for one variant; return fallback on any failure."""
        model = for_agent("rationale_writer")
        user_msg = self._build_user_message(variant)

        try:
            response = await asyncio.to_thread(
                self.client.messages.create,
                model=model,
                max_tokens=1024,
                system=[
                    {
                        "type": "text",
                        "text": self._system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                tools=self._tools,
                tool_choice={"type": "tool", "name": "write_rationale"},
                messages=[{"role": "user", "content": user_msg}],
            )

            tool_block = None
            for block in response.content:
                if block.type == "tool_use" and block.name == "write_rationale":
                    tool_block = block
                    break

            if not tool_block:
                logger.warning(
                    "No write_rationale block for variant '%s' — using fallback",
                    variant.id,
                )
                return self._fallback_rationale(variant)

            rationale = list(tool_block.input.get("rationale") or [])
            logger.info(
                "Rationale written for variant '%s': %d entries",
                variant.id,
                len(rationale),
            )
            return rationale

        except Exception as e:
            logger.error(
                "Agent 4 API failed for variant '%s': %s — using fallback",
                variant.id,
                e,
            )
            return self._fallback_rationale(variant)

    # ------------------------------------------------------------------ #
    # Prompt construction                                                  #
    # ------------------------------------------------------------------ #

    def _build_system(self) -> str:
        """Build static system prompt."""
        return (
            "You are a kitchen design rationale writer.\n"
            "For each significant placement decision and each NKBA rule outcome, "
            "write one concise plain-English sentence.\n"
            "Output only via the write_rationale tool.\n"
            "rule_id must be a rule ID (e.g. 'LAYOUT-01') "
            "or a label ('COLOR-MATCH', 'GENERAL')."
        )

    def _build_user_message(self, variant: VariantSummaryDTO) -> str:
        """Build the per-variant user prompt."""
        violation_ids = [v["rule_id"] for v in variant.violations] or "none"
        warnings = variant.warnings or "none"
        return (
            f"Variant {variant.id} — score {variant.score:.2f} — family {variant.family}\n"
            f"Placed items: {variant.placement_count}\n"
            f"Violations: {violation_ids}\n"
            f"Warnings: {warnings}\n"
            "Write rationale explaining the main placement decisions and rule outcomes."
        )

    # ------------------------------------------------------------------ #
    # Tool schema                                                          #
    # ------------------------------------------------------------------ #

    def _build_tool_schema(self) -> dict[str, Any]:
        """Build write_rationale tool schema."""
        return {
            "name": "write_rationale",
            "description": "Output rationale for a kitchen layout variant",
            "input_schema": {
                "type": "object",
                "properties": {
                    "rationale": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "rule_id": {"type": "string"},
                                "text": {"type": "string"},
                            },
                            "required": ["rule_id", "text"],
                        },
                    }
                },
                "required": ["rationale"],
            },
        }

    # ------------------------------------------------------------------ #
    # Fallback                                                             #
    # ------------------------------------------------------------------ #

    def _fallback_rationale(self, variant: VariantSummaryDTO) -> list[dict[str, Any]]:
        """Return minimal valid rationale on any failure."""
        return [
            {
                "rule_id": "GENERAL",
                "text": (f"Score {variant.score:.2f} with {len(variant.violations)} violations."),
            }
        ]
