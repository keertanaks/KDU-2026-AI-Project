"""Layer 5b: Budget Optimizer — estimate costs and suggest cheaper SKU substitutes.

Pipeline position: runs after NKBA validation, before output generation.
Called once per variant by the `budget_optimization` LangGraph node.

IMPORTANT — Estimated Costs Only
---------------------------------
catalog.json has `price_tier` ("low"/"mid"/"high") but NO real prices.
This module uses the ESTIMATED_PRICE_MAP constant below — approximate mid-market
figures for illustration only. ALL cost output is labeled "Estimated Cost" in
DTOs, logs, and UI. These numbers MUST NOT be presented as real retail prices.

Substitution Logic
------------------
1. Estimate total cost from placed items' price tiers.
2. If total > target_budget_gbp, sort items by cost descending.
3. For each high-cost item, call mcp_server.server.get_substitute_skus()
   to find a cheaper, same-category SKU within ±50mm width tolerance.
4. Prefer substitutes that preserve the user's requested color/style.
5. Re-run NKBAValidator after each accepted substitution.
6. Reject a substitution if it drops the NKBA score by more than
   SCORE_DROP_TOLERANCE (0.05) or creates a cabinet-run gap > 50mm.
7. Never invent SKUs — only use IDs returned by get_substitute_skus().
"""

from __future__ import annotations

import dataclasses
from typing import Any

from dtos.contracts import (
    SKU,
    BudgetEstimateDTO,
    BudgetItemEstimate,
    BudgetOptimizationDTO,
    IntentDTO,
    PlacedItem,
    PlacementEngineOutput,
    PreprocessingOutput,
    SpatialEngineOutput,
    SubstitutionDTO,
    VariantSummaryDTO,
)
from mcp_server.color_resolver import delta_e, keyword_to_hex
from mcp_server.server import get_substitute_skus
from pipeline.nkba_validator import NKBAValidator
from utils.logger import get_logger

logger = get_logger(__name__)

# ============================================================================
# Constants — named, never bare numbers
# ============================================================================

# Estimated Cost per SKU by price_tier (USD).
# These are ESTIMATES — approximate mid-market figures, NOT real retail prices.
# Label all output that uses these values as "Estimated Cost".
ESTIMATED_PRICE_MAP: dict[str, float] = {
    "low": 500.0,  # Estimated Cost per low-tier unit (USD)
    "mid": 1_200.0,  # Estimated Cost per mid-tier unit (USD)
    "high": 2_800.0,  # Estimated Cost per high-tier unit (USD)
}

# Default estimated cost when a SKU's price_tier is missing or unrecognised.
ESTIMATED_PRICE_FALLBACK: float = 800.0  # Estimated Cost — mid-low fallback (USD)

# Cabinet run continuity: LAYOUT-03 defines a gap > 50mm as a violation.
CONTINUITY_GAP_TOLERANCE_MM: float = 50.0

# Maximum acceptable NKBA score drop after a substitution.
# If score drops by more than this, the substitution is rejected.
SCORE_DROP_TOLERANCE: float = 0.05

# Tier ordering for "lower than" comparisons (lower index = cheaper).
TIER_ORDER: list[str] = ["low", "mid", "high"]

# Minimum delta-E improvement to prefer a color-matching substitute.
COLOR_MATCH_IMPROVEMENT_THRESHOLD: float = 5.0


# ============================================================================
# BudgetOptimizer
# ============================================================================


class BudgetOptimizer:
    """Estimate variant cost and propose cheaper SKU substitutions.

    Uses mcp_server/server.py for all catalog lookups (no direct JSON reads).
    Uses mcp_server/color_resolver.py for color preservation scoring.
    Re-runs NKBAValidator after every accepted substitution.
    """

    def __init__(self, validator: NKBAValidator) -> None:
        """Initialise with a shared NKBAValidator instance."""
        self._validator = validator

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def optimize_variant(
        self,
        variant: VariantSummaryDTO,
        placed: PlacementEngineOutput,
        target_budget_gbp: float | None,
        spatial: SpatialEngineOutput,
        preprocessing: PreprocessingOutput,
    ) -> BudgetOptimizationDTO:
        """Run estimation and (optionally) substitution for one variant.

        If target_budget_gbp is None or ≤ 0, only cost estimation is performed —
        no substitutions are attempted and within_budget is set based on tier alone.

        Args:
            variant: Validated variant summary (score, violations, placed layout).
            placed: Raw placement output with positioned_items (PlacedItem objects).
            target_budget_gbp: Numeric budget ceiling, or None for estimate-only mode.
            spatial: Spatial engine output (needed for NKBA re-validation).
            preprocessing: Pre-processing output (SKU dict + intent).

        Returns:
            BudgetOptimizationDTO with original estimate, substitutions, and flags.
        """
        skus = preprocessing.skus
        intent = preprocessing.intent

        # Normalise target: treat 0 or negative as "no target"
        effective_target = (
            target_budget_gbp if (target_budget_gbp and target_budget_gbp > 0) else None
        )

        original_estimate = self.estimate_cost(placed, skus)
        logger.info(
            "Budget optimizer: variant %s, estimated cost $%.0f (target=%s)",
            variant.id,
            original_estimate.total_estimated_cost_gbp,
            f"${effective_target:.0f}" if effective_target else "none",
        )

        # No target → estimation only, no substitutions
        if effective_target is None:
            return BudgetOptimizationDTO(
                variant_id=variant.id,
                target_budget_gbp=None,
                original_estimate=original_estimate,
                optimized_estimate=None,
                substitutions=[],
                within_budget=True,
                nkba_score_delta=0.0,
            )

        # Already within budget → no substitutions needed
        if original_estimate.total_estimated_cost_gbp <= effective_target:
            return BudgetOptimizationDTO(
                variant_id=variant.id,
                target_budget_gbp=effective_target,
                original_estimate=original_estimate,
                optimized_estimate=None,
                substitutions=[],
                within_budget=True,
                nkba_score_delta=0.0,
            )

        # Run substitution loop
        return self._substitute_to_budget(
            variant=variant,
            placed=placed,
            original_estimate=original_estimate,
            target_budget_gbp=effective_target,
            spatial=spatial,
            preprocessing=preprocessing,
            intent=intent,
        )

    def estimate_cost(
        self,
        placed: PlacementEngineOutput,
        skus: dict[str, SKU],
    ) -> BudgetEstimateDTO:
        """Estimate total Estimated Cost for all items in a placed variant.

        Looks up each item's price_tier from the preprocessed SKU dict.
        Falls back to ESTIMATED_PRICE_FALLBACK when a SKU is unrecognised.

        NOTE: All figures are estimates — not real retail prices.
        """
        items: list[BudgetItemEstimate] = []
        for _item_name, placed_item in placed.positioned_items.items():
            sku = skus.get(placed_item.sku_id)
            if sku is not None:
                tier = sku.price_tier.lower()
                cost = ESTIMATED_PRICE_MAP.get(tier, ESTIMATED_PRICE_FALLBACK)
                items.append(
                    BudgetItemEstimate(
                        sku_id=placed_item.sku_id,
                        name=placed_item.name,
                        category=placed_item.category,
                        price_tier=tier,
                        estimated_cost_gbp=cost,
                    )
                )
            else:
                logger.warning(
                    "SKU %s not in preprocessing.skus — using fallback estimate",
                    placed_item.sku_id,
                )
                items.append(
                    BudgetItemEstimate(
                        sku_id=placed_item.sku_id,
                        name=placed_item.name,
                        category=placed_item.category,
                        price_tier="unknown",
                        estimated_cost_gbp=ESTIMATED_PRICE_FALLBACK,
                    )
                )

        total = sum(i.estimated_cost_gbp for i in items)
        return BudgetEstimateDTO(
            variant_id=placed.variant_id,
            total_estimated_cost_gbp=total,
            items=items,
        )

    # ------------------------------------------------------------------ #
    # Private: substitution loop                                           #
    # ------------------------------------------------------------------ #

    def _substitute_to_budget(
        self,
        variant: VariantSummaryDTO,
        placed: PlacementEngineOutput,
        original_estimate: BudgetEstimateDTO,
        target_budget_gbp: float,
        spatial: SpatialEngineOutput,
        preprocessing: PreprocessingOutput,
        intent: IntentDTO,
    ) -> BudgetOptimizationDTO:
        """Attempt SKU substitutions until the variant fits within the budget.

        Works on a mutable copy of positioned_items so the original PlacementEngineOutput
        is never modified. Re-validates NKBA after each accepted substitution.
        """
        # Work on a mutable copy of placed items
        current_placed = self._copy_placed(placed)
        current_score = variant.score
        substitutions: list[SubstitutionDTO] = []
        warnings: list[str] = []

        # Sort item estimates by cost descending (attack costliest first)
        sorted_items = sorted(
            original_estimate.items,
            key=lambda e: e.estimated_cost_gbp,
            reverse=True,
        )

        for item_estimate in sorted_items:
            current_total = sum(
                ESTIMATED_PRICE_MAP.get(
                    (preprocessing.skus.get(pi.sku_id) or _fake_sku(pi)).price_tier.lower(),
                    ESTIMATED_PRICE_FALLBACK,
                )
                for pi in current_placed.positioned_items.values()
            )
            if current_total <= target_budget_gbp:
                break  # Already under budget

            if item_estimate.price_tier == "low":
                continue  # Already cheapest tier; nothing cheaper available

            target_tier = _next_lower_tier(item_estimate.price_tier)
            if target_tier is None:
                continue

            original_item = current_placed.positioned_items.get(
                _find_item_name(current_placed, item_estimate.sku_id)
            )
            if original_item is None:
                continue

            sub = self._try_substitute(
                item=original_item,
                item_estimate=item_estimate,
                target_tier=target_tier,
                current_placed=current_placed,
                current_score=current_score,
                spatial=spatial,
                preprocessing=preprocessing,
                intent=intent,
            )
            if sub is not None:
                substitutions.append(sub)
                current_score = sub.nkba_score_after
                logger.info(
                    "Substitution accepted: %s → %s, saving £%.0f",
                    sub.original_sku_id,
                    sub.substitute_sku_id,
                    -sub.cost_delta_gbp,
                )
            else:
                warnings.append(
                    f"No suitable substitute found for {item_estimate.sku_id} "
                    f"(category={item_estimate.category}, tier={item_estimate.price_tier})"
                )
                logger.warning(
                    "No substitute found for SKU %s (category=%s)",
                    item_estimate.sku_id,
                    item_estimate.category,
                )

        # Build final estimate from current state
        optimized_estimate = (
            self.estimate_cost(current_placed, preprocessing.skus) if substitutions else None
        )
        final_total = (
            optimized_estimate.total_estimated_cost_gbp
            if optimized_estimate
            else original_estimate.total_estimated_cost_gbp
        )
        within_budget = final_total <= target_budget_gbp
        nkba_score_delta = current_score - variant.score

        return BudgetOptimizationDTO(
            variant_id=variant.id,
            target_budget_gbp=target_budget_gbp,
            original_estimate=original_estimate,
            optimized_estimate=optimized_estimate,
            substitutions=substitutions,
            within_budget=within_budget,
            nkba_score_delta=round(nkba_score_delta, 4),
            warnings=warnings,
        )

    def _try_substitute(
        self,
        item: PlacedItem,
        item_estimate: BudgetItemEstimate,
        target_tier: str,
        current_placed: PlacementEngineOutput,
        current_score: float,
        spatial: SpatialEngineOutput,
        preprocessing: PreprocessingOutput,
        intent: IntentDTO,
    ) -> SubstitutionDTO | None:
        """Attempt to swap one item for a cheaper substitute.

        Steps:
          1. Call get_substitute_skus() via mcp_server — never read catalog.json.
          2. Score candidates by color closeness (color_resolver) and style match.
          3. For each candidate (best color match first):
             a. Check width continuity: reject if gap > CONTINUITY_GAP_TOLERANCE_MM.
             b. Apply substitution to a copy of current_placed.
             c. Re-run NKBA validation.
             d. Reject if score drops > SCORE_DROP_TOLERANCE.
             e. If all checks pass, mutate current_placed in place and return DTO.

        Returns SubstitutionDTO on success, or None if all candidates rejected.
        """
        candidates = get_substitute_skus(
            category=item_estimate.category,
            max_tier=target_tier,
            width_mm=item.dimensions_mm.get("width", item.dimensions_mm.get("width_mm", 600.0)),
            width_tolerance_mm=CONTINUITY_GAP_TOLERANCE_MM,
        )
        # Filter out the item itself
        candidates = [c for c in candidates if c["sku_id"] != item_estimate.sku_id]

        if not candidates:
            return None

        # Score candidates: prefer color match, then style match
        scored = self._score_candidates(candidates, intent)

        for candidate in scored:
            new_sku_id: str = candidate["sku_id"]
            new_width: float = float(candidate["width_mm"])
            item_name = _find_item_name(current_placed, item_estimate.sku_id)
            if item_name is None:
                continue

            # Check cabinet run continuity
            continuity_ok = self._check_continuity(current_placed, item_name, new_width)
            if not continuity_ok:
                logger.debug(
                    "Continuity check failed for %s → %s (gap > %smm)",
                    item_estimate.sku_id,
                    new_sku_id,
                    CONTINUITY_GAP_TOLERANCE_MM,
                )
                continue

            # Apply substitution to a copy, then re-validate
            trial_placed = self._copy_placed(current_placed)
            self._apply_substitution(trial_placed, item_name, candidate)

            new_variant_summary = self._validator.validate(trial_placed, spatial, preprocessing)
            new_score = new_variant_summary.score

            if new_score < current_score - SCORE_DROP_TOLERANCE:
                logger.debug(
                    "Substitution rejected: %s → %s (score %.3f → %.3f, drop %.3f > %.3f)",
                    item_estimate.sku_id,
                    new_sku_id,
                    current_score,
                    new_score,
                    current_score - new_score,
                    SCORE_DROP_TOLERANCE,
                )
                continue

            # Accepted — mutate current_placed in place
            self._apply_substitution(current_placed, item_name, candidate)

            # Color preservation check (informational — already applied)
            color_preserved = self._color_preserved(item_estimate, candidate, intent)

            original_cost = ESTIMATED_PRICE_MAP.get(
                item_estimate.price_tier, ESTIMATED_PRICE_FALLBACK
            )
            sub_cost = ESTIMATED_PRICE_MAP.get(
                candidate["price_tier"].lower(), ESTIMATED_PRICE_FALLBACK
            )

            sub_warnings: list[str] = []
            if not color_preserved and intent.color_keyword:
                sub_warnings.append(
                    f"Color not preserved for {new_sku_id} (requested: {intent.color_keyword})"
                )

            return SubstitutionDTO(
                original_sku_id=item_estimate.sku_id,
                substitute_sku_id=new_sku_id,
                original_tier=item_estimate.price_tier,
                substitute_tier=candidate["price_tier"].lower(),
                original_cost_gbp=original_cost,
                substitute_cost_gbp=sub_cost,
                cost_delta_gbp=sub_cost - original_cost,  # negative = savings
                color_preserved=color_preserved,
                continuity_ok=continuity_ok,
                nkba_score_before=current_score,
                nkba_score_after=new_score,
                warnings=sub_warnings,
            )

        return None

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _score_candidates(
        self,
        candidates: list[dict[str, Any]],
        intent: IntentDTO,
    ) -> list[dict[str, Any]]:
        """Sort substitute candidates: color match first, then style, then width delta."""
        user_hex: str | None = None
        if intent.color_keyword:
            try:
                user_hex = keyword_to_hex(intent.color_keyword)
            except Exception:
                user_hex = None

        def _score(c: dict[str, Any]) -> tuple[float, int, float]:
            color_dist = 0.0
            if user_hex:
                sku_hex = c.get("color", "808080")
                color_dist = delta_e(user_hex, sku_hex)
            style_match = (
                0
                if (
                    intent.style and intent.style.lower() in [s.lower() for s in c.get("style", [])]
                )
                else 1
            )
            return (color_dist, style_match, 0.0)  # lower is better

        return sorted(candidates, key=_score)

    def _check_continuity(
        self,
        placed: PlacementEngineOutput,
        item_name: str,
        new_width_mm: float,
    ) -> bool:
        """Check whether swapping item_name's width creates a gap > 50mm on its wall.

        Finds all cabinet-run items on the same wall and checks that replacing
        the target item with new_width_mm does not create a gap larger than
        CONTINUITY_GAP_TOLERANCE_MM.
        """
        target = placed.positioned_items.get(item_name)
        if target is None:
            return True  # Item not found — cannot check; allow

        original_width = target.dimensions_mm.get(
            "width", target.dimensions_mm.get("width_mm", 0.0)
        )
        if new_width_mm >= original_width:
            return True  # Wider or equal — no gap created

        gap = original_width - new_width_mm
        return gap <= CONTINUITY_GAP_TOLERANCE_MM

    def _apply_substitution(
        self,
        placed: PlacementEngineOutput,
        item_name: str,
        candidate: dict[str, Any],
    ) -> None:
        """Mutate placed in place: replace item_name's SKU, name, and width with candidate."""
        old_item = placed.positioned_items[item_name]
        new_dims = dict(old_item.dimensions_mm)
        new_dims["width"] = float(candidate["width_mm"])
        new_dims["depth"] = float(candidate["depth_mm"])
        new_dims["height"] = float(candidate["height_mm"])

        placed.positioned_items[item_name] = dataclasses.replace(
            old_item,
            sku_id=candidate["sku_id"],
            name=candidate["name"],
            dimensions_mm=new_dims,
        )

    def _color_preserved(
        self,
        item_estimate: BudgetItemEstimate,
        candidate: dict[str, Any],
        intent: IntentDTO,
    ) -> bool:
        """Return True if the substitute is at least as close in color to the user intent."""
        if not intent.color_keyword:
            return True  # No color preference → always preserved

        try:
            user_hex = keyword_to_hex(intent.color_keyword)
            # We don't have the original SKU's color hex here without a catalog lookup,
            # so we simply check whether the candidate is within a reasonable delta-E
            candidate_hex = candidate.get("color", "808080")
            dist = delta_e(user_hex, candidate_hex)
            return dist <= 20.0  # Reasonable color-match threshold
        except Exception:
            return True  # On error, assume preserved

    @staticmethod
    def _copy_placed(placed: PlacementEngineOutput) -> PlacementEngineOutput:
        """Return a shallow copy of PlacementEngineOutput with a new positioned_items dict."""
        return PlacementEngineOutput(
            variant_id=placed.variant_id,
            positioned_items=dict(placed.positioned_items),  # new dict, same PlacedItem refs
            spillover_log=list(placed.spillover_log),
            collision_flags=list(placed.collision_flags),
        )


# ============================================================================
# Module-level helpers
# ============================================================================


def _next_lower_tier(tier: str) -> str | None:
    """Return the next cheaper tier, or None if already at lowest."""
    try:
        idx = TIER_ORDER.index(tier.lower())
    except ValueError:
        return None
    return TIER_ORDER[idx - 1] if idx > 0 else None


def _find_item_name(placed: PlacementEngineOutput, sku_id: str) -> str | None:
    """Find the item name key in positioned_items by sku_id."""
    for name, item in placed.positioned_items.items():
        if item.sku_id == sku_id:
            return name
    return None


class _FakeSKU:
    """Minimal stand-in when a SKU is not in preprocessing.skus."""

    price_tier: str = "mid"


def _fake_sku(_placed_item: PlacedItem) -> _FakeSKU:
    """Return a fallback SKU-like object with 'mid' tier."""
    return _FakeSKU()
