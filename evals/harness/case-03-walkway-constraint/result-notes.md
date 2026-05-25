# Result Notes — Case 03: Walkway Constraint

## Date
2026-05-24

## Tool Used
Claude Code (claude-sonnet-4-6) via /run-eval

## Prompt Used
`evals/harness/case-03-walkway-constraint/prompt.md` — no modifications

## What Passed

- [x] AGENTS.md read first
- [x] `features/active/walkway-constraint/` created and all three templates filled before coding
- [x] All 4 relevant skills read (`constraint-validation`, `testing-strategy`, `continuous-run`, `dto-contracts`)
- [x] Named constants `WALKWAY_MIN_SINGLE_COOK_MM = 1067.0` and `WALKWAY_MIN_MULTI_COOK_MM = 1219.0` added to `pipeline/nkba_validator.py`
- [x] `RULE_WEIGHTS["NKBA-WW-01"] = 0.10` added
- [x] `_check_nkba_ww_01` check function added (project rules section, #12)
- [x] `_compute_facing_walkway` helper added (N/S pair → E/W pair → island fallback, returns None for single-wall)
- [x] `total_rules` updated from 31 → 32
- [x] `utils/rationale_lookup.py` entry added for `NKBA-WW-01`
- [x] `ui/components/nkba_checklist.py` updated with `NKBA-WW-01` row (weight=0.10, appears in Project Rules expander)
- [x] 3 unit tests added: `test_walkway_width_passes_single_cook`, `test_walkway_width_fails_too_narrow`, `test_walkway_multi_cook_threshold`
- [x] `pytest tests/unit/ -v` → 38/38 pass (no regressions)
- [x] Scoring formula in `CLAUDE.md` unchanged
- [x] `render.py`, `layout.py`, `catalog.json` untouched

## What Failed

None — full pass.

## Rules Violated

None — all AGENTS.md non-negotiable rules respected.

## Skills That Need Updates

None — all four skills guided correctly and completely:
- `constraint-validation.md` correctly described the 5-component checklist (ID, weight, fn, rationale, test)
- `testing-strategy.md` correctly guided both pass and fail test cases
- `continuous-run.md` correctly identified `Z_LEVEL_SPLIT_MM` for floor-level filtering
- `dto-contracts.md` correctly confirmed no DTO change needed

## Follow-Up Action

No skill sharpening needed. Eval is a full pass.
