# Context Budget

Hard limits for harness files. Reviewers block PRs that violate these without a filed ADR in `decisions/`.

---

## Hard Limits

| File / Scope | Limit | Why |
|---|---|---|
| `AGENTS.md` | ≤ 200 lines | Must fit comfortably in a fresh chat's first read; over-long files get skimmed |
| Each skill body (excluding frontmatter) | ≤ 1000 tokens (~750 words) | Skills must be skimmable in 30 seconds; depth goes in linked resources |
| Each checklist | ≤ 80 lines | Checklists longer than one screen are not used |
| Each filled template | ≤ 200 lines after filling | Prevents templates from becoming documentation disguised as specs |
| `CLAUDE.md` | ≤ 500 lines (existing — do not modify) | Project constraint from the codebase |

---

## Why Context Budgets Matter

Coding tools have finite context windows. When a session reads `AGENTS.md`, `CLAUDE.md`, a skill file, two templates, and an open file, every byte counts. Bloated harness files:
1. Exceed context limits in long sessions, causing truncation
2. Are skimmed rather than read, defeating their purpose
3. Make drift detection harder (more text = more stale references to find)

---

## What Must NEVER Happen

- **`AGENTS.md` must NEVER inline a skill's body** — it points to `skills/` files, never duplicates them
- **A skill file must NEVER duplicate** content from `AGENTS.md`, `CLAUDE.md`, or `CODING_STANDARDS.md` — reference, don't copy
- **A checklist must not become a tutorial** — checklists are gates, not explanations

---

## How to Handle Overflows

If a skill file exceeds ~1000 tokens:
1. Identify the section that is bloated — usually `## Rules` or `## Common Failure Modes`
2. Move the most specific/rare cases to a linked sub-section or a new related skill
3. Trim examples to the single most illustrative one
4. Never delete rules — condense them

If `AGENTS.md` approaches 200 lines:
1. Review the last 10 additions — was any content that belongs in a skill inlined?
2. Move inlined content to the relevant skill file
3. Replace with a one-line pointer

---

## Enforcement

The `harness-reviewer` sub-agent (`.claude/agents/harness-reviewer.md`) checks context budgets as part of every review. A PR that adds content pushing `AGENTS.md` over 200 lines will be flagged as a blocking issue.
