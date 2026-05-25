---
name: testing-strategy
description: Use when writing tests, choosing where a test belongs, deciding what to mock, or verifying coverage for new pipeline modules. Covers unit/integration split, fixture governance, and test naming conventions.
version: 1.0.0
last_verified: 2026-05-24
applies_to:
  - tests/unit/
  - tests/integration/
  - tests/fixtures/sample_inputs.py
tool_risk: medium
---

# Testing Strategy Skill

## Purpose
Ensure every new feature has the right tests in the right place, using real fixture data, with no fake SKUs or live API calls in deterministic tests.

## When to Use
Writing any new test, adding test coverage for a new rule or module, or deciding whether a test is unit or integration.

## Existing Repo Pattern

**Unit tests** (`tests/unit/`): 8 test modules matching pipeline modules 1:1:
- `test_spatial_engine.py`, `test_preprocessor.py`, `test_zone_planner.py`
- `test_placement_engine.py`, `test_nkba_validator.py`, `test_output_generator.py`
- `test_kitchen_graph.py`, `test_model_selector.py`

**Integration tests** (`tests/integration/test_graph.py`): full pipeline, real API, marked `@pytest.mark.integration`

**Fixtures** (`tests/fixtures/sample_inputs.py`): reusable room specs and SKU data — all fixtures come from here, not inline in test files

**`conftest.py`** in `tests/unit/` provides shared pytest fixtures

**Run commands:**
```bash
pytest tests/unit/ -v                           # unit only (no API)
pytest tests/integration/ -v -m integration     # real API (charges apply)
```

## Rules
1. **Unit tests** go in `tests/unit/` — pure Python math, no API calls, **no mocks for math** (placement, NKBA scoring are deterministic — test the real function)
2. **Integration tests** go in `tests/integration/` — marked `@pytest.mark.integration`, use real API sparingly
3. **No fake SKUs inline** — all fixture SKU data comes from `tests/fixtures/sample_inputs.py`
4. **Every new NKBA rule** gets a unit test in `tests/unit/test_nkba_validator.py`
5. **Every new agent or graph node** gets an integration or graph-level test
6. **Test names describe behavior**: `test_work_triangle_below_minimum_fails` not `test_rule_3`
7. **Test both happy path AND failure/edge cases** — a test suite that only tests success is insufficient

## Bad Example
```python
# WRONG — fake SKU defined inline in test
def test_placement():
    sku = SKU(id="FAKE-BC-001", name="Test Cabinet", width_mm=600, ...)

# WRONG — mocks math that should be tested deterministically
@patch("pipeline.nkba_validator.compute_work_triangle")
def test_workflow_03(mock_triangle):
    mock_triangle.return_value = 5000  # hides real bugs
```

## Good Example
```python
# CORRECT — uses shared fixture
from tests.fixtures.sample_inputs import SAMPLE_SKU_BASE_CABINET

def test_base_cabinet_placed_at_left_end(sample_input):
    result = placement_engine.run(zone_plan, preprocessing, spatial)
    assert result.placed_items[0].x == 0.0  # left end of wall

# CORRECT — tests real function with edge case
def test_work_triangle_below_minimum_fails():
    spatial = make_tiny_kitchen(2000, 2000)  # too small
    result = nkba_validator.validate(placed, preprocessing, spatial)
    assert "WORKFLOW-03" in [v.rule_id for v in result.violations]
```

## Common Failure Modes
- New NKBA rule added without a unit test → rule is never verified to work
- Test relies on a fake SKU not in `catalog.json` → passes in test but fails with real data
- Integration test runs in CI without `@pytest.mark.integration` → charges API on every push

## Must Not Do
- Never use `@patch` to mock deterministic math (spatial, placement, NKBA scoring)
- Never add a new NKBA rule without adding a unit test for it
- Never define fake SKUs inline in test files

## Completion Checklist
- [ ] Unit tests in `tests/unit/` cover all new pure-Python logic
- [ ] Integration tests marked `@pytest.mark.integration`
- [ ] New NKBA rules have unit tests in `test_nkba_validator.py`
- [ ] Fixture data comes from `tests/fixtures/sample_inputs.py`
- [ ] Both happy-path and failure cases tested
- [ ] Test names describe behavior
