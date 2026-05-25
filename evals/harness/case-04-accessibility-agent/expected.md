# Expected — Case 04: Accessibility Advisor Agent

## Expected Files Touched

**New files:**
- `features/active/accessibility-agent/01-product-spec.md`
- `features/active/accessibility-agent/02-technical-spec.md`
- `features/active/accessibility-agent/03-implementation-plan.md`
- `agents/accessibility_advisor.py`
- `ui/components/accessibility_report.py`
- `tests/unit/test_accessibility_advisor.py` (with mocked Anthropic client)
- `tests/integration/test_graph.py` (updated for new node)

**Modified files:**
- `dtos/contracts.py` — `AccessibilityReportDTO` added, `KitchenGraphState` extended
- `graph/kitchen_graph.py` — new node after `nkba_validator`

**Must NOT be touched:**
- `render.py`, `layout.py`, `catalog.json`

## Skills That Should Be Used

- [ ] `skills/langgraph-workflow.md` — new node wiring, KitchenGraphState extension
- [ ] `skills/llm-routing-and-observability.md` — model selector, try/except, prompt caching
- [ ] `skills/dto-contracts.md` — AccessibilityReportDTO before agent code
- [ ] `skills/testing-strategy.md` — mock Anthropic client in unit tests
- [ ] `skills/ui-integration.md` — new component display-only, no business logic

## Required Workflow Steps

1. AGENTS.md read first
2. Templates filled
3. `AccessibilityReportDTO` defined in `dtos/contracts.py` before any agent code
4. `KitchenGraphState` extended in `dtos/contracts.py` with `accessibility_reports` field
5. Agent uses `for_agent("accessibility_advisor")` from `utils/model_selector.py`
6. All API calls in `try/except` returning `AccessibilityReportDTO(issues=[], recommendations=[])`
7. Static system prompt uses `cache_control: ephemeral`
8. Node wired in `graph/kitchen_graph.py` after `nkba_validator`
9. UI panel created in `ui/components/accessibility_report.py` — reads from DTO, no computation
10. Unit tests mock Anthropic client, test DTO parsing
11. Integration test covers the new node in the graph

## Rules That Must Be Followed

- `AccessibilityReportDTO` in `dtos/contracts.py` BEFORE agent code written
- `for_agent()` used for model selection — no hardcoded model string
- `try/except` on all API calls
- Prompt caching applied to static system prompt
- New node registered in `graph/kitchen_graph.py`
- New UI component is display-only

## Tests That Must Be Added

- Unit test: mock Anthropic client → test DTO parsing from tool response
- Unit test: test fallback returns valid empty DTO on API error
- Integration test: verify node runs and produces valid AccessibilityReportDTO

## Forbidden Mistakes

- Hardcoded `"claude-sonnet-4-6"` or other model string in `accessibility_advisor.py`
- `AccessibilityReportDTO` defined in `accessibility_advisor.py` instead of `dtos/contracts.py`
- New agent not registered as a graph node (runs outside the graph)
- Accessibility logic computed in `ui/components/accessibility_report.py`
- No `try/except` around API call

## Passing Criteria

- [ ] Templates filled before coding
- [ ] DTO defined in `dtos/contracts.py` first
- [ ] Model via `for_agent()` only
- [ ] API call in `try/except`
- [ ] Node wired in graph
- [ ] UI component display-only
- [ ] Tests added (unit with mock + integration)
