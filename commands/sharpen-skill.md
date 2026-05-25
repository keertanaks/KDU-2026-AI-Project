# Command: sharpen-skill

How to update a skill file after an eval failure or a repeated mistake. Only harness files are changed — never application code.

---

## Paste-Ready Prompt

```
Read AGENTS.md and evals/harness/<case>/result-notes.md.

Then sharpen the harness:

1. Read result-notes.md to understand what failed
2. Identify the skill file(s) that failed to prevent the mistake
3. Read the current skill file in skills/
4. Propose a precise sharpening:
   - A new entry under ## Rules (specific, actionable)
   - A new entry under ## Bad Example (concrete snippet)
   - A new entry under ## Common Failure Modes
   - A new entry under ## Completion Checklist gate
   (use the most appropriate section — not all four)
5. Check docs/harness/anti-patterns.md:
   - If this pattern has appeared before: add a full entry now
   - If 3rd+ occurrence: also add a hard constraint to ## Must Not Do
     AND add a gate to checklists/pre-commit-checklist.md
6. Bump the skill's version: (patch, e.g., 1.0.0 → 1.0.1)
7. Update the skill's last_verified: to today
8. Add a line to harness/CHANGELOG.md
9. Do NOT touch any file outside skills/, checklists/, decisions/, AGENTS.md, harness/CHANGELOG.md

Case folder: evals/harness/[CASE FOLDER NAME]
Skill to sharpen: skills/[SKILL NAME].md
```

---

## Escalation Path
| Occurrence | Action |
|-----------|--------|
| 1st | Add to skill's `## Common Failure Modes` |
| 2nd | Add full entry to `docs/harness/anti-patterns.md` |
| 3rd | Hard constraint in `## Must Not Do` + gate in `checklists/pre-commit-checklist.md` |

## What Must NOT Be Changed
- `agents/`, `pipeline/`, `graph/`, `dtos/`, `mcp_server/`, `ui/`, `utils/`, `tests/`
- Any existing rules (only add or clarify — never remove)

## Linked Resources
- `.claude/agents/skill-sharpener.md` — sub-agent that can do this in isolated context
- `docs/harness/anti-patterns.md` — where recurring patterns are catalogued
- `harness/CHANGELOG.md` — log every sharpening here
