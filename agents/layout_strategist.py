"""Agent 3: Layout Strategist — Semantic zone placement for kitchen variants.

Outputs ZERO numbers. Only semantic vocabulary terms describing positions.
Placement Engine resolves all mm coordinates downstream.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import anthropic

from dtos.contracts import (
    IntentDTO,
    PreprocessingOutput,
    SpatialEngineOutput,
    ZonePlannerOutput,
)
from utils.logger import get_logger
from utils.model_selector import for_agent, should_use_opus

logger = get_logger(__name__)

# Number of variants generated per request
N_VARIANTS: int = 3

# Valid layout shapes for Mode B auto-selection
SHAPES: list[str] = ["L", "U", "galley", "one_wall", "island"]

# Variant ID by (index, mode)
MODE_A_IDS: dict[int, str] = {1: "v1", 2: "v2", 3: "v3"}
MODE_B_IDS: dict[int, str] = {1: "vA", 2: "vB", 3: "vC"}

# Shape assigned to each Mode B variant slot
MODE_B_SHAPES: dict[int, str] = {1: "L", 2: "U", 3: "galley"}

# Strategy seed per variant index (from CLAUDE.md)
SEEDS: dict[int, str] = {
    1: ("Prefer L-shape. Maximise counter run on the longest wall. Fridge at far end."),
    2: ("Prefer U-shape. Close the work triangle tightly. Dishwasher opposite the sink wall."),
    3: ("Prefer I-shape or island. Minimise total cabinet cost. Use narrower SKUs where possible."),
    4: "Maximise storage. Prioritise tall cabinets and wall cabinets over base units.",
    5: ("Accessibility focus. Maximise aisle widths. No tall cabinets blocking circulation."),
}

# Regex patterns matching the allowed semantic vocabulary
VALID_TERM_PATTERNS: list[str] = [
    r"at north-west corner",
    r"at north-east corner",
    r"at south-west corner",
    r"at south-east corner",
    r"near \w+ window",
    r"centre of \w+",
    r"left end of \w+",
    r"right end of \w+",
    r"next to [\w\s]+",
    r"above [\w\s]+",
    r"leave gap before [\w\s]+",
]

FALLBACK_TERM_PREFIX: str = "left end of"

# Self-assessment score below this triggers an Opus retry
SCORE_RETRY_THRESHOLD: float = 0.60


class LayoutStrategist:
    """Generate semantic layout strategies for kitchen design variants."""

    def __init__(self, client: anthropic.Anthropic) -> None:
        """Initialise with Anthropic client."""
        self.client = client
        self._tools = [self._build_tool_schema()]
        self._system = self._build_system()

    async def run(
        self,
        intent: IntentDTO,
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
        preferences: dict[str, Any],
        retry_context: dict[str, list[str]] | None = None,
    ) -> list[ZonePlannerOutput]:
        """Generate N_VARIANTS layout strategies in parallel.

        Mode A: intent.layout_family set → same shape, differing zone strategies.
        Mode B: layout_family None → each variant picks a different shape.
        Retries with Opus when self-assessed score < SCORE_RETRY_THRESHOLD
        or when retry_context supplies external violations.
        """
        tasks = [
            self._plan_single(intent, preprocessing, spatial, i + 1, retry_context)
            for i in range(N_VARIANTS)
        ]
        return list(await asyncio.gather(*tasks))

    # ------------------------------------------------------------------ #
    # Per-variant orchestration                                            #
    # ------------------------------------------------------------------ #

    async def _plan_single(
        self,
        intent: IntentDTO,
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
        variant_index: int,
        retry_context: dict[str, list[str]] | None,
    ) -> ZonePlannerOutput:
        """Plan one variant; escalate to Opus when warranted."""
        variant_id = self._variant_id(variant_index, intent.layout_family)
        ext_violations = (retry_context or {}).get(variant_id, [])

        # External retry: LangGraph signalled violations → go straight to Opus
        if ext_violations:
            return await self._call_model(
                intent,
                preprocessing,
                spatial,
                variant_index,
                is_retry=True,
                violations=ext_violations,
            )

        # Primary Sonnet call
        plan, score = await self._call_model_scored(
            intent,
            preprocessing,
            spatial,
            variant_index,
            is_retry=False,
            violations=[],
        )

        # Self-assessment retry
        if should_use_opus(score, []):
            logger.info(
                "Variant %s self-score %.2f triggers Opus retry",
                variant_id,
                score,
            )
            plan, _ = await self._call_model_scored(
                intent,
                preprocessing,
                spatial,
                variant_index,
                is_retry=True,
                violations=[],
            )

        return plan

    async def _call_model_scored(
        self,
        intent: IntentDTO,
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
        variant_index: int,
        *,
        is_retry: bool,
        violations: list[str],
    ) -> tuple[ZonePlannerOutput, float]:
        """Make one model call; return plan + placeholder self-assessment score."""
        plan = await self._call_model(
            intent,
            preprocessing,
            spatial,
            variant_index,
            is_retry=is_retry,
            violations=violations,
        )
        score = getattr(plan, "_self_score", 1.0)
        return plan, score

    async def _call_model(
        self,
        intent: IntentDTO,
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
        variant_index: int,
        *,
        is_retry: bool,
        violations: list[str],
    ) -> ZonePlannerOutput:
        """Issue API call and return validated ZonePlannerOutput."""
        variant_id = self._variant_id(variant_index, intent.layout_family)
        model = for_agent("layout_strategist", is_retry=is_retry)
        seed = self._build_seed_suffix(variant_index, intent.layout_family)
        user_msg = self._build_user_message(intent, preprocessing, spatial, seed, violations)

        try:
            response = await asyncio.to_thread(
                self.client.messages.create,
                model=model,
                max_tokens=2048,
                system=[
                    {
                        "type": "text",
                        "text": self._system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                tools=self._tools,
                tool_choice={"type": "tool", "name": "plan_layout"},
                messages=[{"role": "user", "content": user_msg}],
            )

            tool_block = None
            for block in response.content:
                if block.type == "tool_use" and block.name == "plan_layout":
                    tool_block = block
                    break

            if not tool_block:
                logger.warning(
                    "No plan_layout block for variant %s — using fallback",
                    variant_id,
                )
                return self._fallback_plan(variant_id, intent.layout_family)

            plan = self._parse_tool_output(tool_block.input, variant_id, intent.layout_family)
            return self._validate_terms(plan)

        except Exception as e:
            logger.error("Agent 3 API failed for variant %s: %s", variant_id, e)
            return self._fallback_plan(variant_id, intent.layout_family)

    # ------------------------------------------------------------------ #
    # Prompt construction                                                  #
    # ------------------------------------------------------------------ #

    def _build_system(self) -> str:
        """Build static system prompt (cached across all variants)."""
        vocab = "\n".join(
            f'- "{t}"'
            for t in [
                "at north-west corner",
                "at north-east corner",
                "at south-west corner",
                "at south-east corner",
                "near {wall} window",
                "centre of {wall}",
                "left end of {wall}",
                "right end of {wall}",
                "next to {item_name}",
                "above {item_name}",
                "leave gap before {item_name}",
            ]
        )
        return (
            "You are a kitchen layout strategist. "
            "You plan where items go — not coordinates, just semantic positions.\n\n"
            "CRITICAL RULES:\n"
            "1. NEVER output any numbers, measurements, or coordinates\n"
            "2. ONLY use the semantic vocabulary listed below\n"
            "3. Fridge and tall cabinets ALWAYS at corners or ends of walls\n"
            "4. If a window exists on a wall, place sink 'near {wall} window'\n"
            "5. Dishwasher ALWAYS 'next to sink'\n"
            "6. Hood ALWAYS 'above stove'\n"
            "7. Use 'leave gap before fridge' to separate fridge from stove\n\n"
            f"SEMANTIC VOCABULARY (use ONLY these exact terms):\n{vocab}\n\n"
            "Respond only via the plan_layout tool."
        )

    def _build_seed_suffix(self, variant_index: int, layout_family: str | None) -> str:
        """Return variant strategy seed, respecting Mode A/B."""
        seed = SEEDS.get(variant_index, SEEDS[1])
        if layout_family:
            # Mode A: override shape with user's choice; keep rest of seed
            rest = seed.split(".", 1)[1].strip() if "." in seed else seed
            return f"Layout shape: {layout_family}-shape (user requested). {rest}"
        # Mode B: seed determines both shape and strategy
        return seed

    def _build_user_message(
        self,
        intent: IntentDTO,
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
        seed: str,
        violations: list[str],
    ) -> str:
        """Build per-variant user prompt."""
        walls = [w.name for w in spatial.walls if w.has_cabinets]
        windows = [f"{o.wall} window" for o in spatial.exclusions if o.kind == "window"]
        zones = list(preprocessing.zone_groups.keys())

        msg = (
            f"Strategy: {seed}\n\n"
            f"Cabinet walls: {', '.join(walls)}\n"
            f"Windows: {', '.join(windows) or 'none'}\n"
            f"Zones to place: {', '.join(zones)}\n"
            f"Layout capacity: {spatial.layout_capacity}\n"
            f"Style: {intent.style or 'any'}\n"
            f"Special requests: {', '.join(intent.special_requests) or 'none'}\n"
        )

        if violations:
            violations_json = json.dumps(violations, indent=2)
            msg += (
                f"\nRETRY MODE — fix ALL violations:\n"
                f"{violations_json}\n"
                "Pay attention to: WORKFLOW-03 (work triangle) and NKBA-CL-01 "
                "(fridge clearance).\n"
            )

        return msg

    # ------------------------------------------------------------------ #
    # Tool schema                                                          #
    # ------------------------------------------------------------------ #

    def _build_tool_schema(self) -> dict[str, Any]:
        """Build plan_layout tool schema for structured output."""
        return {
            "name": "plan_layout",
            "description": "Output a semantic kitchen layout plan for one variant",
            "input_schema": {
                "type": "object",
                "properties": {
                    "variant_id": {"type": "string"},
                    "room_shape": {
                        "type": "string",
                        "enum": SHAPES,
                        "description": "Kitchen layout shape",
                    },
                    "wall_strategies": {
                        "type": "object",
                        "description": "wall_name → list of semantic placement strings",
                        "additionalProperties": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "zone_assignments": {
                        "type": "object",
                        "description": "zone_name → wall_name",
                        "additionalProperties": {"type": "string"},
                    },
                    "adjacency_hints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Semantic adjacency rules, no numbers",
                    },
                    "work_triangle_priority": {
                        "type": "boolean",
                        "description": "True → placement engine enforces WORKFLOW-03",
                    },
                    "avoid_zones": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Zone names to deprioritise",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Free-text rationale — no numbers",
                    },
                    "self_assessment_score": {
                        "type": "number",
                        "description": "Self-rated quality 0.0-1.0",
                    },
                },
                "required": [
                    "variant_id",
                    "room_shape",
                    "wall_strategies",
                    "zone_assignments",
                    "adjacency_hints",
                    "work_triangle_priority",
                    "avoid_zones",
                    "notes",
                    "self_assessment_score",
                ],
            },
        }

    # ------------------------------------------------------------------ #
    # Parsing & validation                                                 #
    # ------------------------------------------------------------------ #

    def _parse_tool_output(
        self,
        data: dict[str, Any],
        variant_id: str,
        layout_family: str | None,
    ) -> ZonePlannerOutput:
        """Convert raw tool output to ZonePlannerOutput; attach score attr."""
        room_shape = str(data.get("room_shape") or layout_family or SHAPES[0])
        plan = ZonePlannerOutput(
            variant_id=variant_id,
            family=room_shape,
            wall_strategies={k: list(v) for k, v in (data.get("wall_strategies") or {}).items()},
            zone_assignments=dict(data.get("zone_assignments") or {}),
            work_triangle_priority=bool(data.get("work_triangle_priority", True)),
            adjacency_hints=list(data.get("adjacency_hints") or []),
            avoid_zones=list(data.get("avoid_zones") or []),
            notes=str(data.get("notes") or ""),
        )
        # Temporary attr for retry score check — not part of DTO contract
        plan.__dict__["_self_score"] = float(data.get("self_assessment_score", 1.0))
        return plan

    def _validate_terms(self, plan: ZonePlannerOutput) -> ZonePlannerOutput:
        """Replace invalid semantic terms with fallback; log each replacement."""
        validated: dict[str, list[str]] = {}
        for wall, strategies in plan.wall_strategies.items():
            clean: list[str] = []
            for term in strategies:
                if self._is_valid_term(term):
                    clean.append(term)
                else:
                    fallback = f"{FALLBACK_TERM_PREFIX} {wall}"
                    logger.warning(
                        "Invalid semantic term '%s' on wall '%s' → '%s'",
                        term,
                        wall,
                        fallback,
                    )
                    clean.append(fallback)
            validated[wall] = clean
        plan.wall_strategies = validated
        return plan

    def _is_valid_term(self, term: str) -> bool:
        """Return True if term matches any valid semantic vocabulary pattern."""
        return any(re.fullmatch(pattern, term, re.IGNORECASE) for pattern in VALID_TERM_PATTERNS)

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _variant_id(self, index: int, layout_family: str | None) -> str:
        """Return variant ID for Mode A or Mode B."""
        if layout_family:
            return MODE_A_IDS.get(index, f"v{index}")
        return MODE_B_IDS.get(index, f"v{chr(64 + index)}")

    def _fallback_plan(self, variant_id: str, layout_family: str | None) -> ZonePlannerOutput:
        """Return a minimal valid plan on API failure."""
        return ZonePlannerOutput(
            variant_id=variant_id,
            family=layout_family or SHAPES[0],
            wall_strategies={},
            zone_assignments={},
            work_triangle_priority=True,
            adjacency_hints=[],
            avoid_zones=[],
            notes="Fallback plan — API call failed",
        )
