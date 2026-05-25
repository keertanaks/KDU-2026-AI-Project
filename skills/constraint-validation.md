---
name: constraint-validation
description: Use when adding NKBA rules, modifying scoring, adding new constraint types, or touching pipeline/nkba_validator.py. Critical — misuse causes silent validation failures or incorrect scores.
version: 1.0.0
last_verified: 2026-05-24
applies_to:
  - pipeline/nkba_validator.py
  - utils/rationale_lookup.py
  - dtos/contracts.py
  - tests/unit/test_nkba_validator.py
tool_risk: high
---

# Constraint Validation Skill

## Purpose
Ensure all NKBA and workflow rules run through `pipeline/nkba_validator.py`, scores are computed correctly, and new rules are first-class citizens with weights, tests, and rationale entries.

## When to Use
Any feature touching NKBA rules, work triangle calculations, clearance checks, scoring, or constraint-driven retry logic.

## Existing Repo Pattern

**Key constants in `pipeline/nkba_validator.py`:**
```python
FRIDGE_CLEARANCE_MM: float = 1067.0     # NKBA-CL-01
DOOR_CLEAR_MM: float = 900.0            # NKBA-CL-02
DW_SINK_MAX_MM: float = 600.0           # LAYOUT-02
WORK_TRIANGLE_MIN_MM: float = 3962.0    # WORKFLOW-03 — 13 FEET, NOT 3600mm
WORK_TRIANGLE_MAX_MM: float = 6600.0    # WORKFLOW-03
```

**31 rules** live in `pipeline/nkba_validator.py`; rationale text for all rules is in `utils/rationale_lookup.py`.

**Scoring formula** (from `CLAUDE.md`):
```
SCORE = 1.0
+ (passed_NKBA / total_NKBA) × 0.30
- (spillover_count × 0.05)
- (adjacency_violations × 0.05)
- sum(RULE_WEIGHTS[v] for v in violations)
```

**Retry trigger** (in `graph/kitchen_graph.py`): score < 0.60 OR WORKFLOW-03 violated OR NKBA-CL-01 violated

**Collision whitelist** (do NOT flag as violations):
- `hood ↔ stove` (z-axis: hood above stove)
- `tap ↔ sink` (tap is sub-item of sink unit)
- `wall_cab ↔ base_cab` (z-axis: upper above lower)
- `dishwasher ↔ base_cab` (integrated panel, shared x boundary)

## Rules
1. **WORKFLOW-03 minimum is 3962mm** (13 feet, official NKBA). Using 3600mm is a critical bug
2. **Every variant must be validated before being returned** — never skip `nkba_validator.py`
3. **New constraint rules must have**: a rule ID, a weight in `RULE_WEIGHTS`, a check function, a rationale entry in `utils/rationale_lookup.py`, and a unit test
4. **Validation failures must surface** — never silently swallow a violation
5. **Scoring formula must not be modified** without an ADR in `decisions/`

## Bad Example
```python
# WRONG — skips validation entirely
def run_pipeline(...):
    placed = placement_engine.run(...)
    return FinalOutput(variants=[placed])  # NO validator call!

# WRONG — wrong work triangle minimum
WORK_TRIANGLE_MIN_MM = 3600.0  # BUG: should be 3962mm
```

## Good Example
```python
# CORRECT — every variant is validated
validated = nkba_validator.validate(placed, preprocessing, spatial)
# CORRECT — correct constant name and value
WORK_TRIANGLE_MIN_MM: float = 3962.0  # 13 feet, NKBA official
```

## Common Failure Modes
- Using 3600mm for WORKFLOW-03 (copied from memory — always check `nkba_validator.py`)
- Adding a new rule without adding a `RULE_WEIGHTS` entry → score silently ignores it
- Adding a new rule without a `rationale_lookup.py` entry → rationale shows as empty string

## Must Not Do
- Never bypass `nkba_validator.py` for any variant
- Never use 3600mm for `WORK_TRIANGLE_MIN_MM`
- Never add a rule without a unit test in `tests/unit/test_nkba_validator.py`

## Completion Checklist
- [ ] Every variant passes through `nkba_validator.py` before being returned
- [ ] New rules have: rule ID, RULE_WEIGHTS entry, check function, rationale entry, unit test
- [ ] WORKFLOW-03 minimum is exactly 3962mm
- [ ] Scoring formula unchanged (or ADR filed)
- [ ] Collision whitelist respected
