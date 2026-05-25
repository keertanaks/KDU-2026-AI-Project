# /sharpen-skill — Update a skill file after an eval failure or repeated mistake

## Quick Steps

1. Read `evals/harness/<case>/result-notes.md`
2. Identify the skill that failed or the rule that was missing
3. Read the current skill file in `skills/`
4. Propose a precise sharpening diff: add a rule, bad example, or checklist item
5. Update ONLY files in `skills/`, `checklists/`, `decisions/`, or `AGENTS.md`
6. Bump `version:` and update `last_verified:` in the skill frontmatter
7. Add a line to `harness/CHANGELOG.md`
8. Do NOT touch any application code

## Anti-Pattern Rule
- First occurrence: add to skill's `## Common Failure Modes`
- Second occurrence: add to `docs/harness/anti-patterns.md`
- Third occurrence: add hard constraint to `## Must Not Do` AND add gate to `checklists/pre-commit-checklist.md`

## Full Playbook
See `commands/sharpen-skill.md` for the complete workflow.

Now do the work described above.
