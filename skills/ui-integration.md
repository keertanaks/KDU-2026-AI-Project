---
name: ui-integration
description: Use when making any change to ui/app.py or ui/components/. Governs the hard boundary between Streamlit display code and backend business logic — UI must never calculate, validate, or query catalog directly.
version: 1.0.0
last_verified: 2026-05-24
applies_to:
  - ui/app.py
  - ui/components/room_picker.py
  - ui/components/pipeline_log.py
  - ui/components/variant_card.py
  - ui/components/nkba_checklist.py
tool_risk: medium
---

# UI Integration Skill

## Purpose
Keep Streamlit UI components as pure display layers. Business logic, validation, and catalog queries live in `agents/`, `pipeline/`, `graph/`, `mcp_server/`, `utils/`, and `llmops/` — never in `ui/`.

## When to Use
Any feature that adds, modifies, or extends the Streamlit UI (`ui/app.py` or `ui/components/`).

## Existing Repo Pattern

**4 persona tabs** in `ui/app.py`:
- Tab 1: Designer — variant cards, 3D view
- Tab 2: Homeowner — visual layout, room picker
- Tab 3: Builder — NKBA checklist, constraint details
- Tab 4: PM — pipeline log, guardrail report

**Existing components in `ui/components/`:**
- `room_picker.py` — room dimension input
- `pipeline_log.py` — structured pipeline event display
- `variant_card.py` — per-variant summary display
- `nkba_checklist.py` — NKBA rule pass/fail checklist

**UI theme**: dark navy (`#0D1117`), teal accents (`#00D4B1`), score colors: green > 0.8, amber 0.6–0.8, red < 0.6.

**Data flow**: pipeline returns `FinalOutput` (from `dtos/contracts.py`); UI reads this DTO and renders it. UI does not re-run pipeline logic.

## Rules
1. **UI components display prepared data** — no placement calculations, NKBA scoring, or catalog queries
2. **No business logic in `ui/app.py` or `ui/components/`** — business logic belongs in `agents/`, `pipeline/`, `graph/`
3. **New reusable panels go under `ui/components/`** as separate files
4. **UI surfaces warnings, cost assumptions, and validation failures visibly** — never hide them
5. **Never apply UI-only fixes for pipeline/data issues** — if the rendered output is wrong, fix the data
6. **Test UI output without Streamlit running** — serialize `FinalOutput` to JSON and verify shape

## Bad Example
```python
# WRONG — placement calculation in UI component
# (in ui/components/variant_card.py)
def render_variant(placed_items):
    for item in placed_items:
        item["x"] = item["x"] + 50  # "fix" misaligned items in UI

# WRONG — catalog query in UI
# (in ui/app.py)
import json
with open("catalog.json") as f:
    catalog = json.load(f)
colors = [v["color_hex"] for v in catalog.values()]
```

## Good Example
```python
# CORRECT — UI reads prepared data from FinalOutput DTO
def render_variant_card(variant: VariantSummaryDTO) -> None:
    st.metric("Score", f"{variant.score:.2f}")
    if variant.warnings:
        for w in variant.warnings:
            st.warning(w)  # surface warnings visibly

# CORRECT — new panel as a separate component
# ui/components/design_report.py
def render_design_report(final_output: FinalOutput) -> None:
    ...
```

## Common Failure Modes
- Validation failure silently omitted from UI display → user never knows layout has issues
- Catalog query inside `st.cache_data` in `ui/app.py` → bypasses MCP abstraction
- `PlacedItem` coordinates adjusted in UI instead of fixing placement engine

## Must Not Do
- Never compute NKBA scores, work triangle, or clearances in UI code
- Never read `catalog.json` directly from `ui/`
- Never silently hide pipeline warnings or validation failures

## Completion Checklist
- [ ] UI reads `FinalOutput` DTO — no re-computation
- [ ] All warnings and validation failures surfaced to user
- [ ] New panels created as separate files in `ui/components/`
- [ ] No catalog reads or business logic in `ui/`
- [ ] UI testable without Streamlit running (serialize DTO, verify shape)
