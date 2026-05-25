# How to Use the Harness

A practical guide for anyone starting work on Kitchen-Layout-Visualizer with a coding assistant.

---

## What the Harness Is

The harness is a set of documentation files that tells a coding assistant (Claude Code, Cursor, etc.) how to work on this repo without re-explaining the architecture each time. It enforces conventions, prevents known mistakes, and provides structured workflows for features, evals, and reviews.

It does NOT contain application code. It DOES contain:
- `AGENTS.md` — the router (≤200 lines, read this first)
- `skills/` — 12 deep-dive skill files (read before coding)
- `templates/` — 3 spec templates (fill before coding)
- `commands/` — paste-ready workflow prompts
- `review/` — PR and architecture review playbooks
- `checklists/` — pre-implementation and pre-commit gates
- `evals/harness/` — 6 Markdown eval cases for validation
- `decisions/` — architecture decision records

---

## Starting a Fresh Chat

Use one of the three starters in `docs/harness/fresh-chat-starter.md`:
1. **Feature starter** — for building a feature
2. **Eval starter** — for running an eval case
3. **Review starter** — for PR review

**Golden rule**: always start a fresh chat for each feature. Long sessions accumulate context pollution that causes mistakes.

---

## Choosing Skills

From `AGENTS.md`'s Skill Glossary, identify which skills apply to your feature:

| Feature touches... | Read skill... |
|-------------------|--------------|
| SKU retrieval, catalog queries, prices | `skills/catalog.md` |
| Color keywords, materials, nearest-match | `skills/color-resolution.md` |
| Kitchen shapes L/U/I, variant seeds | `skills/layout-typology.md` |
| NKBA rules, work triangle, scoring | `skills/constraint-validation.md` |
| Multiple variants, seeding, retry | `skills/variant-generation.md` |
| Cabinet runs, gaps, corners | `skills/continuous-run.md` |
| render.py output, coordinates | `skills/rendering.md` |
| Graph nodes, state, retry edges | `skills/langgraph-workflow.md` |
| DTOs, KitchenGraphState | `skills/dto-contracts.md` |
| Unit tests, integration tests, fixtures | `skills/testing-strategy.md` |
| Streamlit UI, components | `skills/ui-integration.md` |
| Model routing, logging, llmops/ | `skills/llm-routing-and-observability.md` |

When in doubt, read more skills. The context cost is small; the mistake cost is high.

---

## Using Commands

The `commands/` folder has paste-ready prompts for repeatable workflows:
- `commands/start-feature.md` — begin a feature (with templates + skills)
- `commands/run-harness-eval.md` — run a Markdown eval case
- `commands/review-implementation.md` — review changed files
- `commands/sharpen-skill.md` — update a skill after failure
- `commands/prepare-pr.md` — compose PR summary

The `.claude/commands/` folder has shorter mirrors of these as slash commands (`/start-feature`, `/run-eval`, etc.) for use inside Claude Code.

---

## Running Harness Evals

See `evals/harness/README.md` for the full eval system.

Quick start:
1. Fresh chat
2. Paste Starter 2 from `docs/harness/fresh-chat-starter.md`
3. Give the case folder name
4. Let the agent run without interruption
5. Compare output to `expected.md`
6. Fill `result-notes.md`

**Recommended first eval**: `case-03-walkway-constraint` — tests constraint-validation with small surface area.

**Bigger demo**: `case-01-budget-optimizer` — stresses 9 skills simultaneously; good for onboarding validation.

---

## Using the PR Review Agent

1. Fresh chat
2. Paste Starter 3 from `docs/harness/fresh-chat-starter.md`
3. List the changed files (or say "run git diff")
4. Review the structured output against `checklists/pre-commit-checklist.md`

Full role prompt: `review/pr-review-agent.md`

---

## Updating a Skill After a Failure

1. Fill `evals/harness/<case>/result-notes.md`
2. Run `commands/sharpen-skill.md` (or `/sharpen-skill` in Claude Code)
3. The agent proposes a precise diff to the skill file — review and apply
4. Bump the skill's `version:` and `last_verified:` date
5. Add a line to `harness/CHANGELOG.md`

---

## Do-Not List

- Do NOT use a long ongoing chat for a new feature — start fresh
- Do NOT skip the templates — they prevent wasted effort later
- Do NOT skip reading skills — each one prevents a specific mistake
- Do NOT modify `render.py`, `layout.py`, or `catalog.json` without an ADR
- Do NOT hardcode model names or use `print()` — ever
