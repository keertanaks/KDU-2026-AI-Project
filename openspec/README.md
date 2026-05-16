# OpenSpec — Auto-Design System

Each file in `specs/` is a complete implementation brief for one module.
Implement phases in order (00 → 10). Each phase must pass its validation test before the next begins.

## Spec Files

| File | Module | Phase |
|------|--------|-------|
| [00_dtos.md](specs/00_dtos.md) | DTOs + Data Contracts | 0 |
| [01_mcp_server.md](specs/01_mcp_server.md) | MCP Server (9 tools) | 1 |
| [02_spatial_engine.md](specs/02_spatial_engine.md) | Spatial Engine | 2 |
| [03_agent1_prompt_parser.md](specs/03_agent1_prompt_parser.md) | Agent 1 — Prompt Parser | 3 |
| [04_agent2_catalog_selector.md](specs/04_agent2_catalog_selector.md) | Agent 2 — Catalog Selector | 4 |
| [05_agent3_layout_strategist.md](specs/05_agent3_layout_strategist.md) | Agent 3 — Layout Strategist | 5 |
| [06_placement_engine.md](specs/06_placement_engine.md) | Placement Engine | 6 |
| [07_nkba_validator.md](specs/07_nkba_validator.md) | NKBA Validator + Scoring | 7 |
| [08_output_generator.md](specs/08_output_generator.md) | Agent 4 + Output Generator | 8 |
| [09_langgraph.md](specs/09_langgraph.md) | LangGraph Orchestration | 9 |
| [10_streamlit_ui.md](specs/10_streamlit_ui.md) | Streamlit UI (4 tabs) | 10 |

## Critical Rules
- Read CLAUDE.md before implementing anything
- NEVER modify: render.py, layout.py, catalog.json, input*.json
- ALL coordinates in mm
- Agent 3 outputs ZERO numbers — semantic terms only
- WORKFLOW-03 minimum: 3962mm (not 3600mm)
