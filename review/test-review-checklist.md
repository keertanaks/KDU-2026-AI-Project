# Test Review Checklist

Use when reviewing test coverage for a new feature or after an eval failure exposes untested behavior.

---

## Test Location
- [ ] Unit tests in `tests/unit/test_<module>.py` (matching the module they test)
- [ ] Integration tests in `tests/integration/test_graph.py`
- [ ] New fixture data in `tests/fixtures/sample_inputs.py` (not inline in test files)

## Coverage
- [ ] New NKBA rule has a unit test in `tests/unit/test_nkba_validator.py`
- [ ] New agent module has tests (mock Anthropic client, test DTO parsing logic)
- [ ] New graph node has integration or graph-level test
- [ ] New MCP tool has fixture-based test

## Edge Cases and Failure Paths
- [ ] Tests cover both happy path and failure path
- [ ] Edge case: room too small for the requested layout
- [ ] Edge case: all variants score < 0.60 (retry triggered)
- [ ] Edge case: WORKFLOW-03 violated (retry triggered)
- [ ] Edge case: color keyword not found → nearest match returned with warning
- [ ] Edge case: SKU substitution creates a gap → LAYOUT-03 triggered

## Graph Behavior
- [ ] Retry edge tested: score < 0.60 triggers re-run
- [ ] Retry edge tested: second failure keeps variant with warnings[]
- [ ] Parallel variant production tested: 3 variants always produced

## UI-Safe Outputs
- [ ] `FinalOutput` serializes to valid JSON that `render.py` can consume
- [ ] Tests verify `PlacedItem` fields are present and correct types

## No Live LLM Dependency in Deterministic Tests
- [ ] `placement_engine.py` tests use no mocks (pure math — test the real function)
- [ ] `nkba_validator.py` tests use no mocks (pure math — test the real function)
- [ ] `spatial_engine.py` tests use no mocks (pure math — test the real function)
- [ ] Agent tests mock the Anthropic client — they test DTO parsing, not model output

## Test Naming
- [ ] Test names describe behavior: `test_dishwasher_placed_adjacent_to_sink`
- [ ] Not: `test_rule_02`, `test_case_1`, `test_placement`

## Markers
- [ ] Integration tests marked `@pytest.mark.integration`
- [ ] Slow tests (> 5s) marked `@pytest.mark.slow`
