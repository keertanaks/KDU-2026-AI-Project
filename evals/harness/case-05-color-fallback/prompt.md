# Eval Case 05 — Color Fallback

Read AGENTS.md at the repo root before doing anything else.

---

## Feature Request

Harden the color resolution path to gracefully handle cases where a user requests a color that has no exact SKU match in the catalog.

Specifically, when a user requests "dark grey" (or any color keyword not in `COLOR_KEYWORD_HEX` in `agents/prompt_parser.py` and not exactly matched by `mcp_server/color_resolver.py`):

1. The system must NOT crash or raise an unhandled exception
2. The system must NOT invent a fake SKU to satisfy the request
3. The system must return the nearest available catalog color match (using delta-E distance in `mcp_server/color_resolver.py`)
4. The nearest match must be flagged with a clear warning visible to the user: "Requested color 'dark grey' not available — using nearest match: [matched color name] ([hex]) SKU: [sku_id]"
5. The warning must appear in `VariantSummaryDTO.warnings[]` and be displayed in the Streamlit UI

## Instructions

- Read AGENTS.md first
- Follow the full 12-step new-feature workflow from AGENTS.md
- Fill all three templates in `templates/` before writing any code
- Identify and read all relevant skill files
- Do NOT ask clarifying questions unless completely blocked
- Add a test that specifically exercises the "dark grey" fallback case
- Verify the fix works for any unrecognized color, not just "dark grey"

## Constraints

- `mcp_server/color_resolver.py` must handle unknown keywords without crashing
- Warning must appear in `VariantSummaryDTO.warnings[]`
- UI must display the warning (not swallow it)
- Resolved color must always map to a real SKU
- No invented SKUs
