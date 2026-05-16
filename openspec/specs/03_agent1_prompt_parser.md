# OpenSpec: Agent 1 — Prompt Parser
## File: `agents/prompt_parser.py`
## Branch: `feature/agent1`
## Design Doc: §5.1

---

## Goal
Extract structured kitchen design intent from a free-form user prompt.
Always returns a valid IntentDTO — never blocks generation.

## Model
`claude-haiku-4-5`

## Input
```python
prompt: str          # "I want navy blue base cabinets"
preferences: dict    # from input JSON preferences section
```

## Output
```python
IntentDTO  # from dtos.contracts
```

---

## Class Structure

```python
import anthropic
from dtos.contracts import IntentDTO

class PromptParser:
    MODEL = "claude-haiku-4-5"

    def __init__(self):
        self.client = anthropic.Anthropic()
        self._tools = [self._build_tool_schema()]
        self._system = self._build_system()  # cached once

    def parse(self, prompt: str, preferences: dict) -> IntentDTO:
        # Call API with tool_choice={"type": "tool", "name": "extract_intent"}
        # Parse tool_use block from response
        # Merge with preferences fallback
        # Return IntentDTO — never raise
```

---

## System Prompt

```
You are a kitchen design intent extractor.
Your task is to extract structured information from a user's kitchen design request.

Rules:
- NEVER fail or return an error — always extract best-effort information
- If a field cannot be determined from the prompt, set it to null and use the preferences JSON as fallback
- Extract kitchen-related requests ONLY — log non-kitchen requests in the "ignored" array
- Color keywords must be resolved to a hex code (you know common color names)
- Layout family: L (two walls), U (three walls), I (single wall run) — only set if the user explicitly mentions a shape

Always respond using the extract_intent tool.
```

Enable prompt caching on system message:
```python
{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}
```

---

## Tool Schema

```python
def _build_tool_schema(self) -> dict:
    return {
        "name": "extract_intent",
        "description": "Extract structured kitchen design intent from user prompt",
        "input_schema": {
            "type": "object",
            "properties": {
                "color_keyword": {
                    "type": ["string", "null"],
                    "description": "Color name from prompt, e.g. 'navy blue'"
                },
                "color_hex": {
                    "type": ["string", "null"],
                    "description": "Hex code resolved from color_keyword, e.g. '#1F3A5F'"
                },
                "layout_family": {
                    "type": ["string", "null"],
                    "enum": ["L", "U", "I", None],
                    "description": "Kitchen layout shape if explicitly mentioned"
                },
                "style": {
                    "type": ["string", "null"],
                    "enum": ["modern", "traditional", "minimalist", None]
                },
                "cabinet_preference": {
                    "type": ["string", "null"],
                    "enum": ["base_only", "with_uppers", "with_tall", None]
                },
                "special_requests": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "e.g. ['island', 'pantry']"
                },
                "ignored": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Non-kitchen requests from prompt, e.g. ['AC', 'TV']"
                }
            },
            "required": ["color_keyword", "color_hex", "layout_family", "style",
                         "cabinet_preference", "special_requests", "ignored"]
        }
    }
```

---

## Fallback Logic

After receiving tool output:
```python
def _merge_with_preferences(self, extracted: dict, preferences: dict) -> IntentDTO:
    return IntentDTO(
        color_keyword = extracted.get("color_keyword"),
        color_hex     = extracted.get("color_hex"),
        layout_family = extracted.get("layout_family"),
        style         = extracted.get("style") or preferences.get("style"),
        cabinet_preference = extracted.get("cabinet_preference"),
        special_requests = (extracted.get("special_requests") or []) +
                           preferences.get("must_have", []),
        ignored       = extracted.get("ignored", []),
    )
```

---

## Error Handling
Wrap API call in try/except. On any exception, return:
```python
IntentDTO(
    color_keyword=None, color_hex=None, layout_family=None,
    style=None, cabinet_preference=None, special_requests=[], ignored=[]
)
```
Log the error but do NOT raise.

---

## Validation
```bash
python -c "
from agents.prompt_parser import PromptParser
result = PromptParser().parse('I want navy blue base cabinets', {'budget_tier': 'mid'})
print('color_hex:', result.color_hex)
print('layout_family:', result.layout_family)
assert result.color_hex is not None, 'color_hex must be resolved'
print('PASS')
"
```
