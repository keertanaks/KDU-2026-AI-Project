# Drift Check Runbook

Monthly runbook for validating that skill files still accurately describe the current repo.

Run via `/drift-check` (which invokes `.claude/agents/drift-detector.md`).

---

## When to Run
- Monthly (suggested: first Sunday of the month)
- After any large refactor touching `pipeline/`, `agents/`, `dtos/`, or `mcp_server/`
- After merging a feature that adds new NKBA rules, renames modules, or changes DTO fields

---

## Manual Runbook (if drift-detector sub-agent is not available)

### Step 1 — File Path Verification
For each skill file in `skills/`, grep for mentioned file paths and confirm they exist:
```bash
# Example: check catalog.md references
grep -oE '[a-z_/]+\.py' skills/catalog.md | sort -u
# Then verify each path exists
```

Paths to verify across all skills:
- `mcp_server/server.py`, `mcp_server/catalog_loader.py`, `mcp_server/color_resolver.py`
- `pipeline/nkba_validator.py`, `pipeline/placement_engine.py`, `pipeline/zone_planner.py`
- `pipeline/spatial_engine.py`, `pipeline/preprocessor.py`, `pipeline/output_generator.py`
- `agents/prompt_parser.py`, `agents/catalog_selector.py`, `agents/layout_strategist.py`
- `graph/kitchen_graph.py`, `dtos/contracts.py`
- `utils/model_selector.py`, `utils/logger.py`, `utils/rationale_lookup.py`, `utils/openrouter_compat.py`

### Step 2 — NKBA Rule ID Verification
Grep `utils/rationale_lookup.py` for each rule ID mentioned in skills/:
```bash
grep -oE 'NKBA[-A-Z0-9]+|WORKFLOW-[0-9]+|LAYOUT-[0-9]+' skills/*.md | sort -u
```
Confirm each appears in `utils/rationale_lookup.py` as a key.

### Step 3 — Function/Class Name Verification
Key symbols that skills reference — confirm these still exist:
- `for_agent()` in `utils/model_selector.py`
- `should_use_opus()` in `utils/model_selector.py`
- `NKBAValidator` in `pipeline/nkba_validator.py`
- `PlacementEngine` in `pipeline/placement_engine.py`
- `KitchenGraphState` in `dtos/contracts.py`
- `get_logger()` in `utils/logger.py`
- `OpenRouterCompat` in `utils/openrouter_compat.py`
- `WORK_TRIANGLE_MIN_MM`, `FRIDGE_CLEARANCE_MM`, `DW_SINK_MAX_MM` in `pipeline/nkba_validator.py`

### Step 4 — Last-Verified Date Check
For each skill file, check `last_verified:` frontmatter:
```bash
grep -h 'last_verified:' skills/*.md
```
Flag any date older than 60 days from today.

### Step 5 — openspec/specs/ Cross-References
Skills may reference specs like `openspec/specs/07_nkba_validator.md`. Confirm each still exists.

### Step 6 — Decision Record Status
For each file in `decisions/`:
- Confirm `Status:` field is still accurate
- Flag decisions older than 180 days with `Status: Accepted` for review

---

## Output Format

```
DRIFT REPORT — <date>
=====================

STALE FILE REFERENCES
  skills/<name>.md → <path> [NOT FOUND]

STALE SYMBOL REFERENCES
  skills/<name>.md → <symbol>() [NOT FOUND in <file>]

STALE RULE IDs
  skills/<name>.md → <RULE-ID> [NOT IN rationale_lookup.py]

SKILLS DUE FOR RE-VERIFICATION (> 60 days)
  skills/<name>.md — last_verified: <date>

STALE DECISION RECORDS
  decisions/<adr>.md — Status: Accepted, age: <N> days

SUMMARY
  Issues found: <N>
  Action: run commands/sharpen-skill.md for stale skills
```

---

## After the Report
- For each stale file reference: run `/sharpen-skill` to update the skill
- For each old `last_verified` date: re-read the module and update the date + bump patch version
- Add a `DRIFT CHECK PASSED` or `DRIFT CHECK: N issues` note to `harness/CHANGELOG.md`
