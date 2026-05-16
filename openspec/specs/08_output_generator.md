# OpenSpec: Agent 4 + Output Generator
## Files: `agents/rationale_writer.py`, `pipeline/output_generator.py`
## Branch: `feature/output`
## Design Doc: §5.4, §3.1 Layer 5, §13.2

---

## Agent 4 — Rationale Writer

### Goal
Write plain-English explanations of each layout decision.
Reference NKBA rule IDs. Confirm color match. Flag violations.

### Model
`claude-haiku-4-5`

### Class Structure
```python
class RationaleWriter:
    MODEL = "claude-haiku-4-5"

    def __init__(self):
        self.client = anthropic.Anthropic()
        self._system = self._build_system()  # cached

    async def write(self, placement: PlacementEngineOutput,
                    validation: VariantSummaryDTO,
                    intent: IntentDTO) -> list[dict]:
        # Returns: [{"rule_id": str, "text": str}, ...]
```

### System Prompt
```
You are a kitchen design reviewer explaining layout decisions to a homeowner.
Write 1–2 sentence explanations for each decision.
Always reference the rule ID (e.g., LAYOUT-01).
If a violation exists, explain it clearly — do not hide it.
Confirm color match to the user's prompt.
Use plain English — no jargon.
```

### Output Schema
```json
[
  {"rule_id": "LAYOUT-01", "text": "The sink is centred under the north window (within 0mm) for natural light while washing up."},
  {"rule_id": "COLOR-MATCH", "text": "SKU-C11 (#1F3A5F) was selected — the closest catalog match to your 'navy blue' request."},
  {"rule_id": "WORKFLOW-03", "text": "The work triangle perimeter is 4,200mm — well within the 3,962–6,600mm recommended range."},
  {"rule_id": "NKBA-CL-01", "text": "The fridge has 1,200mm of clear space in front for comfortable door access."}
]
```

### Always Include
- Color match entry (rule_id: "COLOR-MATCH")
- Work triangle entry (rule_id: "WORKFLOW-03")
- Entry for every violation (so violations are visible in UI)
- Entry for every passed critical rule (NKBA-CL-01, WORKFLOW-01, WORKFLOW-02)

### Prompt Caching
Cache: system prompt + rationale templates (static)
Do NOT cache: placement data or violations (unique per variant)

---

## Output Generator

### Goal
Merge all outputs, sort by score, write output.json, trigger render.py.

### File: `pipeline/output_generator.py`

### Class Structure
```python
import json
import subprocess
import uuid
import time
from pathlib import Path
from dtos.contracts import FinalOutput, VariantSummaryDTO

class OutputGenerator:
    def __init__(self, out_dir: str = "renders"):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(exist_ok=True)

    def generate(self, validated_variants: list[VariantSummaryDTO],
                 input_json: dict,
                 start_time: float) -> FinalOutput:
        # Sort by score descending
        sorted_variants = sorted(validated_variants, key=lambda v: v.score, reverse=True)

        # Build render.py-compatible layout dict for each variant
        for v in sorted_variants:
            v.layout = self._build_layout_dict(v, input_json)
            v.environment = input_json["environment"]

        duration_ms = (time.time() - start_time) * 1000

        final = FinalOutput(
            request_id=str(uuid.uuid4()),
            duration_ms=duration_ms,
            layouts=sorted_variants,
        )

        # Write output.json
        self._write_output_json(final)

        # Render all variants
        self._render_all(final)

        return final
```

### Layout Dict Builder

output.json layout format must match render.py expectations exactly:
```python
def _build_layout_dict(self, variant: VariantSummaryDTO, input_json: dict) -> dict:
    layout = {}

    # Add walls
    for wall in input_json["environment"]["wall"]:
        layout[wall["name"]] = {
            "is_wall": True,
            "position_mm": {"x": wall["points"][0]["x"], "y": wall["points"][0]["y"], "z": 0},
            "dimensions_mm": {"width": wall["dimensions"]["length_mm"],
                               "depth": wall["thickness_mm"],
                               "height": wall["dimensions"]["height"]},
            "rotation_z_deg": 0,
        }

    # Add placed items
    for item_name, item in variant.positioned_items.items():
        layout[item_name] = {
            "is_wall": False,
            "product_id": item.sku_id,
            "position_mm": item.position_mm,
            "dimensions_mm": item.dimensions_mm,
            "rotation_z_deg": item.rotation_z_deg,
            "anchor_wall": item.anchor_wall,
            "zone_type": item.zone_type,
        }

    return layout
```

### Render Trigger

```python
def _render_all(self, final: FinalOutput):
    # Write output.json first
    output_path = Path("output.json")
    with open(output_path, "w") as f:
        json.dump(self._to_render_envelope(final), f, indent=2)

    # Call render.py via subprocess
    result = subprocess.run(
        ["python", "render.py", str(output_path),
         "--out-dir", str(self.out_dir), "--2d-only"],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        print(f"WARNING: render.py stderr: {result.stderr}")
```

### Render Envelope Format
```python
def _to_render_envelope(self, final: FinalOutput) -> dict:
    return {
        "request_id": final.request_id,
        "duration_ms": final.duration_ms,
        "layouts": [
            {
                "id": v.variant_id,
                "family": v.family,
                "score": v.score,
                "environment": v.environment,
                "layout": v.layout,
            }
            for v in final.layouts
        ]
    }
```

---

## Validation
```bash
# Run output generator end-to-end
python -c "
from pipeline.output_generator import OutputGenerator
# Create mock VariantSummaryDTO with positioned_items
# Call generate()
# Assert output.json written
# Assert renders/variant-1_top.png exists
"
```
