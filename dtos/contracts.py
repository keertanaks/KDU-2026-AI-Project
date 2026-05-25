"""Data Transfer Objects (DTOs) for the kitchen layout pipeline.

This module defines all typed contracts used at module boundaries.
No logic, math, or LLM calls — data definitions only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict

# ============================================================================
# Primitive DTOs (Spatial & Catalog)
# ============================================================================


@dataclass
class Wall:
    """Represents a room wall with cabinets and dimensions."""

    name: str
    anchor: str
    length_mm: float
    height_mm: float
    thickness_mm: float
    has_cabinets: bool
    points: list[dict[str, Any]]


@dataclass
class Segment:
    """Represents a free continuous space on a wall."""

    start_mm: float
    end_mm: float

    @property
    def length_mm(self) -> float:
        """Compute length from start and end offsets."""
        return self.end_mm - self.start_mm


@dataclass
class Opening:
    """Represents a door or window aperture in a wall."""

    id: str
    kind: str
    wall: str
    offset_mm: float
    width_mm: float
    height_mm: float
    sill_mm: float
    blocked_start_mm: float
    blocked_end_mm: float


@dataclass
class SKU:
    """Catalog item (cabinet, appliance, fixture)."""

    sku_id: str
    name: str
    category: str
    width_mm: float
    depth_mm: float
    height_mm: float
    color: str
    price_tier: str
    style: list[str]
    front_clearance_mm: float
    needs_water: bool
    needs_power: bool
    must_attach_to: str
    placement: str = ""  # "built_in" | "counter_top" | "" (legacy)
    color_set: str = ""  # e.g. "ivory_white", "sage_green" — empty for legacy SKUs


@dataclass
class PlacedItem:
    """A SKU positioned and anchored in the kitchen."""

    sku_id: str
    name: str
    category: str
    position_mm: dict[str, float]
    dimensions_mm: dict[str, float]
    rotation_z_deg: float
    anchor_wall: str
    zone_type: str


# ============================================================================
# Budget Optimisation DTOs
# ============================================================================


@dataclass
class BudgetItemEstimate:
    """Estimated cost for one placed SKU.

    NOTE: These are ESTIMATES using a static price map — not real retail prices.
    Always surface this data with the label "Estimated Cost" in any UI or output.
    """

    sku_id: str
    name: str
    category: str
    price_tier: str  # "low" | "mid" | "high"
    estimated_cost_gbp: float  # Estimated Cost — not a real price


@dataclass
class BudgetEstimateDTO:
    """Total estimated cost for one layout variant.

    All figures are estimates derived from the ESTIMATED_PRICE_MAP constant in
    pipeline/budget_optimizer.py. Never claim these as real prices.
    """

    variant_id: str
    total_estimated_cost_gbp: float  # Estimated Cost — sum of item estimates
    items: list[BudgetItemEstimate]
    currency: str = "USD"


@dataclass
class SubstitutionDTO:
    """One accepted SKU swap: original (higher-tier) → substitute (lower-tier).

    Produced by pipeline/budget_optimizer.py after continuity and NKBA checks pass.
    """

    original_sku_id: str
    substitute_sku_id: str
    original_tier: str
    substitute_tier: str
    original_cost_gbp: float  # Estimated Cost of original SKU
    substitute_cost_gbp: float  # Estimated Cost of substitute SKU
    cost_delta_gbp: float  # negative = savings (Estimated)
    color_preserved: bool
    continuity_ok: bool
    nkba_score_before: float
    nkba_score_after: float
    warnings: list[str] = field(default_factory=list)


@dataclass
class BudgetOptimizationDTO:
    """Result of budget optimisation for one variant.

    Carried as an optional field on VariantSummaryDTO so downstream consumers
    (UI, output generator) can access it without changing the core pipeline flow.
    """

    variant_id: str
    target_budget_gbp: float | None  # None → no target, estimation only
    original_estimate: BudgetEstimateDTO
    optimized_estimate: BudgetEstimateDTO | None  # None → no substitutions made
    substitutions: list[SubstitutionDTO]
    within_budget: bool
    nkba_score_delta: float
    warnings: list[str] = field(default_factory=list)


@dataclass
class IntentDTO:
    """Parsed user preferences from input JSON."""

    color_keyword: str | None
    color_hex: str | None
    layout_family: str | None
    style: str | None
    cabinet_preference: str | None
    special_requests: list[str]
    ignored: list[str]
    budget_tier: str | None
    must_have: list[str]
    avoid: list[str]


# ============================================================================
# Pipeline DTOs (Layer Outputs)
# ============================================================================


@dataclass
class SpatialEngineOutput:
    """Result of Layer 1: Spatial facts extracted from input geometry.

    `free_segments` is for FLOOR-LEVEL items (base cabinets, sinks, appliances)
    and subtracts doors + door swings. Windows do NOT block floor items —
    a sink or base cabinet can sit below a window when the sill allows.

    `wall_free_segments` is for WALL-LEVEL items (upper / wall cabinets) and
    subtracts doors AND windows. Defaults to an empty dict for backward
    compatibility; callers should fall back to `free_segments` when empty.
    """

    walls: list[Wall]
    free_segments: dict[str, list[Segment]]
    flow_order: list[str]
    exclusions: list[Opening]
    layout_capacity: str
    wall_free_segments: dict[str, list[Segment]] = field(default_factory=dict)


@dataclass
class PreprocessingOutput:
    """Result of Layer 2: Intent parsed, SKUs selected, groups formed."""

    intent: IntentDTO
    skus: dict[str, SKU]
    zone_groups: dict[str, list[SKU]]
    zone_min_widths: dict[str, float]
    nkba_constraints: dict[str, Any]
    # Human-readable warnings generated when a color keyword had no exact catalog
    # match and a nearest-color substitution was made.  Empty list = no substitution.
    # Merged into VariantSummaryDTO.warnings[] by pipeline/nkba_validator.py.
    color_warnings: list[str] = field(default_factory=list)


@dataclass
class ZonePlannerOutput:
    """Result of Layer 3: Zone strategies for one variant.

    Primary placement contract (used first by placement engine):
        item_hints: {item_type → {wall, position}}
            Example: {"fridge": {"wall": "north_wall", "position": "at north-west corner"}}

    Fallback contracts (used if item_hints missing/invalid):
        wall_strategies: {wall → [position terms]}  — positional matching, legacy
        zone_assignments: {zone → wall}             — coarse routing
    """

    variant_id: str
    family: str
    wall_strategies: dict[str, list[str]]
    zone_assignments: dict[str, str]
    item_hints: dict[str, dict[str, str]] = field(default_factory=dict)
    work_triangle_priority: bool = True
    adjacency_hints: list[str] = field(default_factory=list)
    avoid_zones: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class PlacementEngineOutput:
    """Result of Layer 4: Items positioned in mm coordinates."""

    variant_id: str
    positioned_items: dict[str, PlacedItem]
    spillover_log: list[str]
    collision_flags: list[str]


@dataclass
class VariantSummaryDTO:
    """Result of Layer 5: Complete variant with score and compliance data."""

    id: str
    family: str
    score: float
    placement_count: int
    nkba_compliance_pct: float
    spillover_count: int
    warnings: list[str]
    violations: list[dict[str, Any]]
    rationale: list[dict[str, Any]]
    layout: dict[str, Any]
    environment: dict[str, Any]
    collision_pairs: list[dict[str, Any]] = field(default_factory=list)
    score_debug: dict[str, Any] = field(default_factory=dict)
    # Budget optimisation result — None when no budget target or feature disabled.
    # All cost figures inside are Estimated Cost (not real prices).
    budget_optimization: BudgetOptimizationDTO | None = None


@dataclass
class FinalOutput:
    """Top-level response envelope matching render.py contract."""

    request_id: str
    duration_ms: float
    layouts: list[VariantSummaryDTO]


# ============================================================================
# LangGraph State
# ============================================================================


class KitchenGraphState(TypedDict):
    """State container for the LangGraph pipeline orchestrator."""

    input_json: dict[str, Any]
    spatial_output: SpatialEngineOutput
    preprocessing_output: PreprocessingOutput
    variants: list[ZonePlannerOutput]
    placed_variants: list[PlacementEngineOutput]
    validated_variants: list[VariantSummaryDTO]
    retry_context: dict[str, list[str]]
    final_output: FinalOutput
    # Optional numeric budget target (USD). Populated from
    # input_json["preferences"]["budget_target_gbp"] in the graph run() method.
    budget_target_gbp: float | None
