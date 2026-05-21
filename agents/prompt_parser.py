"""Agent 1: Prompt Parser — extract structured kitchen intent from user input.

Converts free-form user prompts into structured IntentDTO with color,
layout, style, and cabinet preferences. Always returns valid DTO — never fails.
"""

from __future__ import annotations

import re
from typing import Any

import anthropic

from dtos.contracts import IntentDTO
from utils.logger import get_logger
from utils.model_selector import for_agent

logger = get_logger(__name__)

# Hex values taken directly from catalog.json — keeps color matching accurate
COLOR_KEYWORD_HEX: dict[str, str] = {
    "matte white": "#EDEDE9",
    "shaker white": "#E8E2D5",
    "off white": "#F5F0E8",
    "off-white": "#F5F0E8",
    "warm white": "#FAF8F5",
    "warm-white": "#FAF8F5",
    "navy blue": "#1F3A5F",
    "navy": "#1F3A5F",
    "oak": "#D4A574",
    "maple": "#C8A878",
    "walnut": "#6F4E37",
    "cream": "#F5E6CA",
    "forest green": "#2F5233",
    "sage green": "#9CAF88",
    "sage": "#9CAF88",
    "terracotta": "#C76A4A",
    "espresso": "#4A3328",
    "birch": "#DBC59A",
    "charcoal": "#3D3D3D",
    "stainless steel": "#BFC1C2",
    "stainless": "#BFC1C2",
    "graphite": "#2A2A2A",
    "brushed steel": "#B8BABC",
    "chrome": "#D6D8DA",
    "composite black": "#2F2F2F",
    "matte black": "#2E2E2E",
    "soft gray": "#B0B8BE",
    "soft grey": "#B0B8BE",
    "white": "#FFFFFF",
    "black": "#1A1A1A",
    "grey": "#9CA3AF",
    "gray": "#9CA3AF",
}

STYLE_WORDS: tuple[str, ...] = (
    "modern",
    "contemporary",
    "traditional",
    "classic",
    "minimalist",
    "rustic",
    "farmhouse",
    "industrial",
    "scandinavian",
    "shaker",
)

NON_KITCHEN_WORDS: tuple[str, ...] = (
    "ac",
    "air conditioner",
    "tv",
    "sofa",
    "couch",
    "bed",
    "lighting",
)


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

        # Run deterministic extraction first — this is the ground truth for critical fields
        deterministic = self._deterministic_extract(prompt)

        try:
            model = for_agent("prompt_parser")
            logger.debug("Parsing prompt with %s", model)

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

            tool_use = None
            for block in message.content:
                if block.type == "tool_use":
                    tool_use = block
                    break

            if not tool_use:
                logger.warning("No tool_use block — using deterministic result")
                return self._merge_with_preferences(deterministic, preferences)

            # Merge: deterministic values override LLM for critical fields
            extracted = self._merge_extracted(tool_use.input, deterministic)
            return self._merge_with_preferences(extracted, preferences)

        except Exception as e:
            logger.error("Agent 1 API failed: %s — using deterministic result", e)
            return self._merge_with_preferences(deterministic, preferences)

    def _build_system(self) -> str:
        """Build system prompt for intent extraction."""
        return (
            "You are Agent 1 — Kitchen Design Intent Extractor for an AI kitchen layout system.\n"
            "Your ONLY job: read the user's free-text prompt and extract structured fields.\n"
            "NEVER fail. NEVER refuse. ALWAYS call extract_intent with best-effort values.\n"
            "If a field is not mentioned in the prompt, return null for that field.\n\n"
            # ── FIELD RULES ───────────────────────────────────────────────
            "FIELD EXTRACTION RULES:\n\n"
            "1. COLOR\n"
            "   Extract the color word/phrase the user mentioned (color_keyword).\n"
            "   Then resolve it to a hex code (color_hex) using this reference table\n"
            "   (values match the product catalog exactly):\n"
            "   white=#FFFFFF      matte-white=#EDEDE9  shaker-white=#E8E2D5\n"
            "   off-white=#F5F0E8  warm-white=#FAF8F5   cream=#F5E6CA\n"
            "   soft-grey=#B0B8BE  grey=#9CA3AF         charcoal=#3D3D3D\n"
            "   graphite=#2A2A2A   matte-black=#2E2E2E  composite-black=#2F2F2F  black=#1A1A1A\n"
            "   oak=#D4A574        maple=#C8A878        birch=#DBC59A\n"
            "   walnut=#6F4E37     espresso=#4A3328\n"
            "   stainless=#BFC1C2  stainless-steel=#BFC1C2  brushed-steel=#B8BABC  chrome=#D6D8DA\n"
            "   navy=#1F3A5F       navy-blue=#1F3A5F\n"
            "   forest-green=#2F5233  sage=#9CAF88  sage-green=#9CAF88\n"
            "   terracotta=#C76A4A\n"
            "   If the color is not in this table, use your knowledge to estimate the hex.\n"
            "   Always include the # prefix in color_hex (e.g. #1F3A5F not 1F3A5F).\n"
            "   If no color is mentioned → set both color_keyword and color_hex to null.\n\n"
            "2. LAYOUT FAMILY\n"
            "   ONLY set layout_family if the user explicitly names a kitchen shape.\n"
            "   These exact words map to these values:\n"
            "     L-shape / L shape / two walls / corner kitchen       → 'L'\n"
            "     U-shape / U shape / three walls / horseshoe          → 'U'\n"
            "     single wall / one wall / galley / straight / I-shape → 'I'\n"
            "   If the user mentions 'island': set layout_family to null and add 'island'\n"
            "   to special_requests — island is a feature, not a layout shape.\n"
            "   If the user does NOT mention a shape → set layout_family to null.\n"
            "   (null means the system will auto-generate L, U, and I variants — this is correct.)\n"
            "   NEVER infer a shape from style words like 'modern' or 'compact'.\n\n"
            "3. STYLE\n"
            "   Capture any aesthetic/design style words: modern, contemporary, traditional,\n"
            "   classic, minimalist, rustic, farmhouse, industrial, Scandinavian, shaker, etc.\n"
            "   Use lowercase. If multiple styles → pick the strongest one. Null if not mentioned.\n\n"
            "4. BUDGET TIER\n"
            "   Map budget words to: low, mid, high, premium.\n"
            "     cheap / affordable / budget / economy → 'low'\n"
            "     mid-range / standard / reasonable     → 'mid'\n"
            "     high-end / quality / expensive        → 'high'\n"
            "     luxury / premium / bespoke / top      → 'premium'\n"
            "   Null if not mentioned.\n\n"
            "5. CABINET PREFERENCE\n"
            "   ONLY set if user explicitly states a cabinet configuration:\n"
            "     'base cabinets only' / 'no wall cabinets' / 'open shelving only' → 'base_only'\n"
            "     'with wall cabinets' / 'upper cabinets' / 'with uppers'          → 'with_uppers'\n"
            "     'with tall cabinets' / 'with pantry' / 'floor to ceiling'        → 'with_tall'\n"
            "   Null if not explicitly stated.\n\n"
            "6. SPECIAL REQUESTS\n"
            "   Capture any kitchen feature requests as a list of short phrases:\n"
            "   island, breakfast bar, pantry, wine fridge, double oven, extra storage,\n"
            "   open shelving, microwave, pot filler, coffee station, walk-in pantry, etc.\n"
            "   Empty array [] if none mentioned.\n\n"
            "7. MUST_HAVE and AVOID\n"
            "   Do NOT extract these from the prompt. Always return empty arrays [].\n"
            "   (They are loaded separately from the input JSON preferences.)\n\n"
            "8. IGNORED\n"
            "   If the prompt contains non-kitchen requests (AC, TV, sofa, lighting, etc.),\n"
            "   list them here so the system can inform the user. Empty array [] if none.\n\n"
            # ── FEW-SHOT EXAMPLES ─────────────────────────────────────────
            "EXAMPLES:\n\n"
            'Prompt: "I want a modern navy blue L-shaped kitchen with an island"\n'
            "→ color_keyword='navy blue'  color_hex='#1F3A5F'  layout_family='L'\n"
            "   style='modern'  special_requests=['island']  budget_tier=null\n\n"
            'Prompt: "Give me a cheap galley kitchen, white cabinets, no frills"\n'
            "→ color_keyword='white'  color_hex='#FFFFFF'  layout_family='I'\n"
            "   style=null  cabinet_preference='base_only'  budget_tier='low'\n\n"
            'Prompt: "Traditional oak kitchen, I also want AC and good lighting"\n'
            "→ color_keyword='oak'  color_hex='#C8A878'  layout_family=null\n"
            "   style='traditional'  ignored=['AC', 'lighting']  budget_tier=null\n\n"
            'Prompt: "Something premium and minimalist, floor-to-ceiling cabinets"\n'
            "→ color_keyword=null  color_hex=null  layout_family=null\n"
            "   style='minimalist'  cabinet_preference='with_tall'  budget_tier='premium'\n\n"
            "Always call extract_intent with ALL required fields."
        )

    def _build_tool_schema(self) -> dict[str, Any]:
        """Build tool schema for structured extraction."""
        return {
            "name": "extract_intent",
            "description": (
                "Extract all kitchen design intent from the user prompt. "
                "Call this with every field filled — use null for anything not mentioned."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "color_keyword": {
                        "type": ["string", "null"],
                        "description": (
                            "The exact color word/phrase from the prompt, e.g. 'navy blue', "
                            "'sage green', 'walnut'. Null if no color mentioned."
                        ),
                    },
                    "color_hex": {
                        "type": ["string", "null"],
                        "description": (
                            "Hex code for color_keyword. MUST include # prefix, e.g. '#1F3A5F'. "
                            "Use the color reference table in your instructions. "
                            "Null if color_keyword is null."
                        ),
                    },
                    "layout_family": {
                        "type": ["string", "null"],
                        "enum": ["L", "U", "I", None],
                        "description": (
                            "Kitchen layout shape — ONLY if user explicitly mentions one. "
                            "L=two adjacent walls (L-shape, corner). "
                            "U=three walls (U-shape, horseshoe). "
                            "I=single wall run (galley, one-wall, straight). "
                            "NULL if user does not mention a shape — do NOT infer from style. "
                            "If user mentions 'island', set this to null and add 'island' to special_requests."
                        ),
                    },
                    "style": {
                        "type": ["string", "null"],
                        "description": (
                            "Aesthetic style if mentioned: modern, contemporary, traditional, "
                            "classic, minimalist, rustic, farmhouse, industrial, Scandinavian, "
                            "shaker. Lowercase. Null if not mentioned."
                        ),
                    },
                    "cabinet_preference": {
                        "type": ["string", "null"],
                        "enum": ["base_only", "with_uppers", "with_tall", None],
                        "description": (
                            "Cabinet configuration ONLY if explicitly stated. "
                            "base_only=base cabinets only, no wall/tall. "
                            "with_uppers=base + wall cabinets. "
                            "with_tall=includes tall cabinets or pantry. "
                            "Null if not stated."
                        ),
                    },
                    "special_requests": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Kitchen feature requests as short phrases. "
                            "Examples: 'island', 'breakfast bar', 'pantry', 'wine fridge', "
                            "'double oven', 'extra storage', 'open shelving', 'coffee station'. "
                            "Empty array if none."
                        ),
                    },
                    "ignored": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Non-kitchen requests found in the prompt, e.g. 'AC', 'TV', "
                            "'sofa', 'lighting'. Empty array if none."
                        ),
                    },
                    "budget_tier": {
                        "type": ["string", "null"],
                        "enum": ["low", "mid", "high", "premium", None],
                        "description": (
                            "Budget level if mentioned. "
                            "low=cheap/budget/economy. mid=standard/mid-range. "
                            "high=high-end/quality. premium=luxury/bespoke. "
                            "Null if not mentioned."
                        ),
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

    # Aliases that must map to canonical SHAPES values
    _FAMILY_ALIASES: dict[str, str] = {
        "one_wall": "I",
        "galley": "I",
        "single_wall": "I",
        "straight": "I",
    }

    def _merge_with_preferences(
        self, extracted: dict[str, Any], preferences: dict[str, Any]
    ) -> IntentDTO:
        """Merge extracted intent with preferences fallback."""
        raw_family = extracted.get("layout_family")
        layout_family = self._FAMILY_ALIASES.get(raw_family or "", raw_family)

        # Normalise color_hex: ensure # prefix, uppercase
        raw_hex = extracted.get("color_hex")
        if raw_hex:
            raw_hex = raw_hex.strip()
            if not raw_hex.startswith("#"):
                raw_hex = f"#{raw_hex}"
            raw_hex = raw_hex.upper()

        return IntentDTO(
            color_keyword=extracted.get("color_keyword"),
            color_hex=raw_hex,
            layout_family=layout_family,
            style=extracted.get("style") or preferences.get("style"),
            cabinet_preference=extracted.get("cabinet_preference"),
            special_requests=(extracted.get("special_requests") or []),
            ignored=extracted.get("ignored", []),
            budget_tier=extracted.get("budget_tier") or preferences.get("budget_tier"),
            must_have=preferences.get("must_have", []),
            avoid=preferences.get("avoid", []),
        )

    def _deterministic_extract(self, prompt: str) -> dict[str, Any]:
        """Pure-code extraction — no LLM. Used as ground truth for critical fields."""
        text = prompt.lower().replace("-", " ")
        compact = re.sub(r"\s+", " ", text).strip()

        # Color — try hex literal first, then keyword table (longest match first)
        color_keyword: str | None = None
        color_hex: str | None = None
        hex_match = re.search(r"#[0-9a-fA-F]{6}\b", prompt)
        if hex_match:
            color_keyword = hex_match.group(0)
            color_hex = hex_match.group(0).upper()
        else:
            for kw in sorted(COLOR_KEYWORD_HEX, key=len, reverse=True):
                if re.search(rf"\b{re.escape(kw.replace('-', ' '))}\b", compact):
                    color_keyword = kw
                    color_hex = COLOR_KEYWORD_HEX[kw]
                    break

        # Layout family — only explicit shape words; island → special_requests
        layout_family: str | None = None
        if re.search(r"\b(l shape|l shaped|l kitchen|two walls|corner kitchen)\b", compact):
            layout_family = "L"
        elif re.search(r"\b(u shape|u shaped|u kitchen|three walls|horseshoe)\b", compact):
            layout_family = "U"
        elif re.search(r"\b(single wall|one wall|galley|straight|i shape|i shaped)\b", compact):
            layout_family = "I"

        # Style
        style = next((w for w in STYLE_WORDS if re.search(rf"\b{w}\b", compact)), None)

        # Budget
        budget_tier: str | None = None
        if re.search(r"\b(cheap|affordable|budget|economy)\b", compact):
            budget_tier = "low"
        elif re.search(r"\b(mid range|standard|reasonable)\b", compact):
            budget_tier = "mid"
        elif re.search(r"\b(high end|quality|expensive)\b", compact):
            budget_tier = "high"
        elif re.search(r"\b(luxury|premium|bespoke|top)\b", compact):
            budget_tier = "premium"

        # Cabinet preference
        cabinet_preference: str | None = None
        if re.search(
            r"\b(base cabinets only|only base cabinets|no wall cabinets|no uppers|open shelving only)\b",
            compact,
        ):
            cabinet_preference = "base_only"
        elif re.search(
            r"\b(with wall cabinets|wall cabinets|upper cabinets|with uppers)\b", compact
        ):
            cabinet_preference = "with_uppers"
        elif re.search(
            r"\b(with tall cabinets|tall cabinets|with pantry|pantry cabinet|floor to ceiling)\b",
            compact,
        ):
            cabinet_preference = "with_tall"

        # Special requests
        special_kws = [
            "island",
            "breakfast bar",
            "pantry",
            "wine fridge",
            "double oven",
            "extra storage",
            "open shelving",
            "microwave",
            "pot filler",
            "coffee station",
            "walk in pantry",
        ]
        special_requests = [
            kw
            for kw in special_kws
            if re.search(rf"\b{re.escape(kw.replace('-', ' '))}\b", compact)
        ]

        # Ignored (non-kitchen)
        ignored = [
            kw.upper() if kw == "ac" else kw
            for kw in NON_KITCHEN_WORDS
            if re.search(rf"\b{re.escape(kw)}\b", compact)
        ]

        return {
            "color_keyword": color_keyword,
            "color_hex": color_hex,
            "layout_family": layout_family,
            "style": style,
            "cabinet_preference": cabinet_preference,
            "special_requests": special_requests,
            "ignored": ignored,
            "budget_tier": budget_tier,
        }

    def _merge_extracted(
        self, llm_result: dict[str, Any], deterministic: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge LLM output with deterministic result.

        Deterministic overrides LLM for critical scalar fields — prevents hallucinations
        on layout_family and color_hex which caused bugs earlier.
        LLM output is trusted for richer list fields (special_requests, ignored).
        """
        merged = dict(llm_result or {})

        for key in (
            "color_keyword",
            "color_hex",
            "style",
            "cabinet_preference",
            "budget_tier",
        ):
            if deterministic.get(key) is not None:
                merged[key] = deterministic[key]

        # layout_family: deterministic always wins — it uses explicit keyword matching;
        # LLM may hallucinate a shape when none was mentioned, which collapses all
        # variants into Mode A (same shape). If user said no shape, None is correct.
        merged["layout_family"] = deterministic.get("layout_family")

        for key in ("special_requests", "ignored"):
            seen: list[str] = []
            for item in (merged.get(key) or []) + (deterministic.get(key) or []):
                if item not in seen:
                    seen.append(item)
            merged[key] = seen

        merged["must_have"] = []
        merged["avoid"] = []
        return merged

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
