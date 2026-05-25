# Eval Case 02 — Style Transfer

Read AGENTS.md at the repo root before doing anything else.

---

## Feature Request

Build a style transfer feature for the Kitchen-Layout-Visualizer. When a user enters a style phrase like "Scandinavian minimalist" or "warm farmhouse", the system should:

1. Map the style phrase to a set of color/material keywords (e.g., "Scandinavian minimalist" → white, birch, light grey)
2. Use `mcp_server/color_resolver.py` and `mcp_server/server.py` to retrieve catalog SKUs that match those keywords
3. Constrain the variant generation to use only SKUs from the resolved palette
4. Display a style rationale in the Streamlit UI explaining what color/material palette was applied and why
5. If a required category has no matching palette SKU, fall back to the nearest color match (with a visible warning)

## Instructions

- Read AGENTS.md first
- Follow the full 12-step new-feature workflow from AGENTS.md
- Fill all three templates in `templates/` before writing any code
- Identify and read all relevant skill files
- Do NOT ask clarifying questions unless completely blocked
- The style → keyword mapping must be documented and deterministic (not LLM-based unless clearly scoped)
- Every resolved color must map to a real catalog SKU — never invent one

## Constraints

- Color resolution must go through `mcp_server/color_resolver.py`
- Catalog queries must go through `mcp_server/server.py`
- Style rationale must appear in the UI without business logic in the UI component
- Fallback to nearest color must add a visible warning
- No fake SKUs
