# Eval Case 03 — Walkway Constraint

Read AGENTS.md at the repo root before doing anything else.

---

## Feature Request

Add a minimum walkway width as a first-class NKBA validation rule in `pipeline/nkba_validator.py`.

The rule: any walkway between a cabinet run and an island (or between two facing cabinet runs) must be at least 1067mm wide for a single-cook kitchen or 1219mm for a multi-cook kitchen.

Requirements:
1. Add the rule with a unique rule ID (e.g., `NKBA-WW-01`), a defined rule weight, and a check function in `pipeline/nkba_validator.py`
2. Add a rationale entry in `utils/rationale_lookup.py` explaining the rule in plain English
3. The rule must participate in the scoring formula defined in `CLAUDE.md`
4. Add a unit test in `tests/unit/test_nkba_validator.py` covering both pass and fail cases
5. Expose the rule violation (if any) in the Streamlit UI via the NKBA checklist

## Instructions

- Read AGENTS.md first
- Follow the full 12-step new-feature workflow from AGENTS.md
- Fill all three templates in `templates/` before writing any code
- Identify and read all relevant skill files
- Do NOT ask clarifying questions unless completely blocked
- The walkway width constants must be named constants, not bare numbers in logic

## Constraints

- New rule belongs in `pipeline/nkba_validator.py` ONLY
- New rationale entry belongs in `utils/rationale_lookup.py`
- Scoring formula in `CLAUDE.md` must not be changed
- `render.py` and `layout.py` must not be touched
- `catalog.json` must not be touched
