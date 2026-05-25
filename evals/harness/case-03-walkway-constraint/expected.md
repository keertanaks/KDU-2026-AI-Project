# Expected — Case 03: Walkway Constraint

## Expected Files Touched

**Modified files:**
- `features/active/walkway-constraint/01-product-spec.md` (new)
- `features/active/walkway-constraint/02-technical-spec.md` (new)
- `features/active/walkway-constraint/03-implementation-plan.md` (new)
- `pipeline/nkba_validator.py` — new rule function + constants + RULE_WEIGHTS entry
- `utils/rationale_lookup.py` — new rationale entry for NKBA-WW-01
- `tests/unit/test_nkba_validator.py` — new test cases

**Optionally modified:**
- `ui/components/nkba_checklist.py` — if NKBA-WW-01 needs explicit display

**Must NOT be touched:**
- `render.py`, `layout.py`, `catalog.json`, `CLAUDE.md`, `CODING_STANDARDS.md`

## Skills That Should Be Used

- [ ] `skills/constraint-validation.md` — how to add a new rule, weight, rationale entry
- [ ] `skills/testing-strategy.md` — unit test for new rule (no mocks for math)
- [ ] `skills/continuous-run.md` — walkway is affected by cabinet placement
- [ ] `skills/dto-contracts.md` — if VariantSummaryDTO needs a new field

## Required Workflow Steps

1. AGENTS.md read first
2. `features/active/walkway-constraint/` created, all three templates filled
3. Rule ID assigned (e.g., `NKBA-WW-01`)
4. Named constants defined at top of `nkba_validator.py`:
   - `WALKWAY_MIN_SINGLE_COOK_MM: float = 1067.0`
   - `WALKWAY_MIN_MULTI_COOK_MM: float = 1219.0`
5. Rule weight added to `RULE_WEIGHTS` dict
6. Check function added to `pipeline/nkba_validator.py`
7. Rationale entry added to `utils/rationale_lookup.py`
8. Unit tests added: one passing case (wide enough walkway) and one failing case (too narrow)
9. Scoring formula not modified

## Rules That Must Be Followed

- Rule ID must be unique (check existing IDs in `nkba_validator.py` first)
- No bare numbers in rule logic — named constants only
- WORKFLOW-03 minimum remains 3962mm — this is a different rule
- Scoring formula unchanged
- `render.py` untouched

## Tests That Must Be Added

- `test_nkba_validator.py::test_walkway_width_passes_single_cook` — walkway ≥ 1067mm → no violation
- `test_nkba_validator.py::test_walkway_width_fails_too_narrow` — walkway < 1067mm → NKBA-WW-01 violation
- `test_nkba_validator.py::test_walkway_multi_cook_threshold` — verify multi-cook uses 1219mm

## Forbidden Mistakes

- Bare numbers in rule logic (must use `WALKWAY_MIN_SINGLE_COOK_MM`)
- Confusing this rule with WORKFLOW-03 (different measurement)
- Adding NKBA-WW-01 to `nkba_validator.py` but forgetting the `RULE_WEIGHTS` entry
- Adding the check but skipping the `utils/rationale_lookup.py` entry

## Passing Criteria

- [ ] Templates filled before coding
- [ ] Named constants used (no bare 1067 or 1219 in logic)
- [ ] `RULE_WEIGHTS` entry added
- [ ] `utils/rationale_lookup.py` entry added
- [ ] Unit tests added (pass and fail cases)
- [ ] Scoring formula unchanged
- [ ] `render.py`, `layout.py`, `catalog.json` untouched
