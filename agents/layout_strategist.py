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

# Max tokens for plan_layout tool response.
# The structured JSON output is typically 600-900 tokens; 1400 gives headroom
# without triggering 402 credit errors on budget OpenRouter accounts.
PLAN_LAYOUT_MAX_TOKENS: int = 1400

# Valid layout shapes — L/U/I match TDD section 2.3 exactly.
# 'island' is a special_request, never a family.
SHAPES: list[str] = ["L", "U", "I"]

# Variant ID by (index, mode)
MODE_A_IDS: dict[int, str] = {1: "v1", 2: "v2", 3: "v3"}
MODE_B_IDS: dict[int, str] = {1: "vA", 2: "vB", 3: "vC"}

# Shape assigned to each Mode B variant slot when capacity supports it.
MODE_B_SHAPES: dict[int, str] = {1: "L", 2: "U", 3: "I"}

# Capacity-restricted Mode B slot maps: chosen when the room can't support U.
MODE_B_SHAPES_CAPACITY_L: dict[int, str] = {1: "L", 2: "I", 3: "L"}
MODE_B_SHAPES_CAPACITY_I: dict[int, str] = {1: "I", 2: "I", 3: "I"}

# How many cabinet walls each family requires.
_FAMILY_WALLS: dict[str, int] = {"I": 1, "L": 2, "U": 3}

# Strategy seed per variant index (from CLAUDE.md)
# Shape names MUST match the SHAPES enum exactly so Agent 3 picks them reliably.
SEEDS: dict[int, str] = {
    1: "room_shape MUST be L. Maximise counter run on the longest wall. Fridge at far end.",
    2: "room_shape MUST be U. Tighten the work triangle. Spread fridge, sink, stove across walls.",
    3: "room_shape MUST be I. Minimise total cabinet cost. Use narrower SKUs where possible.",
    4: "room_shape MUST be L. Maximise storage. Prioritise tall cabinets and wall cabinets over base units.",
    5: "room_shape MUST be U. Accessibility focus. Maximise aisle widths. No tall cabinets blocking circulation.",
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

# Word prefixes the model incorrectly prepends to position terms
# e.g. "sink centre of east_wall" → strip "sink" → "centre of east_wall"
_ITEM_STRIP_PREFIXES: tuple[str, ...] = (
    "fridge ",
    "refrigerator ",
    "sink ",
    "stove ",
    "range ",
    "hood ",
    "dishwasher ",
    "tap ",
    "oven ",
    "microwave ",
    "preparation ",
    "storage ",
    "cooking ",
    "cleaning ",
    "cooling ",
    "base_cabinet ",
    "wall_cabinet ",
    "tall_cabinet ",
    "cabinet ",
    "island ",
)


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
        effective_family = self._effective_family(variant_index, intent, spatial)
        model = for_agent("layout_strategist", is_retry=is_retry)
        seed = self._build_seed_suffix(variant_index, effective_family)
        user_msg = self._build_user_message(
            intent, preprocessing, spatial, seed, violations, variant_index
        )

        try:
            response = await asyncio.to_thread(
                self.client.messages.create,
                model=model,
                max_tokens=PLAN_LAYOUT_MAX_TOKENS,
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
                return self._fallback_plan(variant_id, effective_family)

            plan = self._parse_tool_output(tool_block.input, variant_id, effective_family)
            return self._validate_terms(plan)

        except Exception as e:
            logger.error("Agent 3 API failed for variant %s: %s", variant_id, e)
            return self._fallback_plan(variant_id, effective_family)

    # ------------------------------------------------------------------ #
    # Prompt construction                                                  #
    # ------------------------------------------------------------------ #

    def _build_system(self) -> str:
        """Build static system prompt (cached across all variants)."""
        return (
            "You are Agent 3 — Kitchen Layout Strategist for an AI kitchen design system.\n"
            "You output ONE variant per call. Semantic placement only — never numbers, "
            "never mm, never coordinates. The Placement Engine resolves all geometry.\n"
            "Respond ONLY via the plan_layout tool. No free-text.\n\n"
            # ── CORE CONTRACT ──────────────────────────────────────────────
            "== CORE CONTRACT ==\n"
            "Primary output: item_hints — one entry per item type, with {wall, position}.\n"
            "Fallback output: wall_strategies — kept for debugging; the engine reads "
            "item_hints first.\n"
            "Use ONLY walls listed under 'Cabinet walls' in the user message. "
            "Do NOT invent walls, zones, or SKUs.\n\n"
            # ── LAYOUT FAMILIES ────────────────────────────────────────────
            "== LAYOUT FAMILIES (STRICT) ==\n"
            "L = exactly TWO adjacent cabinet walls.\n"
            "U = exactly THREE cabinet walls.\n"
            "I = exactly ONE cabinet wall — all items on that wall, no exceptions.\n"
            "The required family is given in the user message. Match it exactly.\n"
            "Never output 'island' as a family.\n\n"
            # ── SEMANTIC VOCABULARY ────────────────────────────────────────
            "== SEMANTIC VOCABULARY (only these terms allowed) ==\n"
            '  Corners : "at north-west corner" | "at north-east corner"\n'
            '            "at south-west corner" | "at south-east corner"\n'
            '  Ends    : "left end of {wall}"   | "right end of {wall}"\n'
            '  Middle  : "centre of {wall}"\n'
            '  Window  : "near {wall} window"\n'
            '  Relative: "next to {item}"       | "above {item}"\n'
            '  Gap     : "leave gap before {item}"\n'
            "Replace {wall} with a cabinet-wall name from the input. "
            "Replace {item} with one of: fridge, sink, dishwasher, stove, hood, "
            "tall_cabinet.\n\n"
            # ── ZONE RULES ─────────────────────────────────────────────────
            "== ZONE RULES ==\n"
            "Required zones (one each, no duplicates): cooling, cleaning, cooking, "
            "preparation, storage.\n"
            "Meaning:\n"
            "  cooling     = fridge / freezer\n"
            "  cleaning    = sink, dishwasher, tap\n"
            "  cooking     = stove / cooktop, oven, hood\n"
            "  preparation = counter / base cabinets\n"
            "  storage     = wall cabinets, tall cabinets, pantry\n"
            "Assign every required zone exactly once. Never emit two cooling zones.\n\n"
            # ── APPLIANCE RULES (item_hints contract) ──────────────────────
            "== APPLIANCE RULES (apply to item_hints) ==\n"
            "FRIDGE   → position MUST be a corner term. "
            "Never 'centre of wall', never an end term. Cooling sits at workflow end.\n"
            "SINK     → if its wall has a window, position MUST be 'near {wall} window'. "
            "Otherwise 'centre of {wall}'.\n"
            "DISHWASHER → wall MUST equal sink.wall. position = 'next to sink'.\n"
            "STOVE    → position = 'centre of {wall}' or an end term. Never a corner. "
            "Stove and fridge must NOT be adjacent on the same wall.\n"
            "HOOD     → wall MUST equal stove.wall. position = 'above stove'.\n"
            "OVEN / MICROWAVE → place on cooking wall; use end or 'next to stove'.\n"
            "TALL_CABINET → position = 'left end of {wall}' or 'right end of {wall}'. "
            "Never in the middle.\n\n"
            # ── WORKFLOW ───────────────────────────────────────────────────
            "== WORKFLOW (one canonical sequence) ==\n"
            "cooling → preparation → cleaning → preparation → cooking\n"
            "Spread fridge, sink, and stove enough to form a usable work triangle.\n"
            "Do not calculate or output the triangle distance — the Validator checks the exact NKBA rule.\n"
            "Do NOT cluster all three at the same end of one wall.\n"
            "  I-shape: fridge at one corner; sink at centre or window; "
            "stove near the opposite end. Dishwasher next to sink. Hood above stove.\n"
            "  L-shape: fridge + stove on primary wall (far apart); "
            "sink on secondary wall (especially if it has a window).\n"
            "  U-shape: split fridge / sink / stove across two or three walls — "
            "fridge on one wall, sink on another, stove on a third or back on fridge wall.\n\n"
            # ── DOORS / WINDOWS ────────────────────────────────────────────
            "== DOORS / WINDOWS ==\n"
            "Never place an item in a door swing area.\n"
            "Sink is strongly preferred on a wall with a window.\n"
            "Wall cabinets must not block windows; base cabinets may sit below windows.\n\n"
            # ── OUTPUT EXAMPLE ─────────────────────────────────────────────
            "== OUTPUT EXAMPLE (L-shape, north + east walls, window on east) ==\n"
            "item_hints = {\n"
            "  'fridge':     {'wall': 'north_wall', 'position': 'at north-west corner'},\n"
            "  'tall_cabinet': {'wall': 'north_wall', 'position': 'right end of north_wall'},\n"
            "  'stove':      {'wall': 'north_wall', 'position': 'centre of north_wall'},\n"
            "  'hood':       {'wall': 'north_wall', 'position': 'above stove'},\n"
            "  'sink':       {'wall': 'east_wall',  'position': 'near east_wall window'},\n"
            "  'dishwasher': {'wall': 'east_wall',  'position': 'next to sink'},\n"
            "}\n"
            "zone_assignments = {\n"
            "  'cooling': 'north_wall', 'cooking': 'north_wall',\n"
            "  'cleaning': 'east_wall', 'preparation': 'north_wall', 'storage': 'north_wall',\n"
            "}\n"
            "wall_strategies (mirror of hints, position terms only):\n"
            "  {'north_wall': ['at north-west corner', 'centre of north_wall', "
            "'above stove', 'right end of north_wall'],\n"
            "   'east_wall':  ['near east_wall window', 'next to sink']}\n\n"
            # ── FINAL CHECK ────────────────────────────────────────────────
            "== FINAL CHECK (verify before calling the tool) ==\n"
            " 1. family is exactly L, U, or I (never island).\n"
            " 2. I uses 1 wall, L uses 2 walls, U uses 3 walls.\n"
            " 3. Every wall referenced exists in 'Cabinet walls'.\n"
            " 4. No duplicate zones.\n"
            " 5. fridge.position is a corner term.\n"
            " 6. stove.position is NOT a corner term.\n"
            " 7. dishwasher.wall == sink.wall and position == 'next to sink'.\n"
            " 8. hood.wall == stove.wall and position == 'above stove'.\n"
            " 9. If sink's wall has a window, sink.position == 'near {wall} window'.\n"
            "10. No numbers, no mm, no coordinates anywhere in positions.\n"
            "11. tall_cabinet (if present) uses 'left end of {wall}' or "
            "'right end of {wall}'.\n"
            "12. Workflow: fridge and stove are not adjacent.\n"
            "Then call plan_layout."
        )

    def _build_seed_suffix(self, variant_index: int, effective_family: str) -> str:
        """Return variant strategy seed, anchored to the resolved family.

        The original SEED text mentions a shape; we override that with the
        capacity-resolved family so the prompt and the variant DTO stay aligned.
        """
        seed = SEEDS.get(variant_index, SEEDS[1])
        rest = seed.split(".", 1)[1].strip() if "." in seed else seed
        return f"Layout shape: {effective_family}-shape. {rest}"

    def _build_user_message(
        self,
        intent: IntentDTO,
        preprocessing: PreprocessingOutput,
        spatial: SpatialEngineOutput,
        seed: str,
        violations: list[str],
        variant_index: int = 1,
    ) -> str:
        """Build per-variant user prompt with variant-specific zone distribution."""
        walls = [w.name for w in spatial.walls if w.has_cabinets]
        wall_lengths = {w.name: w.length_mm for w in spatial.walls if w.has_cabinets}
        windows = [f"{o.wall} window" for o in spatial.exclusions if o.kind == "window"]
        zones = list(preprocessing.zone_groups.keys())
        total_item_width = sum(
            s.width_mm for skus in preprocessing.zone_groups.values() for s in skus
        )

        primary_wall = (
            max(wall_lengths, key=lambda n: wall_lengths[n])
            if wall_lengths
            else (walls[0] if walls else "")
        )
        secondary_walls = [w for w in walls if w != primary_wall]
        secondary = secondary_walls[0] if secondary_walls else primary_wall
        tertiary = secondary_walls[1] if len(secondary_walls) >= 2 else secondary

        # Variant-specific zone distribution — each variant is a different interpretation
        # of the same requested family shape (Mode A) or a different shape (Mode B).
        family_upper = (intent.layout_family or "").upper()

        # Corner terms for primary wall — used to differentiate I-shape variants structurally
        if "north" in primary_wall:
            _left_corner, _right_corner = "at north-west corner", "at north-east corner"
        elif "south" in primary_wall:
            _left_corner, _right_corner = "at south-west corner", "at south-east corner"
        elif "east" in primary_wall:
            _left_corner, _right_corner = "at north-east corner", "at south-east corner"
        else:
            _left_corner, _right_corner = "at north-west corner", "at south-west corner"

        if intent.layout_family and family_upper == "I":
            # Mode A I-shape: vary fridge end across variants for structural differentiation
            if variant_index == 2:
                zone_constraint = (
                    f"- ALL zones → assign to {primary_wall} only (I-shape is SINGLE-WALL)\n"
                    f"- MIRRORED layout: fridge at RIGHT end ('{_right_corner}'), stove near LEFT end\n"
                    f"  Opposite workflow direction to Variant 1\n"
                    f"- Sink at 'centre of {primary_wall}', dishwasher next to sink\n"
                    f"- Do NOT assign any zone to {secondary}\n"
                )
            elif variant_index == 3:
                zone_constraint = (
                    f"- ALL zones → assign to {primary_wall} only (I-shape is SINGLE-WALL)\n"
                    f"- Cost-efficient: fridge at '{_left_corner}', sink near window if present\n"
                    f"  otherwise 'centre of {primary_wall}', stove near right end\n"
                    f"- Minimize cabinet cost: prefer narrower base cabinets, skip tall cabinets\n"
                    f"- Do NOT assign any zone to {secondary}\n"
                )
            else:  # variant_index == 1
                zone_constraint = (
                    f"- ALL zones → assign to {primary_wall} only (I-shape is SINGLE-WALL)\n"
                    f"- Standard layout: fridge at LEFT end ('{_left_corner}'), stove near right end\n"
                    f"- Sink at 'centre of {primary_wall}', maximize counter run\n"
                    f"- Do NOT assign any zone to {secondary}\n"
                )
        elif intent.layout_family and family_upper == "L":
            # Mode A L-shape: exactly 2 walls for all 3 variants — vary WHICH wall gets cooking
            if variant_index == 2:
                # Structurally different: cooking moves to the secondary wall
                zone_constraint = (
                    f"- Cooling (fridge) → {primary_wall} (far corner, use corner term)\n"
                    f"- COOKING (stove + hood) → {secondary} wall (centre of {secondary})\n"
                    f"  This flips the work triangle: stove on the cross-wall, NOT on {primary_wall}\n"
                    f"- Cleaning (sink + dishwasher) → {secondary} alongside cooking\n"
                    f"  Use 'right end of {secondary}' for sink so dishwasher fits between stove and sink\n"
                    f"- Preparation → {primary_wall} (long counter run, no stove interruption)\n"
                    f"- L-shape MUST use exactly 2 walls: {primary_wall} AND {secondary}\n"
                )
            elif variant_index == 3:
                # Different fridge corner + storage-heavy
                zone_constraint = (
                    f"- Cooling (fridge) → {primary_wall} at the NEAR end (corner closest to {secondary})\n"
                    f"  Use the corner term for the end of {primary_wall} that adjoins {secondary}\n"
                    f"- Cooking (stove + hood) → {primary_wall}, towards the far end from fridge\n"
                    f"- Cleaning (sink + dishwasher) → {secondary}\n"
                    f"- Storage-heavy: fill remaining {secondary} space with base cabinets\n"
                    f"- L-shape MUST use both {primary_wall} AND {secondary} — do NOT collapse to one wall\n"
                )
            else:  # variant_index == 1
                zone_constraint = (
                    f"- Cooling (fridge) + cooking (stove + hood) → {primary_wall}\n"
                    f"  Fridge at FAR end of {primary_wall}, stove at centre (>600mm apart)\n"
                    f"- Cleaning (sink + dishwasher) → {secondary} (prefer window wall)\n"
                    f"  GOAL: maximize counter run on {primary_wall}; sink on cross-wall creates clean L\n"
                    f"- Preparation → {primary_wall} first; overflow to {secondary} if full\n"
                    f"- L-shape MUST use both {primary_wall} AND {secondary} — do NOT collapse to one wall\n"
                )
        elif intent.layout_family and family_upper == "U":
            # Mode A U-shape: exactly 3 walls for all 3 variants
            if variant_index == 2:
                zone_constraint = (
                    f"- Compact U: tighten work triangle (3962-6600mm perimeter)\n"
                    f"- Cooling (fridge) → {primary_wall}\n"
                    f"- Cleaning (sink + dishwasher) → {secondary} near the {primary_wall}/{secondary} corner\n"
                    f"- Cooking (stove + hood) → {tertiary}\n"
                    f"- Preparation → {secondary} alongside cleaning\n"
                    f"- U-shape MUST use 3 walls: {primary_wall}, {secondary}, {tertiary} — NO single-wall\n"
                )
            elif variant_index == 3:
                zone_constraint = (
                    f"- Storage-heavy U: maximize cabinets across all 3 walls\n"
                    f"- Cooling (fridge) → {primary_wall}\n"
                    f"- Cleaning (sink + dishwasher) → {secondary}\n"
                    f"- Cooking (stove + hood) → {tertiary}\n"
                    f"- Storage (wall cabs + tall cabs) → all 3 walls for maximum storage\n"
                    f"- U-shape MUST use 3 walls: {primary_wall}, {secondary}, {tertiary} — NO single-wall\n"
                )
            else:  # variant_index == 1
                zone_constraint = (
                    f"- Balanced U: distribute appliances across 3 walls\n"
                    f"- Cooling (fridge) → {primary_wall} (outer wall, far corner)\n"
                    f"- Cleaning (sink + dishwasher) → {secondary} (back/middle wall, near window if present)\n"
                    f"- Cooking (stove + hood) → {tertiary} (opposite outer wall)\n"
                    f"- Preparation → split between {secondary} and {tertiary}\n"
                    f"- U-shape MUST use 3 walls: {primary_wall}, {secondary}, {tertiary}\n"
                )
        elif intent.layout_family:
            # Mode A with unrecognised family — fall back to maximize on primary
            zone_constraint = (
                f"- ALL zones → assign to {primary_wall} (maximize counter run)\n"
                f"- SPREAD appliances: fridge one end, sink centre, stove other end\n"
            )
        elif variant_index == 1 and not intent.layout_family:
            # Mode B Variant 1: L-shape — classic, cooking on primary, cleaning on secondary
            zone_constraint = (
                f"- Cooling (fridge) + cooking (stove + hood) → {primary_wall}\n"
                f"  Fridge at FAR end of {primary_wall} (corner term), stove at centre (>600mm apart)\n"
                f"- Cleaning (sink + dishwasher) → {secondary} (cross-wall for clean L workflow)\n"
                f"  Use 'right end of {secondary}' so sink is near the corner for a tight work triangle\n"
                f"- Preparation → {primary_wall} first; overflow to {secondary} if needed\n"
                f"- L-shape MUST use both {primary_wall} AND {secondary}\n"
            )
        elif variant_index == 2 and not intent.layout_family:
            # Mode B Variant 2: U-shape — 3 walls, tight work triangle
            zone_constraint = (
                f"- Cooling (fridge) → {primary_wall} (far corner)\n"
                f"- Cleaning (sink + dishwasher) → {secondary} (near window if present, otherwise centre)\n"
                f"- Cooking (stove + hood) → {tertiary} (centre of {tertiary})\n"
                f"- Tight work triangle: fridge, sink, stove each on a different wall (3962-6600mm perimeter)\n"
                f"- U-shape MUST use 3 walls: {primary_wall}, {secondary}, {tertiary} — NO single-wall\n"
            )
        else:
            # Mode B Variant 3: I-shape — single wall, cost-minimizing
            zone_constraint = (
                f"- ALL zones MUST assign ONLY to {primary_wall} — I-shape is a SINGLE-WALL layout\n"
                f"- Do NOT assign ANY zone to {secondary} — that would break the I-shape constraint\n"
                f"- Cost-efficient: fridge at one end (corner term), sink at 'centre of {primary_wall}',\n"
                f"  stove near the other end (work triangle 3962-6600mm)\n"
                f"- Use narrower SKUs where possible to minimize total cabinet cost\n"
            )

        # Determine corner terms based on primary wall orientation
        corner_hint = (
            "'at north-west corner' or 'at north-east corner'"
            if "north" in primary_wall or "south" in primary_wall
            else "'at north-west corner' or 'at south-west corner'"
        )

        msg = (
            f"=== VARIANT STRATEGY ===\n"
            f"{seed}\n\n"
            f"=== ROOM DATA ===\n"
            f"Cabinet walls (assign ONLY to these): {', '.join(walls)}\n"
            f"Primary wall (longest): {primary_wall} ({int(wall_lengths.get(primary_wall, 0))}mm)\n"
            f"All wall lengths: {', '.join(f'{n}={int(wl)}mm' for n, wl in wall_lengths.items())}\n"
            f"Total item footprint: {int(total_item_width)}mm\n"
            f"Windows: {', '.join(windows) or 'none'}\n"
            f"Zones to place: {', '.join(zones)}\n"
            f"Layout capacity: {spatial.layout_capacity}\n"
            f"Style: {intent.style or 'any'}\n"
            f"Special requests: {', '.join(intent.special_requests) or 'none'}\n\n"
            f"=== ZONE ASSIGNMENTS ===\n"
            f"{zone_constraint}"
            f"- storage → any cabinet wall (wall cabinets mount above base units, no floor conflict)\n"
            f"- Valid zone keys: {', '.join(zones)}\n"
            f"- Valid wall values: {', '.join(walls)}\n\n"
            f"=== HARD CONSTRAINTS (each violation reduces score) ===\n"
            f"1. Fridge: corner position ONLY → {corner_hint}\n"
            f"2. Sink: {('near window — use near {wall} window term' if windows else f'centre of wall — use centre of {primary_wall}')}\n"
            f"3. Dishwasher: next to sink, SAME wall as sink\n"
            f"4. Hood: above stove, SAME wall as stove\n"
            f"5. Stove: NOT at a corner — use centre or end of wall\n"
            f"6. Work triangle (fridge↔sink↔stove): must be 3962–6600mm perimeter\n"
            f"   Spread them apart: fridge at one end, sink at centre, stove near other end\n"
            f"7. NKBA-02 sequence along wall: fridge → [prep] → sink → dishwasher → [prep] → stove\n"
            f"   (left-to-right; stove and fridge must NOT be adjacent)\n"
            f"8. wall_strategies: position terms ONLY — never prefix with item names\n"
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
                        "description": "Kitchen layout shape: L=2 adjacent walls, U=3 walls, I=single wall run, island=I with centre island",
                    },
                    "item_hints": {
                        "type": "object",
                        "description": (
                            "PRIMARY placement contract. Map each item type to "
                            "{'wall': <wall_name>, 'position': <semantic position term>}. "
                            "Item types: fridge, sink, dishwasher, stove, hood, oven, "
                            "microwave, tall_cabinet. Position must be a semantic vocabulary "
                            "term — no numbers, no mm, no coordinates. "
                            "Example: {'fridge': {'wall': 'north_wall', "
                            "'position': 'at north-west corner'}}."
                        ),
                        "additionalProperties": {
                            "type": "object",
                            "properties": {
                                "wall": {"type": "string"},
                                "position": {"type": "string"},
                            },
                            "required": ["wall", "position"],
                        },
                    },
                    "wall_strategies": {
                        "type": "object",
                        "description": (
                            "FALLBACK contract (used only if item_hints is empty/invalid). "
                            "wall_name → list of POSITION-ONLY strings from the semantic "
                            "vocabulary. NEVER prefix with item names."
                        ),
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
                    "item_hints",
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
        effective_family: str,
    ) -> ZonePlannerOutput:
        """Convert raw tool output to ZonePlannerOutput; attach score attr.

        The variant DTO is always stamped with the capacity-resolved
        `effective_family`, regardless of what the model put in `room_shape`.
        """
        room_shape = effective_family
        plan = ZonePlannerOutput(
            variant_id=variant_id,
            family=room_shape,
            wall_strategies={k: list(v) for k, v in (data.get("wall_strategies") or {}).items()},
            zone_assignments=dict(data.get("zone_assignments") or {}),
            item_hints=self._sanitise_item_hints(data.get("item_hints") or {}),
            work_triangle_priority=bool(data.get("work_triangle_priority", True)),
            adjacency_hints=list(data.get("adjacency_hints") or []),
            avoid_zones=list(data.get("avoid_zones") or []),
            notes=str(data.get("notes") or ""),
        )
        # Temporary attr for retry score check — not part of DTO contract
        plan.__dict__["_self_score"] = float(data.get("self_assessment_score", 1.0))
        return plan

    # Item types we will accept in item_hints; anything else is dropped
    _VALID_ITEM_TYPES: tuple[str, ...] = (
        "fridge",
        "sink",
        "dishwasher",
        "stove",
        "hood",
        "oven",
        "microwave",
        "tall_cabinet",
    )

    # Corner terms allowed for fridge
    _CORNER_TERMS: tuple[str, ...] = (
        "at north-west corner",
        "at north-east corner",
        "at south-west corner",
        "at south-east corner",
    )

    def _sanitise_item_hints(self, raw: dict[str, Any]) -> dict[str, dict[str, str]]:
        """Drop hints with invalid item types, missing fields, or numeric positions.

        Cross-item consistency (dishwasher.wall == sink.wall, hood.wall == stove.wall)
        is enforced here too — bad hints are dropped, not silently passed through.
        """
        if not isinstance(raw, dict):
            return {}
        clean: dict[str, dict[str, str]] = {}
        digit_re = re.compile(r"\d")
        for item_type, payload in raw.items():
            key = str(item_type).strip().lower()
            if key not in self._VALID_ITEM_TYPES:
                continue
            if not isinstance(payload, dict):
                continue
            wall = str(payload.get("wall") or "").strip()
            position = str(payload.get("position") or "").strip().lower()
            if not wall or not position:
                continue
            if digit_re.search(position):
                logger.info("Dropping %s hint — numeric position: %r", key, position)
                continue
            clean[key] = {"wall": wall, "position": position}

        # Cross-item consistency
        sink = clean.get("sink")
        if "dishwasher" in clean and sink and clean["dishwasher"]["wall"] != sink["wall"]:
            logger.info("Dropping dishwasher hint — wall != sink.wall")
            clean.pop("dishwasher")
        stove = clean.get("stove")
        if "hood" in clean and stove and clean["hood"]["wall"] != stove["wall"]:
            logger.info("Dropping hood hint — wall != stove.wall")
            clean.pop("hood")

        # Fridge must use a corner term — drop if not
        fridge = clean.get("fridge")
        if fridge and fridge["position"] not in self._CORNER_TERMS:
            logger.info("Dropping fridge hint — non-corner position %r", fridge["position"])
            clean.pop("fridge")

        return clean

    def _validate_terms(self, plan: ZonePlannerOutput) -> ZonePlannerOutput:
        """Replace invalid semantic terms with fallback; log each replacement.

        Tries stripping a leading item/zone name (e.g. 'sink centre of east_wall'
        → 'centre of east_wall') before falling back to the default term.
        """
        validated: dict[str, list[str]] = {}
        for wall, strategies in plan.wall_strategies.items():
            clean: list[str] = []
            for term in strategies:
                if self._is_valid_term(term):
                    clean.append(term)
                    continue
                # Attempt to strip item/zone name prefix and re-validate
                stripped = self._strip_item_prefix(term)
                if stripped != term.strip() and self._is_valid_term(stripped):
                    logger.info(
                        "Stripped item prefix: '%s' → '%s' on wall '%s'",
                        term,
                        stripped,
                        wall,
                    )
                    clean.append(stripped)
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

    def _strip_item_prefix(self, term: str) -> str:
        """Remove a leading item/zone keyword from a compound term.

        The model sometimes prepends the item name to the position term, e.g.:
        'fridge at north-west corner' → 'at north-west corner'
        'sink centre of east_wall'   → 'centre of east_wall'
        """
        t = term.strip()
        for prefix in _ITEM_STRIP_PREFIXES:
            if t.lower().startswith(prefix):
                return t[len(prefix) :].strip()
        return t

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

    def _effective_family(
        self,
        variant_index: int,
        intent: IntentDTO,
        spatial: SpatialEngineOutput,
    ) -> str:
        """Resolve the layout family for this variant, given capacity.

        Mode A (user specified): keep user's family if capacity supports it;
        otherwise fall back to the highest supported family and log
        TYPOLOGY-UNAVAILABLE.

        Mode B (auto): pick a per-slot family from the capacity-restricted map,
        so U is never emitted unless the room actually has 3 cabinet walls.
        """
        capacity = (spatial.layout_capacity or "I").upper()
        cap_walls = _FAMILY_WALLS.get(capacity, 1)

        if intent.layout_family:
            requested = intent.layout_family.upper()
            if _FAMILY_WALLS.get(requested, 1) <= cap_walls:
                return requested
            fallback = "L" if cap_walls >= 2 else "I"
            logger.warning(
                "TYPOLOGY-UNAVAILABLE: requested %s, capacity %s (%d walls) — fallback %s",
                requested,
                capacity,
                cap_walls,
                fallback,
            )
            return fallback

        if capacity == "U":
            return MODE_B_SHAPES.get(variant_index, "L")
        if capacity == "L":
            return MODE_B_SHAPES_CAPACITY_L.get(variant_index, "L")
        return MODE_B_SHAPES_CAPACITY_I.get(variant_index, "I")

    def _fallback_plan(self, variant_id: str, effective_family: str) -> ZonePlannerOutput:
        """Return a minimal valid plan on API failure."""
        return ZonePlannerOutput(
            variant_id=variant_id,
            family=effective_family or SHAPES[0],
            wall_strategies={},
            zone_assignments={},
            work_triangle_priority=True,
            adjacency_hints=[],
            avoid_zones=[],
            notes="Fallback plan — API call failed",
        )
