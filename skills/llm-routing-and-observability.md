---
name: llm-routing-and-observability
description: Use when adding any new LLM call, changing model assignments, or adding cost tracking. Every LLM call must be routed through utils/model_selector.py — never hard-code model strings.
version: 1.0.1
last_verified: 2026-05-24
applies_to:
  - utils/model_selector.py
  - utils/openrouter_compat.py
  - utils/logger.py
  - agents/prompt_parser.py
  - agents/catalog_selector.py
  - agents/layout_strategist.py
tool_risk: high
---

# LLM Routing and Observability Skill

## Purpose
Ensure all LLM calls use `utils/model_selector.py` for model selection and `utils/logger.py` for logging. No hardcoded model strings anywhere in feature code.

## When to Use
Any feature that adds a new LLM call, changes which model an agent uses, adds a new agent, or requires cost/latency tracking.

## Existing Repo Pattern

**`utils/model_selector.py`** — single source of truth:
```python
class Models:
    HAIKU = "claude-haiku-4-5-20251001"   # fast/cheap
    SONNET = "claude-sonnet-4-6"           # default workhorse
    OPUS = "claude-opus-4-7"               # retry escalation only

def for_agent(agent_name: str, is_retry: bool = False) -> str:
    ...  # returns correct model string for each agent

def should_use_opus(score: float, violation_ids: list[str]) -> bool:
    ...  # returns True if score < 0.60 OR violation_ids contain retry triggers
```

**Model assignments**:
| Agent | Primary | On Retry |
|-------|---------|----------|
| prompt_parser | Haiku | Haiku |
| catalog_selector | Haiku | Haiku |
| layout_strategist | Sonnet | Opus (score<0.60 OR WORKFLOW-03 OR NKBA-CL-01) |

**OpenRouter**: `utils/openrouter_compat.py` provides `OpenRouterCompat` for routing via OpenRouter. Set `OPENROUTER_API_KEY` in `.env` to activate. Set `TEST_MODE=1` to downgrade Agent 3 to Haiku (dev/test cost savings).

**Logging**: use `utils/logger.py` (`get_logger(__name__)`) — never `print()`.

**Prompt caching**: all agents use `{"type": "text", ..., "cache_control": {"type": "ephemeral"}}` on static system prompts to reduce cost ~10-20%.

## Rules
1. **Never hardcode model strings** in agent files or graph nodes — always use `for_agent()` or `should_use_opus()`
2. **Any new LLM call must document**: why it's needed, model route, fallback behavior, cost/latency controls, what is logged
3. **All Claude API calls are wrapped in `try/except`** returning a valid fallback DTO — never let API errors propagate to graph state
4. **New LLM behavior must be testable** without live model responses where possible (mock the Anthropic client)
5. **Prompt caching**: apply `cache_control: ephemeral` to static system prompts in all new agents

## Bad Example
```python
# WRONG — hardcoded model string
client.messages.create(model="claude-opus-4-7", ...)

# WRONG — no try/except around API call
result = await client.messages.create(...)  # can raise APIError → corrupts graph state

# WRONG — print() instead of logger
print(f"Agent response: {result}")
```

## Good Example
```python
# CORRECT — model via selector with retry escalation
from utils.model_selector import for_agent, should_use_opus
model = for_agent("layout_strategist")
if should_use_opus(variant_score, violation_ids):
    model = for_agent("layout_strategist", is_retry=True)

# CORRECT — try/except with valid fallback
try:
    result = await client.messages.create(model=model, ...)
except anthropic.APIError as e:
    logger.warning("layout_strategist API failed: %s — returning empty DTO", e)
    return ZonePlannerOutput(variant_id="", family=None, zone_assignments=[])

# CORRECT — structured logging
logger.info("layout_strategist completed: variant_id=%s", variant_id)
```

## Common Failure Modes
- New agent hardcodes `"claude-sonnet-4-6"` instead of using `for_agent()` → breaks when model names change
- API error propagates to LangGraph → graph state corrupted, entire pipeline fails
- Cost spikes because new agent calls Opus unconditionally instead of only on retry

## Must Not Do
- Never hardcode model names in any file other than `utils/model_selector.py`
- Never add an LLM call without documenting its model route and fallback
- Never use `print()` — use `utils/logger.py`

## Completion Checklist
- [ ] All model strings come from `utils/model_selector.py`
- [ ] All Claude API calls have `try/except` returning valid fallback DTO
- [ ] New agent documented: why, model route, fallback, cost controls, logging
- [ ] Static system prompts use prompt caching (`cache_control: ephemeral`)
- [ ] No `print()` calls — all logging via `utils/logger.py`
