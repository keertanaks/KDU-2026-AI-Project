# Pre-Commit Checklist

Complete before opening any PR or merging any branch. All items must pass.

---

## SKU and Catalog Integrity
- [ ] No fake/invented SKUs in any file (code, tests, fixtures, JSON)
- [ ] No direct `catalog.json` reads in agents, pipeline, or UI — all via `mcp_server/server.py`
- [ ] Any budget/cost feature labels output as "Estimated Cost" with a documented price map

## LLM Routing
- [ ] No hardcoded model strings — all model selection via `utils/model_selector.py`
- [ ] All new Claude API calls have `try/except` returning a valid fallback DTO

## Logging
- [ ] No `print()` statements anywhere in production code — all via `utils/logger.py`

## Protected Files
- [ ] `render.py` — untouched
- [ ] `layout.py` — untouched
- [ ] `catalog.json` — untouched (or ADR filed in `decisions/`)
- [ ] `CLAUDE.md` — untouched
- [ ] `CODING_STANDARDS.md` — untouched
- [ ] `AGENT_SPECS.md` — untouched
- [ ] `IMPLEMENTATION_PLAN.md` — untouched
- [ ] `System_Design_and_Learnings.md` — untouched

## DTOs and Contracts
- [ ] DTOs from `dtos/contracts.py` used at all module boundaries — no loose dicts
- [ ] `KitchenGraphState` changes defined in `dtos/contracts.py` before node code
- [ ] No duplicate DTO definitions in non-contracts files

## Validation
- [ ] Every generated variant passes through `pipeline/nkba_validator.py` before being returned
- [ ] WORKFLOW-03 minimum is 3962mm (not 3600mm) if constraint code was touched
- [ ] Collision whitelist respected (hood↔stove, tap↔sink, wall_cab↔base_cab, dw↔base_cab)

## Graph Wiring
- [ ] New pipeline step registered as a node in `graph/kitchen_graph.py`
- [ ] MCP/catalog abstraction respected — no direct JSON reads

## UI
- [ ] No business logic, no placement math, no catalog queries in `ui/app.py` or `ui/components/`
- [ ] All pipeline warnings and validation failures surfaced visibly in UI

## Agent 3 Output
- [ ] Agent 3 outputs only semantic vocabulary — no mm coordinates in zone plans

## Tests
- [ ] Tests added or updated for all new logic
- [ ] New NKBA rules have unit tests in `tests/unit/test_nkba_validator.py`
- [ ] Integration tests marked `@pytest.mark.integration`
- [ ] No fake SKUs in test files — all from `tests/fixtures/sample_inputs.py`

## Linting Gate
- [ ] `ruff format .` — passes
- [ ] `ruff check .` — passes (zero errors)
- [ ] `mypy .` — passes (zero errors)
- [ ] `pytest tests/unit/ -v` — all pass (or failures documented with open issue)

## Feature Alignment
- [ ] Implementation still matches `features/active/<name>/03-implementation-plan.md`
- [ ] `result-notes.md` filled if this came from an `evals/harness/` case

## Context Budget
- [ ] No skill inlined into `AGENTS.md` — all content points to `skills/`
- [ ] `AGENTS.md` still ≤ 200 lines
