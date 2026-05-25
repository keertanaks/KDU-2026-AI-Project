# Command: start-feature

Paste this block at the start of a new Claude Code / Cursor chat to begin building a feature.

---

## Paste-Ready Prompt

```
Read AGENTS.md at the repo root. Then follow these steps exactly:

1. Read AGENTS.md
2. Read CLAUDE.md
3. Read CODING_STANDARDS.md
4. Create features/active/<feature-name>/ (use the feature name I give you)
5. Copy templates/01-product-spec-template.md → features/active/<name>/01-product-spec.md
   Fill every field. Write N/A with a reason if not applicable.
6. Copy templates/02-technical-spec-template.md → features/active/<name>/02-technical-spec.md
   Fill every field.
7. Copy templates/03-implementation-plan-template.md → features/active/<name>/03-implementation-plan.md
   Fill every step — be specific (file, function, line range where known).
8. Identify all relevant skills from the Skill Glossary in AGENTS.md.
9. Read every relevant skill file in skills/.
   Check that last_verified: is within 60 days. Flag any stale skills.
10. Do NOT write any application code until step 9 is complete and I confirm the plan.

Feature name and description: [I WILL PROVIDE THIS]
```

---

## What Happens Next

Once templates are filled and skills are read:
- Agent will present the filled `03-implementation-plan.md` for review
- You confirm, then coding begins
- Agent follows the 12-step workflow from AGENTS.md

## If an Eval Case Applies

If this feature maps to an eval case, tell the agent:
```
This feature maps to evals/harness/case-<N>-<name>/prompt.md.
Read that prompt and use it as the feature description.
```

## Linked Resources
- `checklists/pre-implementation-checklist.md` — agent should work through this before coding
- `templates/` — three templates to fill
- `skills/` — 12 skill files to read as relevant
