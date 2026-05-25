# Expected — Case 06: Export Design Report

## Expected Files Touched

**New files:**
- `features/active/export-design-report/01-product-spec.md`
- `features/active/export-design-report/02-technical-spec.md`
- `features/active/export-design-report/03-implementation-plan.md`
- `pipeline/report_generator.py` OR `utils/report_generator.py` — report serialization logic
- `tests/unit/test_report_generator.py`

**Modified files:**
- `ui/app.py` OR `ui/components/variant_card.py` — download button only
- `dtos/contracts.py` — possibly a `DesignReportDTO` if needed

**Must NOT be touched:**
- `render.py`, `layout.py`, `catalog.json`, `utils/rationale_lookup.py` content (read-only)

## Skills That Should Be Used

- [ ] `skills/rendering.md` — PlacedItem fields, render path references
- [ ] `skills/dto-contracts.md` — DesignReportDTO if needed, FinalOutput usage
- [ ] `skills/ui-integration.md` — export trigger in UI, logic in pipeline/utils
- [ ] `skills/llm-routing-and-observability.md` — confirm no unnecessary LLM calls
- [ ] `skills/testing-strategy.md` — unit tests for serialization

## Required Workflow Steps

1. AGENTS.md read first
2. Templates filled
3. `utils/rationale_lookup.py` used for NKBA rationale text (read-only, no modifications)
4. Estimated cost: document the price map (or reference Case 01's map) and label "Estimated Cost"
5. Report generation logic in `pipeline/report_generator.py` or `utils/report_generator.py`
6. UI only triggers download — no report logic in `ui/app.py`
7. Tests cover JSON serialization and Markdown formatting

## Rules That Must Be Followed

- Report generation logic NOT in `ui/app.py` or `ui/components/`
- Estimated cost labeled "Estimated Cost"
- NKBA rationale text sourced from `utils/rationale_lookup.py`
- No new LLM calls (data serialization only)
- No new pipeline graph nodes needed (reads existing FinalOutput)

## Tests That Must Be Added

- `test_report_generator.py::test_json_export_contains_all_fields`
- `test_report_generator.py::test_markdown_export_contains_nkba_rationale`
- `test_report_generator.py::test_estimated_cost_labeled_correctly`
- `test_report_generator.py::test_warnings_included_in_report`

## Forbidden Mistakes

- Report generation logic in `ui/app.py` (must be in pipeline/utils layer)
- Calling `nkba_validator.py` again in the report generator (reads existing data)
- Making an LLM call to generate the report narrative
- Omitting the "Estimated Cost" label on cost figures

## Passing Criteria

- [ ] Templates filled before coding
- [ ] Report logic in pipeline/utils layer, not UI
- [ ] NKBA rationale from `utils/rationale_lookup.py`
- [ ] Estimated cost labeled "Estimated Cost"
- [ ] No new LLM calls
- [ ] Tests for JSON and Markdown serialization
- [ ] UI is download-button-only (no business logic)
