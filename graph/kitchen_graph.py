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
from pipeline.nkba_validator import NKBAValidator
from pipeline.output_generator import OutputGenerator
from pipeline.placement_engine import PlacementEngine
from pipeline.preprocessor import Preprocessor
from pipeline.spatial_engine import SpatialEngine
from pipeline.zone_planner import ZonePlanner
from utils.logger import get_logger
from utils.model_selector import should_use_opus

logger = get_logger(__name__)


class KitchenGraph:
    """LangGraph orchestrator for the full kitchen design pipeline."""

    def __init__(
        self,
        client: anthropic.Anthropic,
        output_path: str = "output.json",
    ) -> None:
        """Initialise all pipeline layers and compile the graph."""
        self._spatial = SpatialEngine()
        self._preprocessor = Preprocessor(client)
        self._zone_planner = ZonePlanner(client)
        self._placement = PlacementEngine()
        self._validator = NKBAValidator()
        self._output = OutputGenerator(client)
        self._output_path = output_path
        self._start_time = 0.0
        self._graph = self._build()

    async def run(self, input_json: dict[str, Any]) -> FinalOutput:
        """Execute the full pipeline and return FinalOutput."""
        self._start_time = time.time()
        initial: dict[str, Any] = {
            "input_json": input_json,
            "spatial_output": None,
            "preprocessing_output": None,
            "variants": [],
            "placed_variants": [],
            "validated_variants": [],
            "retry_context": {},
            "final_output": None,
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
        graph.add_node("output", self._node_output)

        graph.add_edge(START, "spatial")
        graph.add_edge("spatial", "preprocessing")
        graph.add_edge("preprocessing", "zone_planner")
        graph.add_edge("zone_planner", "placement")
        graph.add_edge("placement", "validation")
        graph.add_conditional_edges(
            "validation",
            self._should_retry,
            {"retry": "zone_planner", "done": "output"},
        )
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
        """NKBA validation and retry-context update."""
        is_retry_pass = bool(state["retry_context"])

        validated: list[VariantSummaryDTO] = [
            self._validator.validate(p, state["spatial_output"], state["preprocessing_output"])
            for p in state["placed_variants"]
        ]

        new_retry: dict[str, list[str]] = {}
        if not is_retry_pass:
            for v in validated:
                vids = [x["rule_id"] for x in v.violations]
                if should_use_opus(v.score, vids):
                    new_retry[v.id] = vids
            if new_retry:
                logger.info("Retry triggered for variants: %s", list(new_retry))

        return {"validated_variants": validated, "retry_context": new_retry}

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
