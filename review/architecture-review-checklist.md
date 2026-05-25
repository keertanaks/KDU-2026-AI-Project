# Architecture Review Checklist

Use for deeper architectural reviews — when a feature adds new modules, changes pipeline layering, or introduces new abstractions.

---

## Folder Placement
- [ ] New Python modules go in the correct folder (agents/, pipeline/, graph/, dtos/, mcp_server/, ui/, utils/)
- [ ] No new top-level module created without an ADR
- [ ] Harness-only files go in skills/, commands/, review/, decisions/ — not mixed with application code

## DTO Usage
- [ ] All inter-module data uses DTOs from `dtos/contracts.py`
- [ ] No bare `dict[str, Any]` passed across module boundaries where a DTO exists
- [ ] No DTO duplication in other files

## Pipeline Layering
- [ ] Layer responsibilities respected:
  - Layer 1 (spatial_engine.py): parse JSON → spatial facts, no LLM
  - Layer 2 (preprocessor.py + agents): prompt → intent + SKU selection, LLM only
  - Layer 3 (zone_planner.py + layout_strategist.py): semantic zone layout, LLM only
  - Layer 4 (placement_engine.py): semantic → mm coordinates, no LLM
  - NKBA (nkba_validator.py): rules → score, no LLM
  - Layer 5 (output_generator.py): serialize + render, no LLM
- [ ] No layer skipped (e.g., placement engine results consumed without validation)
- [ ] No layer doing another layer's work (e.g., spatial math in an agent)

## MCP / Catalog Boundaries
- [ ] All catalog access via `mcp_server/server.py` tools
- [ ] `mcp_server/catalog_loader.py` is the only file that reads `catalog.json`
- [ ] Color resolution goes through `mcp_server/color_resolver.py`

## Graph Wiring
- [ ] Every new module is wired into `graph/kitchen_graph.py` as a node
- [ ] `KitchenGraphState` extended in `dtos/contracts.py` before node code
- [ ] Sequential vs parallel structure preserved (Layers 1–2 sequential; Layers 3–5 parallel per variant)

## Validator Usage
- [ ] `pipeline/nkba_validator.py` is the ONLY place scoring runs
- [ ] No inline NKBA checks duplicated in other modules

## UI Separation
- [ ] `ui/app.py` and `ui/components/` contain zero business logic
- [ ] Display data prepared before reaching UI

## Protected Files
- [ ] `render.py` and `layout.py` untouched or ADR filed
- [ ] `catalog.json` untouched or ADR filed
- [ ] `CLAUDE.md`, `CODING_STANDARDS.md`, `AGENT_SPECS.md` untouched

## No Duplicated Services or Utilities
- [ ] No new logger created — all use `utils/logger.py`
- [ ] No new model selector created — all use `utils/model_selector.py`
- [ ] No second MCP server or catalog loader
