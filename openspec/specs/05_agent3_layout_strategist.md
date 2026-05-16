# OpenSpec: Agent 3 — Layout Strategist
## File: `agents/layout_strategist.py`
## Branch: `feature/agent3`
## Design Doc: §5.3

---

## Goal
Plan semantic layout strategy for each variant — zone assignments and item order.
HARD CONSTRAINT: Output semantic terms ONLY. Zero coordinates. Zero numbers.

## Model
`claude-sonnet-4-6` primary / `claude-opus-4-7` on retry

## Input
```python
spatial: SpatialEngineOutput
preprocessing: PreprocessingOutput
n_variants: int = 3
layout_family: str | None = None  # from IntentDTO
retry_context: dict[str, list[str]] | None = None  # variant_id → violations
```

## Output
```python
list[ZonePlannerOutput]  # one per variant
```

---

## Class Structure

```python
import asyncio
import anthropic
from dtos.contracts import ZonePlannerOutput, SpatialEngineOutput, PreprocessingOutput

class LayoutStrategist:
    # Never hard-code model strings — use the selector
    # from utils.model_selector import for_agent, should_use_opus

    SEEDS = {
        1: "Prefer L-shape. Maximise counter run on the longest wall. Fridge at far end.",
        2: "Prefer U-shape. Close the work triangle tightly. Dishwasher opposite the sink wall.",
        3: "Prefer I-shape or island. Minimise total cabinet cost. Use narrower SKUs where possible.",
        4: "Maximise storage. Prioritise tall cabinets and wall cabinets over base units.",
        5: "Accessibility focus. Maximise aisle widths. No tall cabinets blocking circulation.",
    }

    VALID_TERMS = {
        "at north-west corner", "at north-east corner",
        "at south-west corner", "at south-east corner",
        "near {wall} window", "centre of {wall}",
        "left end of {wall}", "right end of {wall}",
        "next to {item_name}", "above {item_name}",
        "leave gap before {item_name}",
    }

    def __init__(self):
        self.client = anthropic.Anthropic()

    async def plan_variants(self, spatial: SpatialEngineOutput,
                            preprocessing: PreprocessingOutput,
                            n_variants: int = 3,
                            layout_family: str | None = None,
                            retry_context: dict | None = None) -> list[ZonePlannerOutput]:
        tasks = [
            self._plan_single(spatial, preprocessing, i+1, layout_family, retry_context)
            for i in range(n_variants)
        ]
        return await asyncio.gather(*tasks)
```

---

## Mode A vs Mode B

```python
def _build_seed_suffix(self, variant_index: int, layout_family: str | None) -> str:
    seed = self.SEEDS.get(variant_index, self.SEEDS[1])
    if layout_family:
        # Mode A: user specified shape — override seed's shape preference
        return f"Layout shape: {layout_family}-shape (user requested). {seed.split('.', 1)[1].strip()}"
    else:
        # Mode B: seed determines shape
        return seed
```

---

## System Prompt

```
You are a kitchen layout strategist. You plan where items go — not coordinates, just semantic positions.

CRITICAL RULES:
1. NEVER output any numbers, measurements, or coordinates
2. ONLY use the semantic vocabulary below — no free text
3. Plan zone assignments first, then item order per wall
4. Follow these placement rules:
   - Fridge and tall cabinets ALWAYS at corners or ends of walls
   - If window exists on a wall, place sink "near {wall} window"
   - Dishwasher ALWAYS "next to sink"
   - Hood ALWAYS "above stove"
   - Use "leave gap before fridge" to ensure separation from stove

SEMANTIC VOCABULARY (use ONLY these exact terms, substituting {wall} and {item_name}):
- "at north-west corner"
- "at north-east corner"
- "at south-west corner"
- "at south-east corner"
- "near {wall} window"
- "centre of {wall}"
- "left end of {wall}"
- "right end of {wall}"
- "next to {item_name}"
- "above {item_name}"
- "leave gap before {item_name}"

OUTPUT FORMAT (JSON only):
{
  "variant_id": "variant-N",
  "family": "L",
  "wall_strategies": {
    "north_wall": ["sink near north window", "dishwasher next to sink", "stove at right end of north_wall"],
    "east_wall": ["fridge at north-east corner", "tall cabinet next to fridge"]
  },
  "zone_assignments": {
    "cleaning": "north_wall",
    "cooling": "east_wall",
    "cooking": "north_wall",
    "preparation": "north_wall",
    "storage": "east_wall"
  }
}
```

---

## Retry System Prompt Extension

If retry_context provided for a variant:
```python
retry_addition = f"""
RETRY MODE: The previous plan for {variant_id} violated these rules:
{json.dumps(violations, indent=2)}

Re-plan to fix ALL violations listed above. Pay special attention to:
- Work triangle perimeter must be 3962mm–6600mm (WORKFLOW-03)
- Fridge must have 1067mm clear in front (NKBA-CL-01)
"""
```

---

## Output Validation

After receiving response, validate all semantic terms:
```python
def _validate_terms(self, plan: ZonePlannerOutput) -> ZonePlannerOutput:
    warnings = []
    for wall, strategies in plan.wall_strategies.items():
        validated = []
        for term in strategies:
            if self._is_valid_term(term):
                validated.append(term)
            else:
                warnings.append(f"Unknown term '{term}' on {wall} → replaced with 'left end of {wall}'")
                validated.append(f"left end of {wall}")
        plan.wall_strategies[wall] = validated
    return plan

def _is_valid_term(self, term: str) -> bool:
    for valid in self.VALID_TERMS:
        # template match: replace {wall} and {item_name} with any word
        pattern = re.escape(valid).replace(r"\{wall\}", r"\w+").replace(r"\{item_name\}", r"[\w\s]+")
        if re.fullmatch(pattern, term):
            return True
    return False
```

---

## Prompt Caching

Cache system message (static across all variants):
```python
{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}
```
Do NOT cache: seed suffix (variant-specific) or retry violations.

---

## Validation
```bash
python -c "
import asyncio
from agents.layout_strategist import LayoutStrategist
# Mock spatial and preprocessing outputs
# Expected: 3 variants, each with different wall_strategies, zero numbers in output
asyncio.run(test())
"
```
