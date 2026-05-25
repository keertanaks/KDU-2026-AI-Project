# Eval Case 06 — Export Design Report

Read AGENTS.md at the repo root before doing anything else.

---

## Feature Request

Build an exportable design report feature that allows a user to download a summary of their selected kitchen variant.

The design report should include:
1. Selected variant summary: variant ID, layout family (L/U/I), NKBA score, score color (green/amber/red per UI theme)
2. SKU list: each placed item's SKU ID, name, category, dimensions (width × depth × height mm), color hex
3. NKBA compliance summary: list of passed rules, list of violated rules with their rationale text (from `utils/rationale_lookup.py`)
4. Estimated cost (if available): total estimated cost labeled "Estimated Cost", using price_tier from catalog.json with a documented estimated price map
5. Warnings: any color fallbacks, spillover placements, or retry flags
6. Rendered image reference: the PNG filename for the selected variant (not the image itself — just the filename and render path)

The report should be exportable as JSON (always) and optionally as a formatted Markdown file.

## Instructions

- Read AGENTS.md first
- Follow the full 12-step new-feature workflow from AGENTS.md
- Fill all three templates in `templates/` before writing any code
- Identify and read all relevant skill files
- Do NOT ask clarifying questions unless completely blocked
- The report generator must use data already in `FinalOutput` / `VariantSummaryDTO` — no new pipeline calls
- Export logic goes in a new module or in `pipeline/output_generator.py`, NOT in `ui/app.py`

## Constraints

- Report generation logic in pipeline/utils layer, not in UI
- UI only triggers export and displays a download button
- Estimated cost must use the same documented price map as Case 01 (or reference it)
- NKBA rationale text comes from `utils/rationale_lookup.py`
- No LLM calls needed for this feature — it's a data serialization task
- No new pipeline stages required (reads from existing FinalOutput)
