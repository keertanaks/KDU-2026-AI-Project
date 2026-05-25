# decisions/ — Architecture Decision Records

This folder captures harness design decisions using the MADR (Markdown Any Decision Record) format.

---

## Why ADRs

Design decisions are easy to forget and expensive to re-debate. When a teammate asks "why is this harness structured this way?" or "why doesn't it use hooks?", the answer is here — not in Slack history.

ADRs are **short** (one page). They are **not** implementation docs.

---

## When to Write an ADR

Write an ADR when:
- You make a choice that future contributors might want to change
- You deliberately chose NOT to do something (e.g., deferred hooks)
- A significant harness structure decision is made

Do NOT write an ADR for:
- Obvious implementation details
- Bug fixes
- Skill sharpening (that goes in `harness/CHANGELOG.md`)

---

## MADR Format

Every decision record uses these sections:

```markdown
# ADR-NNNN: Title

## Status
Accepted | Superseded | Deprecated

## Date
YYYY-MM-DD

## Context
What situation forced this decision?

## Decision
What was decided and why?

## Consequences
### Positive
### Negative
### Neutral

## Alternatives Considered
What other options were evaluated?

## Supersedes
[Link to the ADR this replaces, if any]

## Superseded-by
[Link to the ADR that replaces this one, if any]
```

---

## Maintenance

- Check `decisions/INDEX.md` before creating a new ADR — it must be kept in sync
- After creating a new ADR, add a row to `decisions/INDEX.md`
- Monthly drift check (`/drift-check`) checks that `Status:` fields are current
