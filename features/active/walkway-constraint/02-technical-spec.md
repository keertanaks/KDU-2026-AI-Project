# Technical Spec — walkway-constraint

> Fill every field before writing a single line of code.
> Reference real file paths from this repo — no generic placeholders.

---

## Pipeline Layers Affected

| Layer | File | Change Type | Description |
|-------|------|-------------|-------------|
| Layer 1 | pipeline/spatial_engine.py | none | No change |
| Layer 2 | pipeline/preprocessor.py | none | No change |
| Layer 2 | agents/prompt_parser.py | none | No change |
| Layer 2 | agents/catalog_selector.py | none | No change |
| Layer 3 | pipeline/zone_planner.py | none | No change |
| Layer 3 | agents/layout_strategist.py | none | No change |
| Layer 4 | pipeline/placement_engine.py | none | No change |
| NKBA | pipeline/nkba_validator.py | modify | Add constants, RULE_WEIGHTS entry, check function, helper |
| Layer 5 | pipeline/output_generator.py | none | No change |
| Utils | utils/rationale_lookup.py | modify | Add NKBA-WW-01 entry to RULE_EXPLANATIONS |
| UI | ui/components/nkba_checklist.py | modify | Add NKBA-WW-01 row to ALL_RULES |

## DTO / Data Contract Changes

No DTO changes. `VariantSummaryDTO.violations` already holds `list[dict[str, Any]]` and the new
rule uses the identical `{"rule_id": ..., "text": ...}` shape used by all other rules.

```python
# No changes to dtos/contracts.py
```

## MCP / Catalog Changes

No MCP changes.

## Agent Changes

No agent changes.

## LangGraph State and Graph Changes

No graph changes. The new rule runs inside `NKBAValidator.validate()` which is already called
by the graph. No new node, edge, or state field is needed.

```python
# No KitchenGraphState additions
```

## UI Changes

`ui/components/nkba_checklist.py` — add one entry to `ALL_RULES`:
```python
("NKBA-WW-01", "Walkway width -- >=1067mm single-cook, >=1219mm multi-cook", 0.10),
```
This appears in the "Project Rules (weighted)" expander since weight=0.10 > 0.

## Rendering / Output Changes

No rendering changes. The rule writes a violation dict; the existing serialization path handles it.

## Validation Requirements

| Rule ID | Weight | Condition | Rationale Text |
|---------|--------|-----------|----------------|
| NKBA-WW-01 | 0.10 | Walkway between facing cabinet runs (or island + run) < 1067mm (1 cook) or < 1219mm (2+ cooks) | Walkway between the island (or facing cabinet run) is narrower than the NKBA-required minimum. Single-cook kitchens need 1067mm; multi-cook kitchens need 1219mm for safe simultaneous use. |

**New constants** at top of `pipeline/nkba_validator.py` (after existing constants):
```python
WALKWAY_MIN_SINGLE_COOK_MM: float = 1067.0  # NKBA-WW-01 single-cook walkway minimum
WALKWAY_MIN_MULTI_COOK_MM: float  = 1219.0  # NKBA-WW-01 multi-cook walkway minimum
```

**New RULE_WEIGHTS entry** in `pipeline/nkba_validator.py`:
```python
"NKBA-WW-01": 0.10,
```

**New check function** `_check_nkba_ww_01(placed, spatial, preprocessing, violations)` in the
"11 Project rules" section (becoming 12 project rules).

**New helper** `_compute_facing_walkway(placed, spatial) -> float | None` in the Helpers section.

**`total_rules` updated** from 31 to 32.

## Logging / Observability Requirements

None beyond existing logging. The violation message includes measured vs. required mm.

## Testing Requirements

| Test File | Test Name | What It Tests |
|-----------|-----------|---------------|
| tests/unit/test_nkba_validator.py | test_walkway_width_passes_single_cook | Walkway 1800mm (> 1067mm) → no NKBA-WW-01 violation |
| tests/unit/test_nkba_validator.py | test_walkway_width_fails_too_narrow | Walkway 400mm (< 1067mm) → NKBA-WW-01 violation |
| tests/unit/test_nkba_validator.py | test_walkway_multi_cook_threshold | Walkway 1200mm passes single-cook but fails multi-cook (1219mm) when num_cooks=2 |

## Relevant Skills

- skills/constraint-validation.md — add rule ID, weight, check function, rationale entry
- skills/testing-strategy.md — unit test in test_nkba_validator.py, both pass and fail
- skills/continuous-run.md — walkway detection uses floor-level items (z < Z_LEVEL_SPLIT_MM)
- skills/dto-contracts.md — no DTO change needed; violation shape is unchanged

## Files Expected to Change

- `pipeline/nkba_validator.py`
- `utils/rationale_lookup.py`
- `ui/components/nkba_checklist.py`
- `tests/unit/test_nkba_validator.py`
- `features/active/walkway-constraint/` (this folder — templates)

## Files That MUST NOT Be Touched

- render.py
- layout.py
- catalog.json
- CLAUDE.md
- CODING_STANDARDS.md
- input1.json, input2.json, input3.json
- output.json, latest_run.json
- AGENT_SPECS.md

## Review Criteria

- Named constants `WALKWAY_MIN_SINGLE_COOK_MM` and `WALKWAY_MIN_MULTI_COOK_MM` present and
  correct (1067.0 and 1219.0).
- `RULE_WEIGHTS["NKBA-WW-01"] == 0.10`.
- `total_rules == 32`.
- `_compute_facing_walkway` returns `None` for single-wall layouts (no fire).
- All 3 unit tests pass with `pytest tests/unit/ -v`.
