# Eval Case 01 — Budget Optimizer

Read AGENTS.md at the repo root before doing anything else.

---

## Feature Request

Build an estimated budget optimizer for the Kitchen-Layout-Visualizer. When a user enters a target budget (e.g., "keep it under $18,000"), the system should:

1. Estimate the cost of each generated variant using a documented estimated price map (note: `catalog.json` has `price_tier` but no real prices — you MUST use a clearly documented estimated price map and label all cost output as "Estimated Cost")
2. For each variant, identify the most expensive items and suggest dimension-compatible lower price-tier substitutes from the actual catalog
3. Where possible, preserve the user's requested color and style when suggesting substitutes
4. Re-run NKBA constraint validation after any SKU substitution (a swap may change clearances or cabinet run continuity)
5. Show the cost delta and the impact on the NKBA score in the Streamlit UI

## Instructions

- Read AGENTS.md first
- Follow the full 12-step new-feature workflow from AGENTS.md
- Fill all three templates in `templates/` before writing any code
- Identify and read all relevant skill files
- Do NOT ask clarifying questions unless you are completely blocked by a missing definition
- Do NOT invent SKU prices — use documented estimated prices labeled "Estimated Cost"
- Do NOT invent SKUs to fill a gap — only substitute with real catalog entries
- After building, note which files were changed and which tests were added

## Constraints

- Budget feature must use `price_tier` from `catalog.json` with a documented estimated price map
- All cost figures in the UI must be labeled "Estimated Cost"
- SKU substitution must maintain cabinet run continuity (no new gaps > 50mm)
- NKBA validation must re-run after every substitution
- Color preservation should use `mcp_server/color_resolver.py`
