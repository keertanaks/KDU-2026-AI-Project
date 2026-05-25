# /review-impl — Review a feature implementation against the harness

## Quick Steps

1. Read `AGENTS.md` (non-negotiable rules section)
2. Read `checklists/pre-commit-checklist.md`
3. Read relevant skill files for this feature
4. Review the changed files against the harness rules
5. Report: violations, missing tests, risky assumptions, drift
6. Do NOT change any files unless explicitly asked

## What to Check
- No hardcoded model strings (must use `utils/model_selector.py`)
- No `print()` calls (must use `utils/logger.py`)
- No direct `catalog.json` reads (must use `mcp_server/server.py`)
- No fake/invented SKUs
- No bypassed `nkba_validator.py`
- No business logic in `ui/app.py` or `ui/components/`
- Agent 3 output uses only semantic vocabulary (no mm coordinates)
- DTOs from `dtos/contracts.py` used at all module boundaries
- Tests added for new logic
- `render.py` and `layout.py` untouched

## Output Format
See `review/pr-review-agent.md` for the full structured output format.

## Full Playbook
See `commands/review-implementation.md` for the complete workflow.

Now do the work described above.
