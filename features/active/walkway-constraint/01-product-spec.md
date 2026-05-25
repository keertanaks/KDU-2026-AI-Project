# Product Spec — walkway-constraint

> Fill every field before writing a single line of code.
> Leave no field blank — write "N/A" with a reason if truly not applicable.

---

## Feature Name
`walkway-constraint`

## User / Persona
All four persona tabs (Designer, Homeowner, Builder, PM) — the NKBA checklist in the NKBA tab
is surfaced to every persona.

## User Problem
The pipeline does not currently enforce minimum walkway widths between facing cabinet runs (or
between a cabinet run and an island). A kitchen layout can be approved with a dangerously narrow
corridor between the island and the counter wall, violating NKBA guidelines. Designers and
builders need explicit, rule-driven feedback so they can widen the gap or remove the island
before fabrication.

## Use Case
1. User submits a room spec with an island or U-shape layout where facing runs exist.
2. The pipeline runs the NKBA validator on each variant.
3. The validator detects the facing cabinet runs, computes the walkway gap, and compares it
   against the cook-count-specific minimum (1067mm single-cook, 1219mm multi-cook).
4. If the gap is too narrow, `NKBA-WW-01` is added to the violations list.
5. The Streamlit UI renders `NKBA-WW-01` as a failing rule in the NKBA checklist component
   (red ❌, shows measured vs. required mm).
6. The score is penalised by the rule's weight (0.10).

## Success Criteria
1. `NKBA-WW-01` fires correctly when walkway < 1067mm (single-cook) or < 1219mm (multi-cook).
2. `NKBA-WW-01` does NOT fire when walkway is adequate.
3. The violation and plain-English rationale appear in the NKBA checklist in the UI.

## Non-Goals
- This feature does not automatically adjust layout to fix the walkway (that is Agent 3's job
  via the retry path).
- This feature does not add a new walkway measurement to the 3D viewer.

## Inputs
- `PlacementEngineOutput` (positioned items with wall assignments and dimensions)
- `SpatialEngineOutput` (walls with anchor directions and points)
- `PreprocessingOutput` (nkba_constraints dict, expected key: `"num_cooks"`, default 1)

## Outputs
- If violated: `{"rule_id": "NKBA-WW-01", "text": "Walkway NNNmm < MMMmm (single/multi-cook)"}` appended to the `violations` list inside `VariantSummaryDTO`.
- Rationale entry populated from `utils/rationale_lookup.py`.
- Score reduced by 0.10 weight penalty.
- UI checklist row shows ❌ with measured vs. required value.

## Existing Workflow Affected
- Layer 1 (spatial_engine.py): [ ] touched
- Layer 2 (preprocessor.py / agents): [ ] touched
- Layer 3 (zone_planner.py / layout_strategist.py): [ ] touched
- Layer 4 (placement_engine.py): [ ] touched
- NKBA Validator (nkba_validator.py): [x] touched
- Layer 5 (output_generator.py): [ ] touched
- Graph wiring (kitchen_graph.py): [ ] touched
- UI (ui/app.py, ui/components/): [x] touched — nkba_checklist.py only

## Acceptance Criteria
- [ ] Named constants `WALKWAY_MIN_SINGLE_COOK_MM = 1067.0` and `WALKWAY_MIN_MULTI_COOK_MM = 1219.0` in `nkba_validator.py`.
- [ ] `"NKBA-WW-01": 0.10` in `RULE_WEIGHTS`.
- [ ] Rule fires on too-narrow walkway; does not fire on adequate walkway.
- [ ] `utils/rationale_lookup.py` has a `"NKBA-WW-01"` entry.
- [ ] 3 unit tests added and passing.
- [ ] UI checklist shows the rule.
- [ ] `render.py`, `layout.py`, `catalog.json`, `CLAUDE.md` untouched.

## Edge Cases
- Single-wall kitchen with no island and no facing run → rule must NOT fire (return None from helper).
- Island present but no wall run → rule must NOT fire (no facing pair).
- `num_cooks` missing from `nkba_constraints` → default to 1 (single-cook).
- Items with z >= 500mm (wall cabinets) must not count toward walkway computation.

## Risks
- `_room_depth` only gives Y-extent; east/west facing pair needs X-extent computation.
- Over-eager firing if helper does not correctly skip no-facing-pair scenarios.

## Relevant Skills to Read Before Coding
- [x] skills/constraint-validation.md
- [x] skills/testing-strategy.md
- [x] skills/continuous-run.md
- [x] skills/dto-contracts.md

## Expected Eval Case (if applicable)
`evals/harness/case-03-walkway-constraint/`
