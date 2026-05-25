"""LangGraph StateGraph wiring all 5 pipeline layers with conditional retry."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import anthropic
from langgraph.graph import END, START, StateGraph

from dtos.contracts import (
    FinalOutput,
    KitchenGraphState,
    PlacementEngineOutput,
    VariantSummaryDTO,
)
from pipeline.budget_optimizer import BudgetOptimizer
from pipeline.nkba_validator import NKBAValidator
from pipeline.output_generator import OutputGenerator
from pipeline.placement_engine import PlacementEngine
from pipeline.preprocessor import Preprocessor
from pipeline.spatial_engine import SpatialEngine
from pipeline.zone_planner import ZonePlanner
from utils.logger import get_logger
from utils.model_selector import should_use_opus
from utils.openrouter_compat import OpenRouterCompat

logger = get_logger(__name__)


class KitchenGraph:
    """LangGraph orchestrator for the full kitchen design pipeline."""

    def __init__(
        self,
        client: anthropic.Anthropic | OpenRouterCompat,
        output_path: str = "latest_run.json",
    ) -> None:
        """Initialise all pipeline layers and compile the graph."""
        self._spatial = SpatialEngine()
        self._preprocessor = Preprocessor(client)
        self._zone_planner = ZonePlanner(client)
        self._placement = PlacementEngine()
        self._validator = NKBAValidator()
        self._budget_optimizer = BudgetOptimizer(self._validator)
        self._output = OutputGenerator(client)
        self._output_path = output_path
        self._start_time = 0.0
        self._graph = self._build()

    async def run(self, input_json: dict[str, Any]) -> FinalOutput:
        """Execute the full pipeline and return FinalOutput."""
        self._start_time = time.time()
        # Extract optional numeric budget target from user preferences.
        prefs: dict[str, Any] = input_json.get("preferences", {})
        raw_budget = prefs.get("budget_target_gbp")
        budget_target: float | None = float(raw_budget) if raw_budget else None

        initial: dict[str, Any] = {
            "input_json": input_json,
            "spatial_output": None,
            "preprocessing_output": None,
            "variants": [],
            "placed_variants": [],
            "validated_variants": [],
            "retry_context": {},
            "final_output": None,
            "budget_target_gbp": budget_target,
        }
        result: dict[str, Any] = await self._graph.ainvoke(initial)
        return result["final_output"]  # type: ignore[no-any-return]

    # ------------------------------------------------------------------ #
    # Graph construction                                                   #
    # ------------------------------------------------------------------ #

    def _build(self) -> Any:
        """Build and compile the LangGraph StateGraph."""
        graph: StateGraph[KitchenGraphState] = StateGraph(KitchenGraphState)

        graph.add_node("spatial", self._node_spatial)
        graph.add_node("preprocessing", self._node_preprocessing)
        graph.add_node("zone_planner", self._node_zone_planner)
        graph.add_node("placement", self._node_placement)
        graph.add_node("validation", self._node_validation)
        graph.add_node("budget_optimization", self._node_budget_optimization)
        graph.add_node("output", self._node_output)

        graph.add_edge(START, "spatial")
        graph.add_edge("spatial", "preprocessing")
        graph.add_edge("preprocessing", "zone_planner")
        graph.add_edge("zone_planner", "placement")
        graph.add_edge("placement", "validation")
        graph.add_conditional_edges(
            "validation",
            self._should_retry,
            {"retry": "zone_planner", "done": "budget_optimization"},
        )
        graph.add_edge("budget_optimization", "output")
        graph.add_edge("output", END)

        return graph.compile()

    # ------------------------------------------------------------------ #
    # Nodes                                                                #
    # ------------------------------------------------------------------ #

    def _node_spatial(self, state: KitchenGraphState) -> dict[str, Any]:
        """Layer 1: parse spatial geometry from input JSON."""
        spatial = self._spatial.parse(state["input_json"])
        logger.info("Spatial: %d walls, capacity=%s", len(spatial.walls), spatial.layout_capacity)
        return {"spatial_output": spatial}

    async def _node_preprocessing(self, state: KitchenGraphState) -> dict[str, Any]:
        """Layer 2: parse intent, load catalog, select SKUs."""
        result = await asyncio.to_thread(
            self._preprocessor.run, state["input_json"], state["spatial_output"]
        )
        return {"preprocessing_output": result}

    async def _node_zone_planner(self, state: KitchenGraphState) -> dict[str, Any]:
        """Layer 3: generate zone plan variants via LayoutStrategist."""
        retry_ctx = state["retry_context"] or None
        variants = await self._zone_planner.run(
            state["preprocessing_output"],
            state["spatial_output"],
            state["input_json"],
            retry_ctx,
        )
        return {"variants": variants}

    async def _node_placement(self, state: KitchenGraphState) -> dict[str, Any]:
        """Layer 4: resolve semantic terms to mm coordinates for all variants in parallel."""
        placed: list[PlacementEngineOutput] = list(
            await asyncio.gather(
                *[
                    asyncio.to_thread(
                        self._placement.place,
                        variant,
                        state["preprocessing_output"],
                        state["spatial_output"],
                    )
                    for variant in state["variants"]
                ]
            )
        )
        logger.info("Placement complete: %d variants", len(placed))
        return {"placed_variants": placed}

    def _node_validation(self, state: KitchenGraphState) -> dict[str, Any]:
        """NKBA validation and retry-context update.

        On retry pass, compare each retry variant against the original first-pass
        validated variant of the same id and keep the higher-scoring one. This
        prevents a worse retry from replacing a better original.
        """
        is_retry_pass = bool(state["retry_context"])

        validated: list[VariantSummaryDTO] = [
            self._validator.validate(p, state["spatial_output"], state["preprocessing_output"])
            for p in state["placed_variants"]
        ]

        if is_retry_pass:
            previous = {v.id: v for v in state["validated_variants"]}
            merged: list[VariantSummaryDTO] = []
            for retry_v in validated:
                orig = previous.get(retry_v.id)
                if orig is None:
                    merged.append(retry_v)
                    continue
                if retry_v.score > orig.score:
                    logger.info(
                        "RETRY-USED-IMPROVED: %s retry %.3f > original %.3f",
                        retry_v.id,
                        retry_v.score,
                        orig.score,
                    )
                    merged.append(retry_v)
                else:
                    logger.info(
                        "RETRY-KEPT-ORIGINAL: %s original %.3f >= retry %.3f",
                        retry_v.id,
                        orig.score,
                        retry_v.score,
                    )
                    merged.append(orig)
            validated = merged

        new_retry: dict[str, list[str]] = {}
        if not is_retry_pass:
            for v in validated:
                vids = [x["rule_id"] for x in v.violations]
                if should_use_opus(v.score, vids):
                    new_retry[v.id] = vids
            if new_retry:
                logger.info("Retry triggered for variants: %s", list(new_retry))

        return {"validated_variants": validated, "retry_context": new_retry}

    def _node_budget_optimization(self, state: KitchenGraphState) -> dict[str, Any]:
        """Layer 5b: estimate variant costs and propose substitutions if over budget.

        Runs for every validated variant. If no budget target is set the node
        still attaches a cost estimate (BudgetOptimizationDTO) to each variant
        so the UI can display "Estimated Cost" unconditionally.

        placed_variants and validated_variants are paired by position (both lists
        come from the same parallel placement pass and share the same order).
        """
        import dataclasses as _dc

        budget_target: float | None = state.get("budget_target_gbp")  # type: ignore[call-overload]
        placed_by_id = {p.variant_id: p for p in state["placed_variants"]}
        spatial = state["spatial_output"]
        preprocessing = state["preprocessing_output"]

        enriched: list[VariantSummaryDTO] = []
        for variant in state["validated_variants"]:
            placed = placed_by_id.get(variant.id)
            if placed is None:
                logger.warning(
                    "Budget optimizer: no placed data for variant %s — skipping", variant.id
                )
                enriched.append(variant)
                continue

            try:
                budget_result = self._budget_optimizer.optimize_variant(
                    variant=variant,
                    placed=placed,
                    target_budget_gbp=budget_target,
                    spatial=spatial,
                    preprocessing=preprocessing,
                )
                enriched.append(_dc.replace(variant, budget_optimization=budget_result))
            except Exception as exc:
                logger.error("Budget optimizer failed for variant %s: %s", variant.id, exc)
                enriched.append(variant)  # keep original on error — never drop a variant

        logger.info("Budget optimization complete: %d variants processed", len(enriched))
        return {"validated_variants": enriched}

    async def _node_output(self, state: KitchenGraphState) -> dict[str, Any]:
        """Layer 5: assemble FinalOutput, write output.json, render PNGs."""
        final = await self._output.generate(
            state["validated_variants"],
            state["variants"],
            state["input_json"],
            self._start_time,
            self._output_path,
        )
        return {"final_output": final}

    # ------------------------------------------------------------------ #
    # Routing                                                              #
    # ------------------------------------------------------------------ #

    def _should_retry(self, state: KitchenGraphState) -> str:
        """Route to zone_planner retry or output based on retry_context."""
        return "retry" if state["retry_context"] else "done"
