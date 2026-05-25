# Implementation Plan — [Feature Name]

> **Do not write any code until this plan is fully filled out and reviewed.**
> Every step must be specific. "Update nkba_validator.py" is not specific.
> "Add WALKWAY-01 rule at line ~120 of nkba_validator.py with weight=0.10" is specific.

---

## Pre-Implementation Checklist (complete before step 1)
- [ ] Read AGENTS.md
- [ ] Read CLAUDE.md
- [ ] Read CODING_STANDARDS.md
- [ ] Filled 01-product-spec.md
- [ ] Filled 02-technical-spec.md
- [ ] Identified relevant skills (list below)
- [ ] Read every relevant skill file and checked last_verified date
- [ ] Inspected existing code in all files I plan to touch

## Relevant Skills Read
- [ ]
- [ ]

## Files I Will Inspect Before Writing
- [ ]
- [ ]

---

## Step 1 — Confirm Scope and Re-Read Relevant Skills
- Skills to re-read:
- Specific sections to focus on:
- Any ambiguity to resolve before proceeding:

## Step 2 — Inspect Existing Code Before Adding New Code
- Files to read first:
  - `dtos/contracts.py` lines ___–___ (relevant existing DTOs)
  - `pipeline/nkba_validator.py` lines ___–___ (existing rule pattern)
  - `graph/kitchen_graph.py` lines ___–___ (existing node wiring)
- Notes on what already exists that this feature extends:

## Step 3 — Update DTOs First (if needed)
- File: `dtos/contracts.py`
- Changes:
  ```python
  # Describe new fields or new dataclasses here
  ```
- Impact on existing callers:

## Step 4 — Update Catalog / MCP Layer (if needed)
- File(s): `mcp_server/server.py`, `mcp_server/catalog_loader.py`, `mcp_server/color_resolver.py`
- New tool(s) or function(s):
- Catalog query changes:

## Step 5 — Update or Add Agent Modules (if needed)
- Agent: `agents/<name>.py`
- Changes to system prompt:
- Changes to tool schema:
- Model route (use `utils/model_selector.py`):

## Step 6 — Update Pipeline Modules (if needed)
- File(s):
- Function(s) to add/modify:
- Constants to add at module top:
- No bare numbers in logic — named constants only

## Step 7 — Update Graph Wiring in graph/kitchen_graph.py (if needed)
- New node(s):
- New edge(s) or conditional:
- Changes to `KitchenGraphState`:
- Confirm every new module is wired in (nothing disconnected):

## Step 8 — Update UI (if needed)
- File(s): `ui/app.py`, `ui/components/<name>.py`
- New display elements:
- Confirm: NO business logic, NO placement math, NO validation calls in UI

## Step 9 — Add / Update Unit and Integration Tests
- Unit test file: `tests/unit/test_<module>.py`
  - New test cases:
  - Edge cases:
  - Failure paths:
- Integration test: `tests/integration/test_graph.py`
  - What end-to-end behavior to verify:
- Fixture data: `tests/fixtures/sample_inputs.py`
  - New fixture needed?

## Step 10 — Lint and Unit Test Gate
```bash
ruff format . && ruff check . && mypy . && pytest tests/unit/ -v
```
- Expected outcome: all pass
- If a test fails before my changes: document it here and open a separate issue

## Step 11 — Harness Eval Comparison (if from evals/harness/)
- Eval case: `evals/harness/<case>/`
- Compare output to `expected.md`
- Fill `result-notes.md`

## Step 12 — Review
- Run `/review-impl` or open `commands/review-implementation.md`
- Confirm all checklist items in `checklists/pre-commit-checklist.md`

## Step 13 — Sign-Off Gate

**STOP. Do not write any code until this step is complete.**

- [ ] Is this plan fully reviewed and approved?
- [ ] Does every step match the product/technical specs?
- [ ] Are all protected files (render.py, layout.py, catalog.json) untouched?
- [ ] Are all relevant skills referenced?

If all checked: Proceed to building. If not: revise the plan first.

---

## Risk Register
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| | | | |

## Open Questions
<!-- Anything unresolved before coding starts — resolve these first -->
-
