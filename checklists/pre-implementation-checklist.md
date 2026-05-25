# Pre-Implementation Checklist

Complete every item before writing any code. Non-negotiable.

---

## Context Loading
- [ ] Read `AGENTS.md`
- [ ] Read `CLAUDE.md`
- [ ] Read `CODING_STANDARDS.md`
- [ ] Read `AGENT_SPECS.md` if this feature touches agent behavior
- [ ] Read relevant `openspec/specs/*.md` for the pipeline layer(s) affected

## Feature Setup
- [ ] Created `features/active/<feature-name>/` folder
- [ ] Filled `features/active/<name>/01-product-spec.md` (all fields, no blanks)
- [ ] Filled `features/active/<name>/02-technical-spec.md` (all fields, no blanks)
- [ ] Filled `features/active/<name>/03-implementation-plan.md` (all 12 steps)

## Skill Loading
- [ ] Identified all relevant skills from the Skill Glossary in `AGENTS.md`
- [ ] Read every relevant skill file in `skills/`
- [ ] Verified `last_verified:` date for each skill is within 60 days
- [ ] If any skill is stale: flagged it (do NOT skip reading it — just note it)

## Code Inspection
- [ ] Inspected existing code in every file I plan to touch BEFORE writing
- [ ] Read `dtos/contracts.py` for relevant existing DTOs
- [ ] Read `pipeline/nkba_validator.py` if adding/changing constraints
- [ ] Read `graph/kitchen_graph.py` if adding/changing graph nodes

## Scope Confirmation
- [ ] Confirmed which files MUST NOT be touched (`render.py`, `layout.py`, `catalog.json`, `CLAUDE.md`, `CODING_STANDARDS.md`, `IMPLEMENTATION_PLAN.md`, `AGENT_SPECS.md`, `System_Design_and_Learnings.md`, `input*.json`, `output.json`, `latest_run.json`)
- [ ] Confirmed test strategy (unit tests + integration tests + fixture data)
- [ ] Confirmed review criteria with the technical spec

## Gate
> **Do not proceed to coding until all boxes above are checked.**
