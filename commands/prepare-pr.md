# Command: prepare-pr

How to prepare a pull request summary for a completed feature.

---

## Paste-Ready Prompt

```
Read AGENTS.md. Then prepare a PR summary for this feature:

1. Read features/active/<feature-name>/01-product-spec.md
2. Read features/active/<feature-name>/02-technical-spec.md
3. Read features/active/<feature-name>/03-implementation-plan.md
4. Run /review-impl (or read commands/review-implementation.md and apply it)
5. Compose the PR summary in this format:

   ## Product Change
   [one paragraph from product spec — what problem it solves]

   ## Technical Change
   [pipeline layers affected, DTO changes, graph wiring changes, new rules]

   ## Files Changed
   [exhaustive list: added / modified / deleted]

   ## Tests Run
   - pytest tests/unit/ — [pass/fail count]
   - pytest tests/integration/ — [pass/fail or "skipped (API cost)"]
   - Harness eval: [case name] — [pass/fail/N/A]
   - ruff format . — [pass/fail]
   - ruff check . — [pass/fail]
   - mypy . — [pass/fail]

   ## Harness Rules Followed
   [for each Non-Negotiable Rule in AGENTS.md: confirm or note exception]

   ## Risks / Known Limitations
   [assumptions made, partial coverage, deferred items, cost/budget estimates labeled]

   ## Eval Pass/Fail
   [result-notes.md summary if applicable, or N/A]

Feature name: [FEATURE NAME]
```

---

## PR Branch Convention
Per `CLAUDE.md` git workflow:
- `main → dev2 → feature/<name> → PR back to dev2 → merge to main`
- PR message must reference the design doc section from `features/active/<name>/02-technical-spec.md`

## Linked Resources
- `commands/review-implementation.md` — run this first
- `checklists/pre-commit-checklist.md` — confirm all items
- `evals/harness/<case>/result-notes.md` — include if applicable
