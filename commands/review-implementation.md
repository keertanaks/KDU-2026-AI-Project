# Command: review-implementation

How to review a feature implementation against this harness. Read-only — proposes changes, does not apply them unless asked.

---

## Paste-Ready Prompt

```
Read AGENTS.md at the repo root. Then review the current implementation:

1. Read checklists/pre-commit-checklist.md
2. Read CODING_STANDARDS.md
3. Read the filled features/active/<feature-name>/02-technical-spec.md
4. Read the filled features/active/<feature-name>/03-implementation-plan.md
5. Read every relevant skill file for this feature
6. Review all files changed by this feature (I will list them or you can git diff)
7. Report in this exact format:

   IMPLEMENTATION REVIEW
   ---------------------
   Feature: <name>

   1. SUMMARY
      <one paragraph>

   2. BLOCKING ISSUES (must fix before merge)
      - <file:line> — <what rule is violated>

   3. NON-BLOCKING ISSUES (should fix)
      - <description>

   4. MISSING TESTS
      - <what is untested and where it should go>

   5. HARNESS RULE VIOLATIONS
      - <which AGENTS.md non-negotiable rule>

   6. SUGGESTED SKILL / CHECKLIST UPDATES
      - <skill file> — <what to add or sharpen>

   7. RECOMMENDATION
      [ ] Approve  [x] Request Changes

8. Do NOT modify any file unless I explicitly ask.

Feature name: [FEATURE NAME]
Files changed: [LIST OR "run git diff"]
```

---

## When to Use
- Before opening a PR
- After a review request from a teammate
- After running an eval case

## Linked Resources
- `review/pr-review-agent.md` — full PR review agent role prompt
- `checklists/pre-commit-checklist.md` — the checklist used during review
- `review/architecture-review-checklist.md` — deeper architectural review
