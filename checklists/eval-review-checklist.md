# Eval Review Checklist

Use after running an `evals/harness/` case to assess pass/fail and drive skill sharpening.

---

## Workflow Compliance
- [ ] Did the coding tool read `AGENTS.md` first?
- [ ] Did it create a `features/active/<name>/` folder?
- [ ] Did it fill all three templates before writing code?
- [ ] Did it identify and read all relevant skill files?
- [ ] Did it follow the 12-step workflow without skipping steps?

## Convention Adherence
- [ ] Did it follow existing repo conventions (CODING_STANDARDS.md)?
- [ ] Did it use `utils/model_selector.py` for all model selection?
- [ ] Did it use `utils/logger.py` (no `print()` calls)?
- [ ] Did it use `mcp_server/server.py` for all catalog access?
- [ ] Did it use `dtos/contracts.py` DTOs at module boundaries?

## Rule Compliance
- [ ] Did it violate any Non-Negotiable Rule from `AGENTS.md`?
  - Which rule(s)?
- [ ] Did it touch any protected file (`render.py`, `layout.py`, `catalog.json`)?
- [ ] Did Agent 3 output semantic vocabulary only (no mm coordinates)?
- [ ] Did it bypass `nkba_validator.py` for any variant?

## Output Quality
- [ ] Did generated output match `expected.md`?
  - If not: which specific items diverged?
- [ ] Were tests added for new logic?
- [ ] Did `pytest tests/unit/` pass after the changes?

## Skill Assessment
- [ ] Which skill(s) failed to prevent the mistakes made?
- [ ] What specific rule was missing from that skill?
- [ ] What bad example should be added?
- [ ] What checklist gate would have caught the failure?

## Actions
- [ ] Filled `result-notes.md` with date, tool, what passed, what failed
- [ ] Identified skill(s) that need sharpening
- [ ] Opened `/sharpen-skill` for each identified skill
- [ ] Added entry to `docs/harness/anti-patterns.md` if this is the 2nd+ occurrence

## Final Assessment
- [ ] **PASS** — output matches expected.md, all rules followed, tests added
- [ ] **PARTIAL** — minor divergences, skill sharpening proposed
- [ ] **FAIL** — significant divergences, skills need major updates before re-run
