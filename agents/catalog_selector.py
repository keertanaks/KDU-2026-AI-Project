"""Agent 2: Catalog Selector — Select SKUs from loaded catalog based on intent."""

from __future__ import annotations

import json
from typing import Any

import anthropic

from dtos.contracts import SKU, IntentDTO, PreprocessingOutput, SpatialEngineOutput
from mcp_server.color_resolver import delta_e, match_catalog_color, resolve_color_keyword
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
    "cooktop": "cooking",
    "hood": "cooking",
    "oven": "cooking",
    "microwave": "cooking",
    "coffee_machine": "cooking",
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
    "microwave": "microwave",
    "oven": "oven",
    "coffee machine": "coffee_machine",
    "coffee_machine": "coffee_machine",
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

# Baseline kitchen items that MUST exist regardless of what Haiku selected.
# Without these, the work triangle can't form and NKBA-25/LAYOUT-04 always fail.
BASELINE_CATEGORIES: list[str] = ["fridge", "sink", "stove", "hood", "base_cabinet", "wall_cabinet"]

# When checking if a baseline category is already satisfied, also accept these aliases.
# NOTE: "oven" is NOT a stove alias — built-in ovens require a tall cabinet to host them,
# they cannot stand alone. A real cooking surface (stove/range/cooktop) must always exist.
BASELINE_ALIASES: dict[str, list[str]] = {
    "stove": ["range", "cooktop"],
    "fridge": ["refrigerator"],
    "sink": ["sink_single", "sink_double"],
}

MIN_BASE_CABINET_FRONTAGE_MM: float = 4013.0

# Max ratio of total floor-item width to total cabinet wall length.
# Conservative — leaves room for gaps, depth-corner overlap, and imperfect packing.
WALL_CAPACITY_RATIO: float = 0.85

# Standard widths (mm) the Placement Engine needs for tight gap-fill packing.
# At least one base_cabinet of each width is added to the pool regardless of
# whether frontage is already satisfied — Placement Engine decides what fits.
GAP_FILL_WIDTHS: list[float] = [1200.0, 900.0, 750.0, 600.0, 450.0, 300.0]
# Accept a catalog size within this many mm of the target as "close enough".
GAP_FILL_WIDTH_TOLERANCE_MM: float = 100.0


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

        # Detect color substitution before any filtering so the warning is
        # available even if the LLM call or catalog lookup later fails.
        color_warnings: list[str] = self._build_color_warnings(intent)

        try:
            filtered = self._filter_catalog(intent)
            filtered = self._filter_layout_unsuitable(filtered, spatial_output, intent)
            summary = self._catalog_summary(filtered)

            response = self.client.messages.create(
                model=model,
                max_tokens=2048,
                system=[
                    {
                        "type": "text",
                        "text": self._system,
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": f"Available SKUs (pre-filtered by budget and color):\n{summary}",
                        "cache_control": {"type": "ephemeral"},
                    },
                ],
                tools=self._tools,
                tool_choice={"type": "tool", "name": "select_skus"},
                messages=[
                    {
                        "role": "user",
                        "content": self._build_prompt(intent, spatial_output),
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
            skus = self._apply_cabinet_preference(skus, intent)
            skus = self._ensure_must_have(skus, intent, filtered)
            skus = self._ensure_color_match(skus, intent, filtered)
            skus = self._ensure_baseline(skus, intent, filtered, spatial_output)
            skus = self._ensure_wall_corner_cabs(skus, intent, filtered)
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
                color_warnings=color_warnings,
            )

        except Exception as e:
            logger.error("Agent 2 selection failed: %s — returning fallback", e)
            return self._fallback_output(intent, color_warnings=color_warnings)

    # ------------------------------------------------------------------ #
    # Color warning                                                        #
    # ------------------------------------------------------------------ #

    def _build_color_warnings(self, intent: IntentDTO) -> list[str]:
        """Return a warning list if the user's color keyword had no exact match.

        Calls ``resolve_color_keyword()`` to check match quality, then finds the
        nearest catalog SKU so the warning names a real SKU (no invented IDs).
        Returns an empty list when the keyword was an exact match or absent.
        """
        if not intent.color_keyword:
            return []

        resolution = resolve_color_keyword(intent.color_keyword)
        if resolution.exact_match:
            return []

        # Find the best matching catalog SKU for the warning message
        best = match_catalog_color(resolution.hex_code, self._catalog)
        if best:
            sku_id, _ = best
            sku_name = self._catalog[sku_id].get("name", sku_id)
            warning = (
                f"Requested color '{intent.color_keyword}' not available — "
                f"using nearest match: {sku_name} (#{resolution.hex_code}) "
                f"SKU: {sku_id}"
            )
        else:
            warning = (
                f"Requested color '{intent.color_keyword}' not available — "
                f"no catalog color match found; using fallback #{resolution.hex_code}"
            )

        logger.warning("Color substitution: %s", warning)
        return [warning]

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

        # If budget+color left no cabinetry, add color-matching cabs from full catalog
        cabinetry_cats = {"base_cabinet", "wall_cabinet", "tall_cabinet"}
        has_cabs = any(d.get("category") in cabinetry_cats for d in catalog.values())
        if not has_cabs and intent.color_hex:
            target = intent.color_hex.lstrip("#")
            for sid, d in self._catalog.items():
                if (
                    d.get("category") in cabinetry_cats
                    and delta_e(target, d.get("color", "000000")) <= COLOR_DELTA_E_TOLERANCE
                ):
                    catalog[sid] = d
            added = sum(1 for d in catalog.values() if d.get("category") in cabinetry_cats)
            if added:
                logger.info("Added %d color-matching cabinets (cross-budget)", added)

        return catalog

    def _filter_layout_unsuitable(
        self,
        catalog: dict[str, dict[str, Any]],
        spatial: SpatialEngineOutput,
        intent: IntentDTO,
    ) -> dict[str, dict[str, Any]]:
        """Remove SKUs that don't suit the room's layout capacity.

        - Islands need at least 'XL' capacity rooms; remove from L/M rooms unless
          the user explicitly requested one.
        - Built-in ovens need a tall cabinet to host them; without one selected,
          they get dropped during placement. Remove them unless a tall cabinet
          is in the filtered catalog.
        """
        capacity = (spatial.layout_capacity or "L").upper()
        requested = " ".join(intent.must_have + intent.special_requests).lower()

        filtered: dict[str, dict[str, Any]] = {}
        removed_islands = 0
        removed_builtins = 0
        has_tall_cab = any(d.get("category") == "tall_cabinet" for d in catalog.values())
        for sid, d in catalog.items():
            cat = d.get("category", "").lower()
            name = d.get("name", "").lower()
            # Islands: only for large rooms or when explicitly requested
            if cat == "island" and capacity not in ("XL", "L+") and "island" not in requested:
                removed_islands += 1
                continue
            # Built-in ovens require a tall cabinet to host them (microwaves/coffee go
            # into wall-cabinet space, not tall cabs — exclude them from this filter).
            is_oven_builtin = "oven" in name and "built_in" in name
            if is_oven_builtin and not has_tall_cab:
                removed_builtins += 1
                continue
            filtered[sid] = d

        if removed_islands or removed_builtins:
            logger.info(
                "Layout filter: removed %d islands, %d built-ins (capacity=%s)",
                removed_islands,
                removed_builtins,
                capacity,
            )
        return filtered

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
            "- When the catalog has color_set groups (e.g. ivory_white, sage_green): "
            "pick ALL cabinets (base, wall, corner, tall) from the SAME color_set that "
            "best matches the user's color request. Do NOT mix color sets.\n"
            "- Prefer SKUs whose style matches the intent style\n"
            "- For microwave/oven: if user wants countertop, pick placement=counter_top; "
            "if built-in or no preference, pick placement=built_in\n"
            "- Never invent SKU IDs — only use IDs from the provided catalog\n"
            "- Respond only via the select_skus tool"
        )

    def _build_prompt(self, intent: IntentDTO, spatial: SpatialEngineOutput) -> str:
        """Build user message with intent and spatial context."""
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
            f"Room layout capacity: {spatial.layout_capacity}"
        )

    def _catalog_summary(self, catalog: dict[str, dict[str, Any]]) -> str:
        """Compact JSON summary of catalog for LLM context."""
        rows = []
        for sid, d in catalog.items():
            row: dict[str, Any] = {
                "sku_id": sid,
                "name": d.get("name"),
                "category": d.get("category"),
                "width_mm": d.get("width_mm"),
                "price_tier": d.get("price_tier"),
                "style": d.get("style"),
            }
            if d.get("color_set"):
                row["color_set"] = d["color_set"]
            if d.get("placement"):
                row["placement"] = d["placement"]
            rows.append(row)
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
            placement=data.get("placement", ""),
            color_set=data.get("color_set", ""),
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

    def _apply_cabinet_preference(self, skus: dict[str, SKU], intent: IntentDTO) -> dict[str, SKU]:
        """Strip cabinet types the user explicitly excluded via cabinet_preference."""
        pref = intent.cabinet_preference
        if pref == "base_only":
            filtered = {
                sid: s
                for sid, s in skus.items()
                if "wall_cabinet" not in s.category.lower()
                and "tall_cabinet" not in s.category.lower()
            }
            removed = len(skus) - len(filtered)
            if removed:
                logger.info("cabinet_preference=base_only: removed %d wall/tall cabinets", removed)
            return filtered
        return skus

    def _ensure_color_match(
        self,
        skus: dict[str, SKU],
        intent: IntentDTO,
        filtered_catalog: dict[str, dict[str, Any]],
    ) -> dict[str, SKU]:
        """If user specified a color but no cabinet matches, add the closest match.

        Picks one base_cabinet whose color is within tolerance of intent.color_hex.
        Prefers any color-matching cabinet already in the filtered catalog.
        """
        if not intent.color_hex:
            return skus
        target = intent.color_hex.lstrip("#")
        cabinetry = {"base_cabinet", "wall_cabinet", "tall_cabinet"}
        has_color_cab = any(
            s.category in cabinetry
            and delta_e(target, s.color.lstrip("#")) <= COLOR_DELTA_E_TOLERANCE
            for s in skus.values()
        )
        if has_color_cab:
            return skus
        # Find best matching cabinet (prefer base_cabinet, then wall_cabinet) from filtered catalog
        for cat_filter in ("base_cabinet", "wall_cabinet"):
            candidates = [
                (sid, d, delta_e(target, d.get("color", "000000")))
                for sid, d in filtered_catalog.items()
                if d.get("category") == cat_filter
                and "corner" not in d.get("name", "").lower()
                and sid not in skus
            ]
            candidates = [c for c in candidates if c[2] <= COLOR_DELTA_E_TOLERANCE]
            if candidates:
                candidates.sort(key=lambda c: c[2])
                sid, data, de = candidates[0]
                skus[sid] = self._make_sku(sid, data)
                logger.info(
                    "Force-added color-matching %s '%s' (delta-E %.1f)", cat_filter, sid, de
                )
                return skus
        return skus

    def _apply_avoid(self, skus: dict[str, SKU], intent: IntentDTO) -> dict[str, SKU]:
        """Remove SKUs whose name or category matches any avoid keyword.

        Matches both directions: keyword-in-name AND name-words-in-keyword,
        so "double_sink" matches "sink_double" and vice versa.
        """
        if not intent.avoid:
            return skus
        avoid_kw = [a.lower() for a in intent.avoid]
        filtered: dict[str, SKU] = {}
        for sid, sku in skus.items():
            combined = (sku.name + " " + sku.category).lower()
            combined_words = set(combined.replace("_", " ").split())
            avoided = any(
                kw in combined or all(w in combined_words for w in kw.replace("_", " ").split())
                for kw in avoid_kw
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
        # Detect explicit built-in preference from the raw prompt text
        raw_text = " ".join(intent.must_have + intent.special_requests).lower()
        wants_builtin = "built_in" in raw_text or "built-in" in raw_text

        requests = list(dict.fromkeys(intent.must_have + intent.special_requests))
        for req in requests:
            mapped = MUST_HAVE_CATEGORY_MAP.get(req.lower(), req.lower())

            # For microwave/oven: prefer countertop unless the user explicitly asked
            # for built-in. Countertop is the default residential choice — it sits on
            # the worktop and doesn't need a dedicated upper-cabinet slot.
            is_microwave_or_oven = mapped in ("microwave", "oven")
            prefer_countertop = is_microwave_or_oven and not wants_builtin

            # Check if category is already present
            existing = [
                (sid, s)
                for sid, s in skus.items()
                if mapped in s.category.lower() or mapped in s.name.lower()
            ]
            if existing:
                # If we prefer countertop but only have built-in versions, swap them
                if prefer_countertop and not any(s.placement == "counter_top" for _, s in existing):
                    # Remove built-in versions and fall through to counter_top search
                    for sid, _ in existing:
                        del skus[sid]
                        logger.info(
                            "Swapping built-in '%s' for counter_top version (prefer_countertop)",
                            sid,
                        )
                else:
                    continue  # already satisfied

            # Search filtered catalog, then full catalog
            search_order = [filtered_catalog, self._catalog]
            placed = False
            for source in search_order:
                # Two-pass: if countertop preferred, try counter_top first then fallback
                passes = (
                    [
                        {k: v for k, v in source.items() if v.get("placement") == "counter_top"},
                        source,
                    ]
                    if prefer_countertop
                    else [source]
                )
                for src_pass in passes:
                    for sid, data in src_pass.items():
                        cat = data.get("category", "").lower()
                        name = data.get("name", "").lower()
                        if mapped in cat or mapped in name:
                            skus[sid] = self._make_sku(sid, data)
                            logger.info("Added must-have SKU '%s' for request '%s'", sid, req)
                            placed = True
                            break
                    if placed:
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

    def _dominant_color_set(self, skus: dict[str, SKU]) -> str:
        """Return the most-used color_set among selected cabinetry SKUs, or ''."""
        counts: dict[str, int] = {}
        for s in skus.values():
            cs = s.color_set
            if cs:
                counts[cs] = counts.get(cs, 0) + 1
        return max(counts, key=lambda k: counts[k]) if counts else ""

    def _ensure_baseline(
        self,
        skus: dict[str, SKU],
        intent: IntentDTO,
        filtered_catalog: dict[str, dict[str, Any]],
        spatial: SpatialEngineOutput,
    ) -> dict[str, SKU]:
        """Force-add baseline kitchen items missing from Haiku's selection.

        A kitchen without a fridge/sink/stove can't form a work triangle,
        and without base/wall cabinets fails NKBA-25 (countertop frontage).
        After ensuring one of each baseline category, tops up base cabinets
        until total frontage reaches MIN_BASE_CABINET_FRONTAGE_MM (4013mm),
        capped by available wall space.
        """
        avoid_kw = {a.lower() for a in intent.avoid}
        # Honor "base_only" cabinet preference: skip wall/tall cabinets entirely
        if intent.cabinet_preference == "base_only":
            avoid_kw.update({"wall_cabinet", "tall_cabinet"})
            # Also strip any wall/tall cabinets already in skus
            skus = {
                sid: s
                for sid, s in skus.items()
                if "wall_cabinet" not in s.category.lower()
                and "tall_cabinet" not in s.category.lower()
            }
        for category_kw in BASELINE_CATEGORIES:
            if category_kw in avoid_kw:
                continue
            check_kws = [category_kw, *BASELINE_ALIASES.get(category_kw, [])]

            # For wall_cabinet: corner wall cabs don't count — need at least one regular wall cab
            def _is_regular(s: SKU, kws: list[str]) -> bool:
                if not any(kw in s.category.lower() or kw in s.name.lower() for kw in kws):
                    return False
                if category_kw == "wall_cabinet" and "corner" in s.name.lower():
                    return False
                return True

            if any(_is_regular(s, check_kws) for s in skus.values()):
                continue
            placed = False
            for source in (filtered_catalog, self._catalog):
                for sid, data in source.items():
                    cat = data.get("category", "").lower()
                    name = data.get("name", "").lower()
                    if category_kw not in cat and category_kw not in name:
                        continue
                    # Skip SKUs whose name/category matches an avoid keyword
                    combined = name + " " + cat
                    combined_words = set(combined.replace("_", " ").split())
                    if any(
                        kw in combined
                        or all(w in combined_words for w in kw.replace("_", " ").split())
                        for kw in avoid_kw
                    ):
                        continue
                    skus[sid] = self._make_sku(sid, data)
                    logger.info("Added baseline SKU '%s' for category '%s'", sid, category_kw)
                    placed = True
                    break
                if placed:
                    break
            if not placed:
                logger.warning("Baseline category '%s' not found in any catalog", category_kw)

        # Ensure a base corner cabinet is present for multi-wall layouts (L/U)
        # so structural corners are always filled by a dedicated corner cabinet,
        # preventing the fridge from landing at the wall junction.
        corner_kws = ("corner_cabinet", "blind_corner", "base_corner")
        avoid_corner = any(kw in avoid_kw for kw in corner_kws)
        if not avoid_corner and intent.cabinet_preference != "base_only":
            cabinet_walls = [w for w in spatial.walls if w.has_cabinets]
            if len(cabinet_walls) >= 2:
                has_corner_cab = any(
                    any(kw in (s.category + " " + s.name).lower() for kw in corner_kws)
                    for s in skus.values()
                )
                if not has_corner_cab:
                    # Prefer corner cab from the same color_set as selected cabs,
                    # then fall back to closest color by delta-E.
                    dom_set = self._dominant_color_set(skus)
                    target_hex = intent.color_hex.lstrip("#") if intent.color_hex else None
                    best_sid: str | None = None
                    best_data: dict[str, Any] | None = None
                    best_score = float("inf")
                    for source in (filtered_catalog, self._catalog):
                        for sid, data in source.items():
                            if sid in skus:
                                continue
                            n = data.get("name", "").lower()
                            t = data.get("type", "").lower()
                            is_corner = any(kw in n or kw in t for kw in corner_kws)
                            is_wall_corner = "wall_corner" in n or "wall_corner" in t
                            if not is_corner or is_wall_corner:
                                continue
                            # Score: same color_set = 0, otherwise delta-E
                            cs = data.get("color_set", "")
                            if dom_set and cs == dom_set:
                                score = 0.0
                            elif target_hex:
                                score = delta_e(target_hex, data.get("color", "000000"))
                            else:
                                score = 50.0
                            if score < best_score:
                                best_score = score
                                best_sid = sid
                                best_data = data
                    if best_sid and best_data:
                        skus[best_sid] = self._make_sku(best_sid, best_data)
                        logger.info(
                            "Added corner base cabinet '%s' for multi-wall layout (score=%.1f)",
                            best_sid,
                            best_score,
                        )

        # Top up base cabinets until NKBA-25 frontage requirement is met.
        # For I-shape, only ONE wall holds items — capping by sum of all cabinet
        # walls would over-select by 2-3x (since L/U use 2-3 walls). Use the
        # single longest cabinet wall as the basis instead.
        if "base_cabinet" not in avoid_kw:
            cabinet_walls = [w for w in spatial.walls if w.has_cabinets]
            if (intent.layout_family or "").upper() == "I" and cabinet_walls:
                cabinet_wall_length = max(w.length_mm for w in cabinet_walls)
                logger.info(
                    "I-shape detected — capping base cabinet pool by longest wall "
                    "(%.0fmm) not sum of all walls",
                    cabinet_wall_length,
                )
            else:
                cabinet_wall_length = sum(w.length_mm for w in cabinet_walls)
            skus = self._ensure_base_cabinet_frontage(skus, filtered_catalog, cabinet_wall_length)
            # Guarantee a variety of sizes for gap-fill packing — Placement Engine decides fit
            skus = self._ensure_gap_fill_pool(skus, filtered_catalog)

        return skus

    def _ensure_base_cabinet_frontage(
        self,
        skus: dict[str, SKU],
        filtered_catalog: dict[str, dict[str, Any]],
        cabinet_wall_length: float,
    ) -> dict[str, SKU]:
        """Add base cabinets until total frontage >= MIN_BASE_CABINET_FRONTAGE_MM.

        Caps total item width (all SKUs) at 85% of cabinet wall length to
        prevent spillover from overloading walls.
        """
        current = sum(s.width_mm for s in skus.values() if "base_cabinet" in s.category.lower())
        if current >= MIN_BASE_CABINET_FRONTAGE_MM:
            return skus

        floor_kw = (
            "base_cabinet",
            "sink",
            "stove",
            "range",
            "fridge",
            "refrigerator",
            "dishwasher",
            "oven",
            "tall_cabinet",
        )
        floor_width = sum(
            s.width_mm
            for s in skus.values()
            if any(kw in s.category.lower() or kw in s.name.lower() for kw in floor_kw)
        )
        max_floor_width = cabinet_wall_length * WALL_CAPACITY_RATIO

        # Exclude corner cabinets from frontage filling — catalog_loader normalizes
        # corner_cabinet types to category="base_cabinet", but they're STRUCTURAL
        # (must sit at a wall corner). Auto-adding them via frontage causes the
        # placement engine to slam them into the NW corner where the fridge wants
        # to live → collision. Corner cabs should only enter via Agent 2's explicit
        # selection or via must_have. Detect by name (e.g. "corner_cabinet_900").
        dom_set = self._dominant_color_set(skus)
        candidates = sorted(
            [
                (sid, data)
                for source in (filtered_catalog, self._catalog)
                for sid, data in source.items()
                if "base_cabinet" in data.get("category", "").lower()
                and "corner" not in data.get("name", "").lower()
                and "corner" not in data.get("type", "").lower()
                and sid not in skus
            ],
            # Sort: same color_set first, then widest-first within each group
            key=lambda t: (
                0 if (dom_set and t[1].get("color_set", "") == dom_set) else 1,
                -float(t[1].get("width_mm", 0)),
            ),
        )
        seen: set[str] = set()
        for sid, data in candidates:
            if sid in seen:
                continue
            seen.add(sid)
            if current >= MIN_BASE_CABINET_FRONTAGE_MM:
                break
            width = float(data.get("width_mm", 0))
            # Don't overshoot the target by more than half a cabinet
            if current + width > MIN_BASE_CABINET_FRONTAGE_MM + 300.0:
                continue
            if floor_width + width > max_floor_width:
                logger.info(
                    "Skipping base_cabinet '%s' (%.0fmm) — would exceed floor capacity",
                    sid,
                    width,
                )
                continue
            skus[sid] = self._make_sku(sid, data)
            current += width
            floor_width += width
            logger.info(
                "Added base_cabinet '%s' (%.0fmm) — frontage %.0fmm / %.0fmm",
                sid,
                width,
                current,
                MIN_BASE_CABINET_FRONTAGE_MM,
            )
        return skus

    def _ensure_gap_fill_pool(
        self,
        skus: dict[str, SKU],
        filtered_catalog: dict[str, dict[str, Any]],
    ) -> dict[str, SKU]:
        """Ensure at least one base_cabinet of each standard gap-fill width is available.

        Placement Engine needs size variety to pack continuous runs tightly.
        Without small widths (600, 450mm) gaps that fit no existing cabinet
        are left unfilled. Searches filtered catalog first, then full catalog.
        Does NOT check the wall-capacity ratio — Placement Engine decides fit.
        """
        dom_set_gf = self._dominant_color_set(skus)
        for target_w in GAP_FILL_WIDTHS:
            already_have = any(
                "base_cabinet" in s.category.lower()
                and abs(s.width_mm - target_w) <= GAP_FILL_WIDTH_TOLERANCE_MM
                for s in skus.values()
            )
            if already_have:
                continue
            best_sid: str | None = None
            best_data: dict[str, Any] | None = None
            best_score = float("inf")
            for source in (filtered_catalog, self._catalog):
                for sid, data in source.items():
                    if "base_cabinet" not in data.get("category", "").lower():
                        continue
                    # Skip corner cabs — they're structural, not gap-fillers.
                    name_lower = data.get("name", "").lower()
                    type_lower = data.get("type", "").lower()
                    if "corner" in name_lower or "corner" in type_lower:
                        continue
                    if sid in skus:
                        continue
                    delta = abs(float(data.get("width_mm", 0)) - target_w)
                    if delta > GAP_FILL_WIDTH_TOLERANCE_MM:
                        continue
                    # Score: same color_set = delta; other sets = delta + 1000
                    cs = data.get("color_set", "")
                    score = delta if (dom_set_gf and cs == dom_set_gf) else delta + 1000.0
                    if score < best_score:
                        best_score = score
                        best_sid = sid
                        best_data = data
                if best_sid and best_score < 500.0:  # found a same-set match
                    break
            if best_sid and best_data:
                skus[best_sid] = self._make_sku(best_sid, best_data)
                logger.info(
                    "GAP-FILL-POOL: added '%s' (%.0fmm) for %.0fmm target",
                    best_sid,
                    float(best_data.get("width_mm", 0)),
                    target_w,
                )
        return skus

    def _ensure_wall_corner_cabs(
        self,
        skus: dict[str, SKU],
        intent: IntentDTO,
        filtered_catalog: dict[str, dict[str, Any]],
    ) -> dict[str, SKU]:
        """Add wall corner cabs when base corner cabs are selected and wall cabs allowed.

        Picks a wall_corner SKU in the same color as selected cabinets so the
        upper corner row is visually consistent with the rest of the wall run.
        """
        if intent.cabinet_preference == "base_only":
            return skus

        base_corner_kws = ("corner_cabinet", "blind_corner", "base_corner")
        has_base_corner = any(
            any(kw in (s.category + " " + s.name).lower() for kw in base_corner_kws)
            for s in skus.values()
        )
        if not has_base_corner:
            return skus

        has_wall_corner = any(
            "wall_corner" in (s.category + " " + s.name).lower() for s in skus.values()
        )
        if has_wall_corner:
            return skus

        target = intent.color_hex.lstrip("#") if intent.color_hex else None
        dom_set_wc = self._dominant_color_set(skus)
        best_sid: str | None = None
        best_data: dict[str, Any] | None = None
        best_score = float("inf")

        for source in (filtered_catalog, self._catalog):
            for sid, data in source.items():
                if sid in skus:
                    continue
                name_lower = data.get("name", "").lower()
                type_lower = data.get("type", "").lower()
                if "wall_corner" not in name_lower and "wall_corner" not in type_lower:
                    continue
                cs = data.get("color_set", "")
                if dom_set_wc and cs == dom_set_wc:
                    score = 0.0
                elif target:
                    score = delta_e(target, data.get("color", "000000"))
                else:
                    score = 50.0
                if score < best_score:
                    best_score = score
                    best_sid = sid
                    best_data = data
            if best_sid and best_score == 0.0:
                break  # same-color-set match found — no need to search further

        if best_sid and best_data:
            skus[best_sid] = self._make_sku(best_sid, best_data)
            logger.info("Added wall corner cab '%s' to pair with base corner", best_sid)
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

    def _fallback_output(
        self,
        intent: IntentDTO,
        color_warnings: list[str] | None = None,
    ) -> PreprocessingOutput:
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
            color_warnings=color_warnings or [],
        )
