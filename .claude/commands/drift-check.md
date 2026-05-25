# /drift-check — Scan skill files for stale references

## Quick Steps

This command invokes the `drift-detector` sub-agent (see `.claude/agents/drift-detector.md`).

1. The drift-detector scans all files in `skills/` for:
   - File paths that no longer exist in the repo
   - Function/class names that have been renamed
   - NKBA rule IDs not found in `utils/rationale_lookup.py` or `pipeline/nkba_validator.py`
   - `last_verified:` dates older than 60 days
   - `openspec/specs/` cross-references that are stale
2. Returns a drift report
3. For each stale reference: open an issue or run `/sharpen-skill` on the affected skill

## When to Run
- Monthly (see `review/drift-check.md` for the full runbook)
- After any large refactor touching `pipeline/`, `agents/`, `dtos/`, or `mcp_server/`
- After merging a feature that added new NKBA rules or renamed modules

## Full Runbook
See `review/drift-check.md` for the complete monthly drift-check procedure.

Now invoke the drift-detector sub-agent to perform the scan.
