"""Unit tests for pipeline/budget_optimizer.py.

Tests cover:
- Estimated cost calculation (sum of ESTIMATED_PRICE_MAP values)
- Cabinet run continuity check after SKU width substitution
- No substitution when variant is already within budget
- Color preservation preference in candidate scoring
- Substitution rejection when NKBA score drops > SCORE_DROP_TOLERANCE

All fixture SKU data comes from tests/fixtures/sample_inputs.py.
No fake SKUs defined inline. No API calls — all math is deterministic.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dtos.contracts import (
    BudgetEstimateDTO,
    IntentDTO,
    PlacedItem,
    PlacementEngineOutput,
    PreprocessingOutput,
    Segment,
    SpatialEngineOutput,
    VariantSummaryDTO,
    Wall,
)
from pipeline.budget_optimizer import (
    CONTINUITY_GAP_TOLERANCE_MM,
    ESTIMATED_PRICE_MAP,
    SCORE_DROP_TOLERANCE,
    BudgetOptimizer,
)
from tests.fixtures.sample_inputs import (
    SAMPLE_SKU_HIGH,
    SAMPLE_SKU_LOW,
    SAMPLE_SKU_MID,
)

# ============================================================================
# Shared helpers
# ============================================================================


def _wall(name: str = "north_wall", length_mm: float = 4000.0) -> Wall:
    return Wall(
        name=name,
        anchor=name,
        length_mm=length_mm,
        height_mm=2700.0,
        thickness_mm=100.0,
        has_cabinets=True,
        points=[],
    )


def _spatial() -> SpatialEngineOutput:
    w = _wall()
    return SpatialEngineOutput(
        walls=[w],
        free_segments={w.name: [Segment(0.0, w.length_mm)]},
        flow_order=[w.name],
        exclusions=[],
        layout_capacity="medium",
    )


def _intent(color_keyword: str | None = None, style: str | None = None) -> IntentDTO:
    return IntentDTO(
        color_keyword=color_keyword,
        color_hex=None,
        layout_family=None,
        style=style,
        cabinet_preference=None,
        special_requests=[],
        ignored=[],
        budget_tier="mid",
        must_have=[],
        avoid=[],
    )


def _preprocessing(
    skus: dict | None = None,
    intent: IntentDTO | None = None,
) -> PreprocessingOutput:
    return PreprocessingOutput(
        intent=intent or _intent(),
        skus=skus or {},
        zone_groups={},
        zone_min_widths={},
        nkba_constraints={},
    )


def _placed_item(
    sku_id: str,
    name: str,
    category: str = "base_cabinet",
    x: float = 0.0,
    width: float = 600.0,
    wall: str = "north_wall",
) -> PlacedItem:
    return PlacedItem(
        sku_id=sku_id,
        name=name,
        category=category,
        position_mm={"x": x, "y": 100.0, "z": 0.0},
        dimensions_mm={"width": width, "depth": 570.0, "height": 850.0},
        rotation_z_deg=0.0,
        anchor_wall=wall,
        zone_type="preparation",
    )


def _placement(items: dict[str, PlacedItem], variant_id: str = "v1") -> PlacementEngineOutput:
    return PlacementEngineOutput(
        variant_id=variant_id,
        positioned_items=items,
        spillover_log=[],
        collision_flags=[],
    )


def _variant(variant_id: str = "v1", score: float = 0.85) -> VariantSummaryDTO:
    return VariantSummaryDTO(
        id=variant_id,
        family="L",
        score=score,
        placement_count=2,
        nkba_compliance_pct=90.0,
        spillover_count=0,
        warnings=[],
        violations=[],
        rationale=[],
        layout={},
        environment={},
    )


def _mock_validator(return_score: float = 0.85) -> MagicMock:
    """Return a mock NKBAValidator whose validate() returns the given score."""
    mock = MagicMock()
    summary = _variant(score=return_score)
    mock.validate.return_value = summary
    return mock


# ============================================================================
# Test: Estimated Cost Calculation
# ============================================================================


class TestEstimatedCostCalculation:
    """Verify that estimate_cost() sums ESTIMATED_PRICE_MAP correctly."""

    def test_single_low_tier_item(self) -> None:
        """One low-tier item → total == ESTIMATED_PRICE_MAP['low']."""
        items = {
            "cabinet_1": _placed_item(SAMPLE_SKU_LOW.sku_id, "Cabinet 1"),
        }
        placed = _placement(items)
        skus = {SAMPLE_SKU_LOW.sku_id: SAMPLE_SKU_LOW}
        preprocessing = _preprocessing(skus=skus)

        optimizer = BudgetOptimizer(_mock_validator())
        result: BudgetEstimateDTO = optimizer.estimate_cost(placed, preprocessing.skus)

        assert result.total_estimated_cost_gbp == ESTIMATED_PRICE_MAP["low"]
        assert len(result.items) == 1
        assert result.items[0].price_tier == "low"
        assert result.items[0].estimated_cost_gbp == ESTIMATED_PRICE_MAP["low"]

    def test_mixed_tier_sum(self) -> None:
        """Three items at low/mid/high → total is the sum of all three map values."""
        items = {
            "low_item": _placed_item(SAMPLE_SKU_LOW.sku_id, "Low Cabinet", x=0.0),
            "mid_item": _placed_item(SAMPLE_SKU_MID.sku_id, "Mid Cabinet", x=600.0),
            "high_item": _placed_item(SAMPLE_SKU_HIGH.sku_id, "High Cabinet", x=1200.0),
        }
        placed = _placement(items)
        skus = {
            SAMPLE_SKU_LOW.sku_id: SAMPLE_SKU_LOW,
            SAMPLE_SKU_MID.sku_id: SAMPLE_SKU_MID,
            SAMPLE_SKU_HIGH.sku_id: SAMPLE_SKU_HIGH,
        }
        preprocessing = _preprocessing(skus=skus)

        optimizer = BudgetOptimizer(_mock_validator())
        result = optimizer.estimate_cost(placed, preprocessing.skus)

        expected_total = (
            ESTIMATED_PRICE_MAP["low"] + ESTIMATED_PRICE_MAP["mid"] + ESTIMATED_PRICE_MAP["high"]
        )
        assert result.total_estimated_cost_gbp == expected_total

    def test_cost_labeled_as_estimate(self) -> None:
        """BudgetEstimateDTO field is named 'total_estimated_cost_gbp', not 'price'."""
        items = {"item": _placed_item(SAMPLE_SKU_MID.sku_id, "Mid Item")}
        placed = _placement(items)
        skus = {SAMPLE_SKU_MID.sku_id: SAMPLE_SKU_MID}

        optimizer = BudgetOptimizer(_mock_validator())
        result = optimizer.estimate_cost(placed, skus)

        # Verify field naming convention: "estimated" in the field name
        assert hasattr(result, "total_estimated_cost_gbp")
        assert result.items[0].estimated_cost_gbp == ESTIMATED_PRICE_MAP["mid"]


# ============================================================================
# Test: No Substitution When Already Within Budget
# ============================================================================


class TestNoSubstitutionWhenWithinBudget:
    """Optimizer returns 0 substitutions when variant is already under target."""

    def test_within_budget_no_subs(self) -> None:
        """Target budget >= total → no substitutions, within_budget=True."""
        items = {
            "item_1": _placed_item(SAMPLE_SKU_LOW.sku_id, "Low Item 1"),
            "item_2": _placed_item(SAMPLE_SKU_LOW.sku_id, "Low Item 2", x=600.0),
        }
        placed = _placement(items)
        skus = {SAMPLE_SKU_LOW.sku_id: SAMPLE_SKU_LOW}
        preprocessing = _preprocessing(skus=skus)
        variant = _variant()
        total = ESTIMATED_PRICE_MAP["low"] * 2  # £1000

        optimizer = BudgetOptimizer(_mock_validator())
        result = optimizer.optimize_variant(
            variant=variant,
            placed=placed,
            target_budget_gbp=total + 1000.0,  # well over total
            spatial=_spatial(),
            preprocessing=preprocessing,
        )

        assert result.within_budget is True
        assert len(result.substitutions) == 0
        assert result.optimized_estimate is None

    def test_no_target_returns_estimation_only(self) -> None:
        """No budget target → estimation only, no substitutions, within_budget=True."""
        items = {"item": _placed_item(SAMPLE_SKU_HIGH.sku_id, "High Item")}
        placed = _placement(items)
        skus = {SAMPLE_SKU_HIGH.sku_id: SAMPLE_SKU_HIGH}
        preprocessing = _preprocessing(skus=skus)

        optimizer = BudgetOptimizer(_mock_validator())
        result = optimizer.optimize_variant(
            variant=_variant(),
            placed=placed,
            target_budget_gbp=None,
            spatial=_spatial(),
            preprocessing=preprocessing,
        )

        assert result.target_budget_gbp is None
        assert result.within_budget is True
        assert len(result.substitutions) == 0
        assert result.original_estimate.total_estimated_cost_gbp == ESTIMATED_PRICE_MAP["high"]


# ============================================================================
# Test: Continuity Preserved After Substitution
# ============================================================================


class TestSubstitutePreservesContinuity:
    """Cabinet run continuity must be maintained after SKU swap (LAYOUT-03)."""

    def test_same_width_substitute_no_gap(self) -> None:
        """Swapping an item for an equal-width substitute creates no gap."""
        optimizer = BudgetOptimizer(_mock_validator())
        # Item is 600mm wide; new SKU is also 600mm wide — gap = 0
        items = {"cabinet": _placed_item("some-sku", "Cabinet", width=600.0)}
        placed = _placement(items)
        continuity_ok = optimizer._check_continuity(placed, "cabinet", new_width_mm=600.0)
        assert continuity_ok is True

    def test_narrower_within_tolerance_ok(self) -> None:
        """Replacing 600mm with 560mm creates 40mm gap — within 50mm tolerance."""
        optimizer = BudgetOptimizer(_mock_validator())
        items = {"cabinet": _placed_item("some-sku", "Cabinet", width=600.0)}
        placed = _placement(items)
        # Gap = 600 - 560 = 40mm < 50mm tolerance
        continuity_ok = optimizer._check_continuity(placed, "cabinet", new_width_mm=560.0)
        assert continuity_ok is True

    def test_narrower_beyond_tolerance_rejected(self) -> None:
        """Replacing 600mm with 500mm creates 100mm gap — exceeds 50mm tolerance."""
        optimizer = BudgetOptimizer(_mock_validator())
        items = {"cabinet": _placed_item("some-sku", "Cabinet", width=600.0)}
        placed = _placement(items)
        # Gap = 600 - 500 = 100mm > 50mm tolerance
        continuity_ok = optimizer._check_continuity(placed, "cabinet", new_width_mm=500.0)
        assert continuity_ok is False

    def test_wider_substitute_always_ok(self) -> None:
        """Replacing with a wider SKU never creates a gap."""
        optimizer = BudgetOptimizer(_mock_validator())
        items = {"cabinet": _placed_item("some-sku", "Cabinet", width=600.0)}
        placed = _placement(items)
        continuity_ok = optimizer._check_continuity(placed, "cabinet", new_width_mm=800.0)
        assert continuity_ok is True

    def test_gap_tolerance_equals_layout03_constant(self) -> None:
        """CONTINUITY_GAP_TOLERANCE_MM must equal the LAYOUT-03 definition (50mm)."""
        # If this constant drifts from LAYOUT-03 in nkba_validator.py (50mm),
        # the continuous-run skill's rule is silently violated.
        assert CONTINUITY_GAP_TOLERANCE_MM == 50.0


# ============================================================================
# Test: Substitution Rejected on NKBA Score Drop
# ============================================================================


class TestSubstitutionRejectedOnScoreDrop:
    """Substitutions must be rejected if they lower the NKBA score by > SCORE_DROP_TOLERANCE."""

    def test_rejection_when_score_drops_too_much(self) -> None:
        """Substitute that causes score to drop > 0.05 must be rejected."""
        # Variant starts at score 0.85; mock validator returns 0.75 after sub (drop = 0.10)
        original_score = 0.85
        post_sub_score = original_score - (SCORE_DROP_TOLERANCE + 0.05)  # drop = 0.10

        # Patch get_substitute_skus to return one candidate
        candidate = {
            "sku_id": SAMPLE_SKU_LOW.sku_id,
            "name": SAMPLE_SKU_LOW.name,
            "category": "base_cabinet",
            "width_mm": 600.0,
            "depth_mm": 570.0,
            "height_mm": 850.0,
            "price_tier": "low",
            "color": "EDEDE9",
            "style": ["modern"],
            "front_clearance_mm": 1067.0,
            "needs_water": False,
            "needs_power": False,
            "must_attach_to": "wall",
        }

        # Validator returns a low score (simulates constraint violation from sub)
        bad_validator = _mock_validator(return_score=post_sub_score)
        optimizer = BudgetOptimizer(bad_validator)

        items = {"high_item": _placed_item(SAMPLE_SKU_HIGH.sku_id, "High Cabinet", width=600.0)}
        placed = _placement(items)
        skus = {SAMPLE_SKU_HIGH.sku_id: SAMPLE_SKU_HIGH}
        preprocessing = _preprocessing(skus=skus)

        with patch(
            "pipeline.budget_optimizer.get_substitute_skus",
            return_value=[candidate],
        ):
            result = optimizer.optimize_variant(
                variant=_variant(score=original_score),
                placed=placed,
                target_budget_gbp=100.0,  # well below cost to force substitution attempt
                spatial=_spatial(),
                preprocessing=preprocessing,
            )

        # Substitution should have been rejected
        assert len(result.substitutions) == 0

    def test_score_drop_tolerance_is_five_percent(self) -> None:
        """SCORE_DROP_TOLERANCE must be exactly 0.05."""
        assert SCORE_DROP_TOLERANCE == 0.05


# ============================================================================
# Test: Color Preservation
# ============================================================================


class TestColorPreservation:
    """Substitutes are sorted by color closeness to the user's intent."""

    def test_color_preserved_flag_set_when_close(self) -> None:
        """Substitute with same color hex as user intent → color_preserved=True."""
        # navy blue intent; SAMPLE_SKU_MID has color "1F3A5F" (navy)
        intent = _intent(color_keyword="navy blue")
        optimizer = BudgetOptimizer(_mock_validator())

        item_estimate_stub = type(
            "E",
            (),
            {
                "sku_id": SAMPLE_SKU_HIGH.sku_id,
                "price_tier": "high",
                "category": "base_cabinet",
            },
        )()

        # Candidate with same navy color
        navy_candidate = {
            "sku_id": SAMPLE_SKU_MID.sku_id,
            "color": "1F3A5F",  # navy blue — close match to intent
            "price_tier": "mid",
            "style": ["modern"],
        }

        color_ok = optimizer._color_preserved(item_estimate_stub, navy_candidate, intent)
        assert color_ok is True

    def test_candidates_sorted_by_color_closeness(self) -> None:
        """_score_candidates returns candidates ordered by closeness to user color."""
        intent = _intent(color_keyword="navy blue")
        optimizer = BudgetOptimizer(_mock_validator())

        # Two candidates: one navy (close), one white (far)
        navy_candidate = {"sku_id": "A", "color": "1F3A5F", "price_tier": "low", "style": []}
        white_candidate = {"sku_id": "B", "color": "FFFFFF", "price_tier": "low", "style": []}

        scored = optimizer._score_candidates([white_candidate, navy_candidate], intent)
        # Navy (closer to navy blue) should come first
        assert scored[0]["sku_id"] == "A"


# ============================================================================
# Test: NKBA Re-validation After Substitution
# ============================================================================


class TestRevalidationAfterSubstitution:
    """NKBA score must be independently re-calculated after every substitution."""

    def test_validate_called_for_each_accepted_substitution(self) -> None:
        """NKBAValidator.validate() must be called once per accepted substitution."""
        # Set up: one high-tier item; one valid low-tier substitute; validator keeps score
        original_score = 0.85
        validator_mock = _mock_validator(return_score=original_score)
        optimizer = BudgetOptimizer(validator_mock)

        items = {"high_item": _placed_item(SAMPLE_SKU_HIGH.sku_id, "High Cabinet", width=600.0)}
        placed = _placement(items)
        skus = {SAMPLE_SKU_HIGH.sku_id: SAMPLE_SKU_HIGH}
        preprocessing = _preprocessing(skus=skus)

        candidate = {
            "sku_id": SAMPLE_SKU_LOW.sku_id,
            "name": SAMPLE_SKU_LOW.name,
            "category": "base_cabinet",
            "width_mm": 600.0,
            "depth_mm": 570.0,
            "height_mm": 850.0,
            "price_tier": "low",
            "color": "EDEDE9",
            "style": ["modern"],
            "front_clearance_mm": 1067.0,
            "needs_water": False,
            "needs_power": False,
            "must_attach_to": "wall",
        }

        with patch(
            "pipeline.budget_optimizer.get_substitute_skus",
            return_value=[candidate],
        ):
            result = optimizer.optimize_variant(
                variant=_variant(score=original_score),
                placed=placed,
                target_budget_gbp=100.0,  # well below cost to trigger substitution
                spatial=_spatial(),
                preprocessing=preprocessing,
            )

        # Validator must have been called (re-validation happened)
        assert validator_mock.validate.call_count >= 1

        # If substitution was accepted, it must carry the score from the re-validation
        if result.substitutions:
            sub = result.substitutions[0]
            assert sub.nkba_score_after == original_score

    def test_score_delta_in_dto_is_accurate(self) -> None:
        """BudgetOptimizationDTO.nkba_score_delta reflects actual score change."""
        original_score = 0.80
        post_sub_score = 0.78  # small drop within tolerance
        validator_mock = _mock_validator(return_score=post_sub_score)
        optimizer = BudgetOptimizer(validator_mock)

        items = {"high_item": _placed_item(SAMPLE_SKU_HIGH.sku_id, "High", width=600.0)}
        placed = _placement(items)
        skus = {SAMPLE_SKU_HIGH.sku_id: SAMPLE_SKU_HIGH}
        preprocessing = _preprocessing(skus=skus)

        candidate = {
            "sku_id": SAMPLE_SKU_LOW.sku_id,
            "name": SAMPLE_SKU_LOW.name,
            "category": "base_cabinet",
            "width_mm": 600.0,
            "depth_mm": 570.0,
            "height_mm": 850.0,
            "price_tier": "low",
            "color": "EDEDE9",
            "style": ["modern"],
            "front_clearance_mm": 1067.0,
            "needs_water": False,
            "needs_power": False,
            "must_attach_to": "wall",
        }

        with patch(
            "pipeline.budget_optimizer.get_substitute_skus",
            return_value=[candidate],
        ):
            result = optimizer.optimize_variant(
                variant=_variant(score=original_score),
                placed=placed,
                target_budget_gbp=100.0,
                spatial=_spatial(),
                preprocessing=preprocessing,
            )

        if result.substitutions:
            expected_delta = post_sub_score - original_score
            assert abs(result.nkba_score_delta - expected_delta) < 1e-6
