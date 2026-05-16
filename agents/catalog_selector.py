"""Agent 2: Catalog Selector — Select SKUs from loaded catalog based on intent."""

from __future__ import annotations

import json
from typing import Any

import anthropic

from dtos.contracts import SKU, IntentDTO, PreprocessingOutput, SpatialEngineOutput
from mcp_server.color_resolver import delta_e
from utils.logger import get_logger
from utils.model_selector import for_agent

logger = get_logger(__name__)

# Zone assignment: category/name keyword → zone name
ZONE_CATEGORY_MAP: dict[str, str] = {
    "refrigerator": "cooling",
    "fridge": "cooling",
    "sink": "cleaning",
    "dishwasher": "cleaning",
    "stove": "cooking",
    "range": "cooking",
    "hood": "cooking",
    "oven": "cooking",
    "base_cabinet": "preparation",
    "wall_cabinet": "storage",
    "tall_cabinet": "storage",
}

# Maps special_request keywords to catalog category keywords
MUST_HAVE_CATEGORY_MAP: dict[str, str] = {
    "dishwasher": "dishwasher",
    "hood": "hood",
    "fridge": "refrigerator",
    "refrigerator": "refrigerator",
    "sink": "sink",
    "island": "base_cabinet",
    "pantry": "tall_cabinet",
}

# Budget tier adjacency for must-have fallback (tries next tier up)
BUDGET_TIER_FALLBACK: dict[str, str] = {
    "low": "mid",
    "mid": "high",
}

# Zone min-width fallbacks (mm)
FALLBACK_COOLING_WIDTH_MM: float = 600.0
FALLBACK_CLEANING_WIDTH_MM: float = 600.0
FALLBACK_DISHWASHER_WIDTH_MM: float = 600.0
FALLBACK_STOVE_WIDTH_MM: float = 600.0
COOKING_LANDING_AREA_MM: float = 600.0
PREPARATION_MIN_WIDTH_MM: float = 900.0
FALLBACK_STORAGE_WIDTH_MM: float = 1800.0

# Color matching tolerance (CIE76 delta-E)
COLOR_DELTA_E_TOLERANCE: float = 15.0


class CatalogSelector:
    """Select SKUs from a pre-loaded catalog based on design intent."""

    def __init__(self, client: anthropic.Anthropic, mcp_catalog: dict[str, dict[str, Any]]) -> None:
        """Initialise with Anthropic client and already-loaded catalog dict."""
        self.client = client
        self._catalog = mcp_catalog
        self._tools = [self._build_tool_schema()]
        self._system = self._build_system()

    def select(self, intent: IntentDTO, spatial_output: SpatialEngineOutput) -> PreprocessingOutput:
        """Select SKUs and group by zone.

        Returns PreprocessingOutput with intent, skus, zone_groups,
        zone_min_widths, and nkba_constraints.
        Falls back to an empty-selections output on any failure.
        """
        model = for_agent("catalog_selector")

        try:
            filtered = self._filter_catalog(intent)
            summary = self._catalog_summary(filtered)

            response = self.client.messages.create(
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
                tool_choice={"type": "tool", "name": "select_skus"},
                messages=[
                    {
                        "role": "user",
                        "content": self._build_prompt(intent, spatial_output, summary),
                    }
                ],
            )

            tool_block = None
            for block in response.content:
                if block.type == "tool_use" and block.name == "select_skus":
                    tool_block = block
                    break

            if not tool_block:
                logger.warning("No select_skus tool block in response — using fallback")
                return self._fallback_output(intent)

            selected_ids: list[str] = tool_block.input.get("sku_ids", [])
            skus = self._resolve_skus(selected_ids, filtered)
            skus = self._apply_avoid(skus, intent)
            skus = self._ensure_must_have(skus, intent, filtered)
            zone_groups = self._group_by_zone(skus)
            zone_min_widths = self._compute_zone_min_widths(zone_groups)
            nkba_constraints = self._build_nkba_constraints(skus)

            logger.info(
                "Agent 2 selected %d SKUs across %d zones",
                len(skus),
                sum(1 for v in zone_groups.values() if v),
            )
            return PreprocessingOutput(
                intent=intent,
                skus=skus,
                zone_groups=zone_groups,
                zone_min_widths=zone_min_widths,
                nkba_constraints=nkba_constraints,
            )

        except Exception as e:
            logger.error("Agent 2 selection failed: %s — returning fallback", e)
            return self._fallback_output(intent)

    # ------------------------------------------------------------------ #
    # Filtering                                                            #
    # ------------------------------------------------------------------ #

    def _filter_catalog(self, intent: IntentDTO) -> dict[str, dict[str, Any]]:
        """Filter catalog by budget_tier and color proximity."""
        catalog = self._catalog

        # Budget-tier filter
        if intent.budget_tier:
            catalog = {
                sid: d for sid, d in catalog.items() if d.get("price_tier") == intent.budget_tier
            }
            if not catalog:
                logger.warning(
                    "Budget filter '%s' removed all SKUs — reverting",
                    intent.budget_tier,
                )
                catalog = self._catalog

        # Color filter (cabinetry only — appliances always pass through)
        if intent.color_hex:
            catalog = self._apply_color_filter(catalog, intent.color_hex)

        return catalog

    def _apply_color_filter(
        self, catalog: dict[str, dict[str, Any]], color_hex: str
    ) -> dict[str, dict[str, Any]]:
        """Keep only cabinetry within delta-E tolerance; always keep appliances."""
        target = color_hex.lstrip("#")
        cabinetry = {"base_cabinet", "wall_cabinet", "tall_cabinet"}
        filtered: dict[str, dict[str, Any]] = {}
        for sid, d in catalog.items():
            if d.get("category") in cabinetry:
                if delta_e(target, d.get("color", "000000")) <= COLOR_DELTA_E_TOLERANCE:
                    filtered[sid] = d
            else:
                filtered[sid] = d

        if not filtered:
            logger.warning(
                "Color filter (delta-E<=%.0f) removed all cabinetry — reverting",
                COLOR_DELTA_E_TOLERANCE,
            )
            return catalog

        logger.info(
            "Color filter reduced catalog from %d to %d SKUs",
            len(catalog),
            len(filtered),
        )
        return filtered

    # ------------------------------------------------------------------ #
    # Prompt construction                                                  #
    # ------------------------------------------------------------------ #

    def _build_system(self) -> str:
        """Build cached system prompt for SKU selection."""
        return (
            "You are a kitchen cabinet and appliance selector.\n"
            "Given a catalog of available SKUs and the user's design intent, "
            "select the best complete set of SKUs for a kitchen layout.\n\n"
            "Rules:\n"
            "- Select at least one SKU per zone: "
            "cooling, cleaning, cooking, preparation, storage\n"
            "- Prefer SKUs whose style matches the intent style\n"
            "- Never invent SKU IDs — only use IDs from the provided catalog\n"
            "- Respond only via the select_skus tool"
        )

    def _build_prompt(
        self,
        intent: IntentDTO,
        spatial: SpatialEngineOutput,
        catalog_summary: str,
    ) -> str:
        """Build user message with intent, spatial context, and catalog."""
        intent_dict: dict[str, Any] = {
            "color_keyword": intent.color_keyword,
            "color_hex": intent.color_hex,
            "layout_family": intent.layout_family,
            "style": intent.style,
            "cabinet_preference": intent.cabinet_preference,
            "special_requests": intent.special_requests,
            "must_have": intent.must_have,
            "budget_tier": intent.budget_tier,
        }
        return (
            "Select SKUs for this kitchen design.\n\n"
            f"Intent:\n{json.dumps(intent_dict, indent=2)}\n\n"
            f"Room layout capacity: {spatial.layout_capacity}\n\n"
            f"Available SKUs:\n{catalog_summary}"
        )

    def _catalog_summary(self, catalog: dict[str, dict[str, Any]]) -> str:
        """Compact JSON summary of catalog for LLM context."""
        rows = [
            {
                "sku_id": sid,
                "name": d.get("name"),
                "category": d.get("category"),
                "width_mm": d.get("width_mm"),
                "price_tier": d.get("price_tier"),
                "style": d.get("style"),
            }
            for sid, d in catalog.items()
        ]
        return json.dumps(rows, indent=2)

    def _build_tool_schema(self) -> dict[str, Any]:
        """Build select_skus tool schema for structured LLM output."""
        return {
            "name": "select_skus",
            "description": "Select SKU IDs from the catalog for this kitchen layout",
            "input_schema": {
                "type": "object",
                "properties": {
                    "sku_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of sku_id values to include in the layout",
                    }
                },
                "required": ["sku_ids"],
            },
        }

    # ------------------------------------------------------------------ #
    # SKU resolution & post-processing                                    #
    # ------------------------------------------------------------------ #

    def _make_sku(self, sku_id: str, data: dict[str, Any]) -> SKU:
        """Construct a SKU dataclass from a raw catalog dict."""
        return SKU(
            sku_id=sku_id,
            name=data.get("name", sku_id),
            category=data.get("category", ""),
            width_mm=float(data.get("width_mm", 0)),
            depth_mm=float(data.get("depth_mm", 0)),
            height_mm=float(data.get("height_mm", 0)),
            color=data.get("color", "000000"),
            price_tier=data.get("price_tier", "mid"),
            style=data.get("style", []),
            front_clearance_mm=float(data.get("front_clearance_mm", 0)),
            needs_water=bool(data.get("needs_water", False)),
            needs_power=bool(data.get("needs_power", False)),
            must_attach_to=data.get("must_attach_to", ""),
        )

    def _resolve_skus(
        self,
        sku_ids: list[str],
        catalog: dict[str, dict[str, Any]],
    ) -> dict[str, SKU]:
        """Convert LLM-selected IDs to SKU instances, skipping unknowns."""
        skus: dict[str, SKU] = {}
        for sid in sku_ids:
            data = catalog.get(sid)
            if not data:
                logger.warning("SKU '%s' not in catalog — skipping", sid)
                continue
            skus[sid] = self._make_sku(sid, data)
        return skus

    def _apply_avoid(self, skus: dict[str, SKU], intent: IntentDTO) -> dict[str, SKU]:
        """Remove SKUs whose name or category matches any avoid keyword."""
        if not intent.avoid:
            return skus
        filtered: dict[str, SKU] = {}
        for sid, sku in skus.items():
            avoided = any(
                kw.lower() in sku.name.lower() or kw.lower() in sku.category.lower()
                for kw in intent.avoid
            )
            if avoided:
                logger.info("Removing avoided SKU '%s' (%s)", sid, sku.name)
            else:
                filtered[sid] = sku
        return filtered

    def _ensure_must_have(
        self,
        skus: dict[str, SKU],
        intent: IntentDTO,
        filtered_catalog: dict[str, dict[str, Any]],
    ) -> dict[str, SKU]:
        """Guarantee every must_have + special_request category is present.

        Tries filtered catalog first; if not found, falls back to full catalog
        then to the adjacent budget tier.
        """
        requests = list(dict.fromkeys(intent.must_have + intent.special_requests))
        for req in requests:
            mapped = MUST_HAVE_CATEGORY_MAP.get(req.lower(), req.lower())
            if any(mapped in s.category.lower() or mapped in s.name.lower() for s in skus.values()):
                continue

            # Search filtered catalog, then full catalog
            search_order = [filtered_catalog, self._catalog]
            placed = False
            for source in search_order:
                for sid, data in source.items():
                    cat = data.get("category", "").lower()
                    name = data.get("name", "").lower()
                    if mapped in cat or mapped in name:
                        skus[sid] = self._make_sku(sid, data)
                        logger.info("Added must-have SKU '%s' for request '%s'", sid, req)
                        placed = True
                        break
                if placed:
                    break

            if not placed:
                logger.warning(
                    "Must-have '%s' (mapped: '%s') not found in any catalog tier",
                    req,
                    mapped,
                )
        return skus

    # ------------------------------------------------------------------ #
    # Zone grouping & metrics                                              #
    # ------------------------------------------------------------------ #

    def _zone_for_sku(self, sku: SKU) -> str:
        """Map SKU category/name to zone name."""
        combined = f"{sku.category} {sku.name}".lower()
        for keyword, zone in ZONE_CATEGORY_MAP.items():
            if keyword in combined:
                return zone
        return "storage"

    def _group_by_zone(self, skus: dict[str, SKU]) -> dict[str, list[SKU]]:
        """Group selected SKUs by zone."""
        groups: dict[str, list[SKU]] = {
            "cooling": [],
            "cleaning": [],
            "cooking": [],
            "preparation": [],
            "storage": [],
        }
        for sku in skus.values():
            groups.setdefault(self._zone_for_sku(sku), []).append(sku)
        return groups

    def _compute_zone_min_widths(self, zone_groups: dict[str, list[SKU]]) -> dict[str, float]:
        """Compute minimum zone widths from selected SKU dimensions."""
        fridge = next(
            (
                s
                for s in zone_groups.get("cooling", [])
                if "fridge" in s.name.lower() or "refrigerator" in s.name.lower()
            ),
            None,
        )
        sink = next(
            (s for s in zone_groups.get("cleaning", []) if "sink" in s.name.lower()),
            None,
        )
        dishwasher = next(
            (s for s in zone_groups.get("cleaning", []) if "dishwasher" in s.name.lower()),
            None,
        )
        stove = next(
            (
                s
                for s in zone_groups.get("cooking", [])
                if "stove" in s.name.lower() or "range" in s.name.lower()
            ),
            None,
        )
        storage_skus = zone_groups.get("storage", [])

        return {
            "cooling": fridge.width_mm if fridge else FALLBACK_COOLING_WIDTH_MM,
            "cleaning": (sink.width_mm if sink else FALLBACK_CLEANING_WIDTH_MM)
            + (dishwasher.width_mm if dishwasher else FALLBACK_DISHWASHER_WIDTH_MM),
            "cooking": (stove.width_mm if stove else FALLBACK_STOVE_WIDTH_MM)
            + COOKING_LANDING_AREA_MM,
            "preparation": PREPARATION_MIN_WIDTH_MM,
            "storage": (
                sum(s.width_mm for s in storage_skus) if storage_skus else FALLBACK_STORAGE_WIDTH_MM
            ),
        }

    def _build_nkba_constraints(self, skus: dict[str, SKU]) -> dict[str, Any]:
        """Build per-SKU nkba_constraints with front_clearance_mm."""
        return {sid: {"front_clearance_mm": sku.front_clearance_mm} for sid, sku in skus.items()}

    # ------------------------------------------------------------------ #
    # Fallback                                                             #
    # ------------------------------------------------------------------ #

    def _fallback_output(self, intent: IntentDTO) -> PreprocessingOutput:
        """Return valid empty PreprocessingOutput on any failure."""
        return PreprocessingOutput(
            intent=intent,
            skus={},
            zone_groups={
                "cooling": [],
                "cleaning": [],
                "cooking": [],
                "preparation": [],
                "storage": [],
            },
            zone_min_widths={
                "cooling": FALLBACK_COOLING_WIDTH_MM,
                "cleaning": FALLBACK_CLEANING_WIDTH_MM + FALLBACK_DISHWASHER_WIDTH_MM,
                "cooking": FALLBACK_STOVE_WIDTH_MM + COOKING_LANDING_AREA_MM,
                "preparation": PREPARATION_MIN_WIDTH_MM,
                "storage": FALLBACK_STORAGE_WIDTH_MM,
            },
            nkba_constraints={},
        )
