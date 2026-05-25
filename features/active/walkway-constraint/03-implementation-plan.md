# Implementation Plan — walkway-constraint

> **Do not write any code until this plan is fully filled out and reviewed.**

---

## Pre-Implementation Checklist

- [x] Read AGENTS.md
- [x] Read CLAUDE.md
- [x] Read CODING_STANDARDS.md (via AGENTS.md reference)
- [x] Filled 01-product-spec.md
- [x] Filled 02-technical-spec.md
- [x] Identified relevant skills (see below)
- [x] Read every relevant skill file and checked last_verified date (all 2026-05-24)
- [x] Inspected existing code in all files I plan to touch

## Relevant Skills Read

- [x] skills/constraint-validation.md — pattern for new rule: constant + RULE_WEIGHTS + check fn + rationale entry + unit test
- [x] skills/testing-strategy.md — unit tests in tests/unit/, both pass and fail cases, no mocks for math
- [x] skills/continuous-run.md — floor-level items use z < Z_LEVEL_SPLIT_MM (500mm)
- [x] skills/dto-contracts.md — confirmed no DTO change needed; violation dict shape unchanged

## Files I Will Inspect Before Writing

- [x] `pipeline/nkba_validator.py` — examined existing constants, RULE_WEIGHTS, check pattern, helpers
- [x] `utils/rationale_lookup.py` — examined RULE_EXPLANATIONS dict structure
- [x] `tests/unit/test_nkba_validator.py` — examined _wall(), _spatial(), _item(), _placed() helpers
- [x] `ui/components/nkba_checklist.py` — examined ALL_RULES list structure

---

## Step 1 — Confirm Scope

- Skills re-read: constraint-validation, testing-strategy, continuous-run, dto-contracts
- Focus: new rule must have all 5 components (ID, weight, check fn, rationale, test)
- No ambiguity remaining

## Step 2 — Inspect Existing Code (done)

- `pipeline/nkba_validator.py` lines 28–99: existing constants and RULE_WEIGHTS
- `pipeline/nkba_validator.py` lines 133–145: validate() rule dispatch
- `pipeline/nkba_validator.py` lines 169: `total_rules = 31` (must become 32)
- `pipeline/nkba_validator.py` lines 1389–1396: `_min_aisle` helper (pattern reference)

Key finding: `_room_depth()` uses Y-extent only; E/W pairs need X-extent (handled in new helper).

## Step 3 — Update DTOs (skipped — no DTO change)

## Step 4 — Update Catalog / MCP Layer (skipped — no change)

## Step 5 — Update Agent Modules (skipped — no change)

## Step 6 — Update pipeline/nkba_validator.py

### 6a — Add constants after existing block (line ~52, after `LAYOUT04_ADJ_MM`):
```python
WALKWAY_MIN_SINGLE_COOK_MM: float = 1067.0  # NKBA-WW-01 single-cook walkway minimum
WALKWAY_MIN_MULTI_COOK_MM: float  = 1219.0  # NKBA-WW-01 multi-cook walkway minimum
```

### 6b — Add to RULE_WEIGHTS (line ~99, after existing entries):
```python
"NKBA-WW-01": 0.10,
```

### 6c — Add call in validate() after _check_layout_06 (project rules section):
```python
self._check_nkba_ww_01(placed, spatial, preprocessing, violations)
```

### 6d — Update total_rules (line ~169):
```python
total_rules = 32  # was 31; NKBA-WW-01 added
```

### 6e — Update class docstring from "31 rules" to "32 rules"

### 6f — Add _check_nkba_ww_01 method (after _check_layout_06 method):
Single/multi-cook threshold from preprocessing.nkba_constraints["num_cooks"].
Calls self._compute_facing_walkway() for the gap.

### 6g — Add _compute_facing_walkway helper (in Helpers section):
Checks N/S then E/W facing wall pairs; also checks island items.
Returns float (mm gap) or None if no facing arrangement.

## Step 7 — Update Graph Wiring (skipped — no graph change)

## Step 8 — Update UI

- `ui/components/nkba_checklist.py` — insert into ALL_RULES after LAYOUT-06:
```python
("NKBA-WW-01", "Walkway width -- >=1067mm single-cook, >=1219mm multi-cook", 0.10),
```
Weight > 0 puts it in the "Project Rules (weighted)" expander automatically.

## Step 9 — Tests

- `tests/unit/test_nkba_validator.py` — append 3 new test functions:
  1. `test_walkway_width_passes_single_cook`: N/S facing walls, 3000mm room, 600mm deep → 1800mm walkway → no violation
  2. `test_walkway_width_fails_too_narrow`: N/S facing walls, 2000mm room, 800mm deep → 400mm walkway → NKBA-WW-01
  3. `test_walkway_multi_cook_threshold`: N/S facing walls, 2300mm room, 550mm deep → 1200mm walkway; single-cook passes, multi-cook (num_cooks=2) fails

Test walls need explicit `anchor="north"` / `anchor="south"` and `points` with y-coords so
`_room_depth()` returns the correct value.

## Step 10 — Lint Gate

```bash
ruff format . && ruff check . && mypy . && pytest tests/unit/ -v
```

## Step 11 — Harness Eval Comparison

- Eval case: `evals/harness/case-03-walkway-constraint/`
- Compare to `expected.md` and fill `result-notes.md`

## Step 12 — Review

- Run `/review-impl`

## Step 13 — Sign-Off Gate

- [x] Plan fully reviewed
- [x] Every step matches product/technical specs
- [x] Protected files untouched
- [x] All relevant skills referenced

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| `_room_depth` only gives Y-extent; E/W case needs X-extent | Low | Medium | Compute X-extent inline in `_compute_facing_walkway` using wall points |
| `total_rules` mismatch if 31 not updated | High | High | Explicitly update to 32 in validate() |
| `_wall()` test helper sets `anchor=name`; anchor must be "north"/"south" | High | Medium | Use explicit anchor in walkway test walls |

## Open Questions

None — all resolved during planning.
