# Coding Standards
## Auto-Design System | Project 2

Every file in this project must follow these standards. No exceptions.
Claude Code checks these automatically — violations block PR merge.

---

## 1. Python Version & Type Hints

**Minimum:** Python 3.11+
**Required:** Full type annotations on every function signature.

```python
# WRONG
def place(zone_plan, preprocessing, spatial):
    pass

# CORRECT
def place(
    zone_plan: ZonePlannerOutput,
    preprocessing: PreprocessingOutput,
    spatial: SpatialEngineOutput,
) -> PlacementEngineOutput:
    pass
```

- Use `from __future__ import annotations` at the top of every file
- Use `TypedDict` for dicts passed between pipeline stages (never `dict[str, Any]` in public interfaces)
- Use `dataclass` with `frozen=True` for value objects (Wall, Segment, Opening, SKU)
- Use `Protocol` instead of `ABC` for interfaces

---

## 2. Imports

Grouped in order, separated by blank lines:
1. Standard library (`from __future__`, `os`, `json`, `asyncio`, ...)
2. Third-party (`anthropic`, `langgraph`, `streamlit`, ...)
3. Internal (`from dtos.contracts import ...`)

```python
# CORRECT
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import anthropic
from langgraph.graph import StateGraph

from dtos.contracts import SpatialEngineOutput, ZonePlannerOutput
```

No star imports (`from module import *`). Ever.

---

## 3. Error Handling

**Rule:** Only catch what you can handle. Never `except Exception: pass`.

```python
# WRONG
try:
    result = api_call()
except Exception:
    pass

# CORRECT — log and fallback, still return something useful
try:
    result = api_call()
except anthropic.APIError as e:
    logger.warning("Agent 1 API call failed: %s — returning empty IntentDTO", e)
    return IntentDTO(color_keyword=None, ...)
```

**Agent fallback rule:** All Claude API calls MUST have a try/except that returns a valid (possibly empty) DTO. Never propagate API errors to LangGraph nodes — they cause graph state corruption.

**Pipeline rule:** Code-only stages (SpatialEngine, PlacementEngine, NKBAValidator) should raise `ValueError` with descriptive messages on bad input. LangGraph will catch these and mark the node as failed.

---

## 4. Logging

Use Python standard `logging`, not `print`. One logger per module.

```python
import logging
logger = logging.getLogger(__name__)

# Levels:
logger.debug("Resolved position: x=%.1f y=%.1f z=%.1f", x, y, z)    # internal state
logger.info("Placed %d items on %s", count, wall_name)                # pipeline progress
logger.warning("Unknown semantic term '%s' → fallback", term)         # recoverable issue
logger.error("Agent 3 API failed: %s", exc)                           # non-fatal error
```

Never use `print()` in production code. Only in ad-hoc scripts.

---

## 5. Constants & Magic Numbers

No bare numbers in logic. Every threshold is a named constant.

```python
# WRONG
if perimeter < 3962 or perimeter > 6600:
    ...

# CORRECT — in nkba_validator.py
WORK_TRIANGLE_MIN_MM = 3962  # 13 feet — official NKBA minimum
WORK_TRIANGLE_MAX_MM = 6600

if perimeter < WORK_TRIANGLE_MIN_MM or perimeter > WORK_TRIANGLE_MAX_MM:
    ...
```

All threshold constants belong in the module that uses them, grouped at the top below imports.

---

## 6. Async

All Claude API calls and MCP calls are `async`. Use `asyncio.gather` for parallel variant processing.

```python
# CORRECT — parallel Agent 3 calls
async def plan_variants(...) -> list[ZonePlannerOutput]:
    tasks = [self._plan_single(spatial, preprocessing, i+1) for i in range(n)]
    return await asyncio.gather(*tasks)
```

Never use `asyncio.run()` inside an async function. Use `await` directly.
Never block the event loop with synchronous I/O inside async functions — use `asyncio.to_thread()` for CPU-bound or sync code.

---

## 7. Module Size & Responsibility

Each module has exactly one responsibility:

| Module | Responsibility |
|--------|---------------|
| `spatial_engine.py` | Parse JSON → spatial facts. No LLM. |
| `placement_engine.py` | Semantic terms → mm coordinates. No LLM. |
| `nkba_validator.py` | Rules → score. No LLM. |
| `prompt_parser.py` | Prompt → IntentDTO. LLM only. |
| `catalog_selector.py` | Intent + MCP → SKU list. LLM + MCP only. |
| `layout_strategist.py` | Spatial + SKUs → zone strategy. LLM only. |
| `rationale_writer.py` | Placement + violations → text. LLM only. |
| `kitchen_graph.py` | Wire nodes into StateGraph. No LLM, no math. |

If a function is >60 lines, split it. If a module is >400 lines, split it.

---

## 8. DTOs (Data Transfer Objects)

All data crossing module boundaries must be a typed DTO from `dtos/contracts.py`.

```python
# WRONG — raw dict crossing boundary
def place(zone_plan: dict, ...) -> dict:
    ...

# CORRECT
def place(zone_plan: ZonePlannerOutput, ...) -> PlacementEngineOutput:
    ...
```

DTOs are dataclasses. They are not modified after creation — treat them as immutable.

---

## 9. Tests

Every module must have a matching test file:
- `pipeline/spatial_engine.py` → `tests/unit/test_spatial_engine.py`
- `agents/prompt_parser.py` → `tests/unit/test_prompt_parser.py` (mock Anthropic client)
- `pipeline/nkba_validator.py` → `tests/unit/test_nkba_validator.py` (pure math — no mocks needed)
- `graph/kitchen_graph.py` → `tests/integration/test_graph.py` (uses real API — run sparingly)

Minimum coverage:
- Unit tests: all pure-code modules (spatial, placement, nkba) — 100% branch coverage
- Agent tests: mock the Anthropic client, test DTO parsing logic only
- Integration tests: one end-to-end run on input1.json and input3.json

```bash
# Run unit tests (no API calls)
pytest tests/unit/ -v

# Run integration tests (uses API — charges apply)
pytest tests/integration/ -v --run-integration
```

---

## 10. Environment Variables

Never hard-code API keys. Use `.env` (gitignored) loaded by `python-dotenv`.

```python
# In any module that needs env vars
from dotenv import load_dotenv
import os

load_dotenv()
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]  # raises KeyError if missing — that's intentional
```

See `.env.example` for all required variables.

---

## 11. Docstrings

One-line docstring on every public class and method. No multi-paragraph essays.

```python
def parse(self, input_json: dict) -> SpatialEngineOutput:
    """Parse input JSON into walls, free segments, and layout capacity."""
```

Private methods (`_compute_free_segments`) need no docstring if the name is clear.

---

## 12. Formatting & Linting

Enforced via `pyproject.toml`. Run before every commit:

```bash
# Format
ruff format .

# Lint
ruff check .

# Type check
mypy . --ignore-missing-imports
```

All three must pass with zero errors before any PR is opened.
CI will run these automatically on push.
