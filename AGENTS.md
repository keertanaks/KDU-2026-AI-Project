# AGENTS.md — Kitchen-Layout-Visualizer Harness
## Harness v1.0.0 | 2026-05-24 | Router — do not inline skills here

---

## Project Overview

A 5-layer kitchen layout generation pipeline (Spatial Engine → Preprocessing → Zone Planner →
Placement Engine → Output) orchestrated by LangGraph, fronted by Streamlit, backed by an MCP
catalog server and NKBA constraint validation. Produces 3–5 differentiated layout variants with
NKBA compliance scores and rendered PNGs from a single room-specification JSON.

## Architecture

```
input.json → Layer 1 (spatial_engine.py) → Layer 2 (preprocessor.py: Agent1 + MCP + Agent2)
           → Layer 3 (zone_planner.py: Agent3 ×3–5 parallel)
           → Layer 4 (placement_engine.py ×3–5 parallel)
           → NKBA Validator (nkba_validator.py) ×3–5 parallel
           → Layer 5 (output_generator.py + render.py) ×3–5 parallel
           → output.json + PNGs → Streamlit UI (ui/app.py)
```

Sequential: Layer 1 → Layer 2. Parallel per-variant: Layers 3, 4, Validator, Output.

---

## Repo Structure

```
agents/           Agent 1–3 (plain Python classes; no services)
pipeline/         5 pipeline layer modules (pure math or LLM wrappers)
graph/            kitchen_graph.py — LangGraph StateGraph wiring
dtos/             contracts.py — all typed DTOs (single source of truth)
mcp_server/       server.py + catalog_loader.py + color_resolver.py
ui/               app.py + components/ (display only — no business logic)
utils/            logger.py, model_selector.py, openrouter_compat.py, rationale_lookup.py
llmops/           tracing, cost tracking, routing analytics, guardrails
tests/            unit/ (pure math) + integration/ (real API) + fixtures/
openspec/specs/   00_dtos.md … 10_streamlit_ui.md (per-module OpenAPI specs)
evals/harness/    Markdown eval cases (separate from evals/evaluators/ Python evals)
skills/           12 skill files — read BEFORE writing any code
templates/        3 spec templates — fill BEFORE writing any code
features/active/  per-feature work folders created during feature development
commands/         long-form workflow playbooks
.claude/commands/ slash-command mirrors (use inside Claude Code)
.claude/agents/   sub-agent definitions for isolated context tasks
review/           PR review agent + architecture, test, safety checklists
decisions/        MADR architecture decision records
docs/harness/     glossary, anti-patterns, context budgets, how-to guides
harness/          CHANGELOG.md (semver the harness itself)
```

---

## New-Feature Workflow (12 Steps — do not skip)

1. Read this file (AGENTS.md)
2. Understand the architecture above and relevant `openspec/specs/` files
3. Create `features/active/<feature-name>/`
4. Copy and fill all three templates (`templates/01-product-spec-template.md`, `02-technical-spec-template.md`, `03-implementation-plan-template.md`)
5. Identify relevant skills (see Skill Glossary below)
6. Read every relevant skill file in `skills/` — verify `last_verified` date
7. Create the implementation plan — do NOT write code until it is complete
8. Build the feature following existing project conventions (CODING_STANDARDS.md)
9. Run tests: `pytest tests/unit/ -v` then `pytest tests/integration/ -v -m integration`
10. Review the implementation against this harness (`commands/review-implementation.md`)
11. Fill `result-notes.md` if the work came from an `evals/harness/` case
12. Sharpen skills if the harness failed to guide correctly (`commands/sharpen-skill.md`)

**Always fill templates BEFORE writing any code.**
**Always read relevant skill files BEFORE writing any code.**
**Use `commands/` for repeatable workflows. Use `review/` for PR and implementation review.**
**Use `.claude/commands/` slash commands inside Claude Code.**

---

## Skill Glossary (12 skills — read the file, not this line)

| Skill | File | When to Read |
|-------|------|--------------|
| catalog | `skills/catalog.md` | Any SKU retrieval, price/cost, catalog query |
| color-resolution | `skills/color-resolution.md` | Any color keyword, hex, or material matching |
| layout-typology | `skills/layout-typology.md` | L/U/I/island shape selection, variant seeding |
| constraint-validation | `skills/constraint-validation.md` | NKBA rules, scoring, work triangle, clearances |
| variant-generation | `skills/variant-generation.md` | Parallel variants, seeds, retry, spillover |
| continuous-run | `skills/continuous-run.md` | Cabinet flush, gap detection, corner handling |
| rendering | `skills/rendering.md` | render.py/layout.py output, PlacedItem schema |
| langgraph-workflow | `skills/langgraph-workflow.md` | Graph nodes, edges, state, retry wiring |
| dto-contracts | `skills/dto-contracts.md` | DTO reuse, KitchenGraphState changes |
| testing-strategy | `skills/testing-strategy.md` | Unit/integration split, fixtures, coverage |
| ui-integration | `skills/ui-integration.md` | Streamlit components, business logic boundary |
| llm-routing-and-observability | `skills/llm-routing-and-observability.md` | Model routing, logging, llmops/ |

---

## Non-Negotiable Rules

- Never hard-code model strings — use `utils/model_selector.py`
- Never use `print()` — use `utils/logger.py` (`get_logger(__name__)`)
- Never modify `catalog.json`, `render.py`, or `layout.py` without a `decisions/` ADR
- Never bypass DTOs, MCP server, NKBA validator, graph wiring, or logger
- Business logic must NOT live in Streamlit UI components (`ui/`)
- Every generated variant MUST pass `nkba_validator.py` before being returned
- Never invent SKUs — only use what `mcp_server/server.py` returns
- Agent 3 outputs SEMANTIC vocabulary only — never mm coordinates
- All Claude API calls must be wrapped in `try/except` returning a valid fallback DTO
- Run `ruff format . && ruff check . && mypy .` before every commit

## Repo-Specific Architectural Rules

- `dtos/contracts.py` is the contract layer — extend it, never duplicate elsewhere
- `graph/kitchen_graph.py` wires all nodes — no pipeline logic outside the graph
- `mcp_server/server.py` is the ONLY entry point to `catalog.json`
- `pipeline/nkba_validator.py` is the ONLY place NKBA scoring runs
- `utils/rationale_lookup.py` drives rationale text — no LLM rationale calls
- WORKFLOW-03 minimum is 3962mm (13 ft) — not 3600mm
- Variant seeds are fixed per CLAUDE.md table — never invent new seeds ad hoc

## Testing & Eval Expectations

- Unit tests go in `tests/unit/` — pure math, no API calls, no mocks for math
- Integration tests go in `tests/integration/` — real API, marked `@pytest.mark.integration`
- Fixtures live in `tests/fixtures/sample_inputs.py` — no fake SKUs inline in tests
- Every new NKBA rule needs a unit test in `tests/unit/test_nkba_validator.py`
- Harness Markdown evals live in `evals/harness/` — separate from Python evals

## Context-Budget Reminder

- This file: ≤200 lines — never inline a skill body here, always point
- Each skill body (excl. frontmatter): ≤1000 tokens
- Each checklist: ≤80 lines
- Each filled template: ≤200 lines

---

## References

- `AGENT_SPECS.md` — legacy Agent 1–4 runtime specifications
- `CLAUDE.md` — architecture, LangGraph state, variant seeds, scoring formula
- `CODING_STANDARDS.md` — type hints, error handling, module size, DTO rules
- `openspec/specs/` — per-module OpenAPI/prose specs (00_dtos.md … 10_streamlit_ui.md)
- `docs/harness/glossary.md` — NKBA terms, semantic vocabulary, zone/scoring reference
- `docs/harness/anti-patterns.md` — known failure modes and their fixes
- `docs/harness/context-budget.md` — hard limits enforced at PR review
- `docs/harness/fresh-chat-starter.md` — copy-paste bootstrap for new chat sessions
