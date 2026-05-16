# OpenSpec: LangGraph Orchestration
## Files: `graph/kitchen_graph.py`, `pipeline/preprocessor.py`, `pipeline/zone_planner.py`
## Branch: `feature/graph`
## Design Doc: §3.1, §3.2, §4

---

## Goal
Wire all pipeline stages into a LangGraph StateGraph.
Sequential for Layers 1–2, parallel for Layers 3–5.
Conditional edge for retry logic.

---

## `pipeline/preprocessor.py`

### Purpose
Orchestrate Agent 1 → MCP → Agent 2 sequentially.

```python
class Preprocessor:
    def __init__(self):
        self.prompt_parser = PromptParser()
        # MCP session started externally and passed in

    async def run(self, input_json: dict, mcp_session: ClientSession) -> PreprocessingOutput:
        preferences = input_json.get("preferences", {})
        prompt = preferences.get("prompt", "")

        # Step 1: Agent 1
        intent = self.prompt_parser.parse(prompt, preferences)

        # Step 2: Spatial Engine (already run, passed via state)
        # (spatial_output available in graph state)

        # Step 3: Agent 2 via MCP
        selector = CatalogSelector(mcp_session)
        return await selector.select(intent, spatial_output)
```

---

## `pipeline/zone_planner.py`

### Purpose
Orchestrate parallel Agent 3 calls.

```python
class ZonePlanner:
    def __init__(self):
        self.strategist = LayoutStrategist()

    async def run(self, spatial: SpatialEngineOutput,
                  preprocessing: PreprocessingOutput,
                  n_variants: int = 3,
                  retry_context: dict | None = None) -> list[ZonePlannerOutput]:
        return await self.strategist.plan_variants(
            spatial, preprocessing,
            n_variants=n_variants,
            layout_family=preprocessing.intent.layout_family,
            retry_context=retry_context,
        )
```

---

## `graph/kitchen_graph.py`

### KitchenGraphState
Define FIRST — before any nodes:
```python
from typing import TypedDict
from dtos.contracts import (SpatialEngineOutput, PreprocessingOutput,
                            ZonePlannerOutput, PlacementEngineOutput,
                            VariantSummaryDTO, FinalOutput)

class KitchenGraphState(TypedDict):
    input_json:            dict
    spatial_output:        SpatialEngineOutput
    preprocessing_output:  PreprocessingOutput
    variants:              list[ZonePlannerOutput]
    placed_variants:       list[PlacementEngineOutput]
    validated_variants:    list[VariantSummaryDTO]
    retry_context:         dict[str, list[str]]
    final_output:          FinalOutput
```

### Node Definitions

```python
from langgraph.graph import StateGraph, END

async def spatial_node(state: KitchenGraphState) -> dict:
    engine = SpatialEngine()
    return {"spatial_output": engine.parse(state["input_json"])}

async def preprocessing_node(state: KitchenGraphState) -> dict:
    async with start_mcp_session() as mcp_session:
        preprocessor = Preprocessor()
        output = await preprocessor.run(state["input_json"], mcp_session)
    return {"preprocessing_output": output}

async def zone_planner_node(state: KitchenGraphState) -> dict:
    planner = ZonePlanner()
    variants = await planner.run(
        state["spatial_output"],
        state["preprocessing_output"],
        n_variants=3,
        retry_context=state.get("retry_context"),
    )
    return {"variants": variants}

async def placement_node(state: KitchenGraphState) -> dict:
    engine = PlacementEngine()
    placed = await asyncio.gather(*[
        asyncio.to_thread(engine.place, v, state["preprocessing_output"], state["spatial_output"])
        for v in state["variants"]
    ])
    return {"placed_variants": list(placed)}

async def nkba_node(state: KitchenGraphState) -> dict:
    validator = NKBAValidator()
    validated = await asyncio.gather(*[
        asyncio.to_thread(validator.validate, pv, state["spatial_output"])
        for pv in state["placed_variants"]
    ])
    return {"validated_variants": list(validated)}

async def output_node(state: KitchenGraphState) -> dict:
    writer = RationaleWriter()
    # Write rationale for each variant
    for v in state["validated_variants"]:
        rationale = await writer.write(
            state["placed_variants"][0],  # match by variant_id
            v,
            state["preprocessing_output"].intent,
        )
        v.rationale = rationale

    generator = OutputGenerator()
    final = generator.generate(
        state["validated_variants"],
        state["input_json"],
        state.get("_start_time", time.time()),
    )
    return {"final_output": final}
```

### Conditional Edge — Retry Logic

```python
def should_retry(state: KitchenGraphState) -> str:
    if state.get("_retry_done"):
        return "output"  # never retry more than once

    retry_context = {}
    for v in state["validated_variants"]:
        violation_ids = [x["rule_id"] for x in v.violations]
        needs_retry = (
            v.score < 0.60
            or "WORKFLOW-03" in violation_ids
            or "NKBA-CL-01" in violation_ids
        )
        if needs_retry:
            retry_context[v.variant_id] = violation_ids

    if retry_context:
        return "retry"
    return "output"
```

### Graph Assembly

```python
def build_graph() -> StateGraph:
    graph = StateGraph(KitchenGraphState)

    graph.add_node("spatial",       spatial_node)
    graph.add_node("preprocessing", preprocessing_node)
    graph.add_node("zone_planner",  zone_planner_node)
    graph.add_node("placement",     placement_node)
    graph.add_node("nkba",          nkba_node)
    graph.add_node("output",        output_node)

    graph.set_entry_point("spatial")
    graph.add_edge("spatial",       "preprocessing")
    graph.add_edge("preprocessing", "zone_planner")
    graph.add_edge("zone_planner",  "placement")
    graph.add_edge("placement",     "nkba")

    graph.add_conditional_edges(
        "nkba",
        should_retry,
        {
            "retry":  "zone_planner",  # re-plan with opus + violations
            "output": "output",
        }
    )

    graph.add_edge("output", END)
    return graph.compile()
```

### MCP Session Helper

```python
from contextlib import asynccontextmanager
from mcp import ClientSession, StdioServerParameters
import subprocess, asyncio

@asynccontextmanager
async def start_mcp_session():
    proc = await asyncio.create_subprocess_exec(
        "python", "mcp_server/server.py",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )
    async with ClientSession(proc.stdout, proc.stdin) as session:
        await session.initialize()
        yield session
    proc.terminate()
```

---

## Validation
```bash
python -c "
import asyncio, json
from graph.kitchen_graph import build_graph

async def test():
    graph = build_graph()
    with open('input1.json') as f:
        input_json = json.load(f)
    input_json.setdefault('preferences', {})['prompt'] = 'navy blue base cabinets'
    result = await graph.ainvoke({'input_json': input_json})
    layouts = result['final_output'].layouts
    print('Variants:', len(layouts))
    print('Scores:', [round(v.score, 2) for v in layouts])
    assert len(layouts) >= 3, 'Expected at least 3 variants'
    print('PASS')

asyncio.run(test())
"
```
