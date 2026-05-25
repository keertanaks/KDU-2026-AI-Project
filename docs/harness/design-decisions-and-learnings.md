# Design Decisions and Learnings

A thoughtful, specific account of how and why this harness was designed for Kitchen-Layout-Visualizer. Not a generic summary.

---

## Project Context

Kitchen-Layout-Visualizer is a brownfield project: the 5-layer pipeline, LangGraph orchestration, MCP catalog server, NKBA validator, and Streamlit UI were all built before the harness existed. The harness had to work with — not replace — an established codebase.

The core challenge: a fresh Claude Code or Cursor session begins with no knowledge of the project. Within a few turns, it will attempt to modify files, choose models, query the catalog, or place cabinets — and without guidance, it makes predictable mistakes. The harness's job is to make those mistakes structurally impossible (or at minimum: conspicuous at review time).

---

## Why AGENTS.md is Small (≤200 lines)

The first instinct was to put everything in AGENTS.md. A large AGENTS.md is tempting — it guarantees the agent sees all rules in one read. But a 600-line AGENTS.md defeats itself: agents skim long files, important rules get buried, and the file becomes too expensive in context budget to re-read when needed.

The solution: AGENTS.md is a **router**, not a reference. It names the 12 skills and points to them. An agent spending 200 lines on rules will miss them; an agent reading a 200-line router that explicitly says "read `skills/constraint-validation.md` before touching nkba_validator.py" has a fighting chance.

---

## Why Skills are Separated

Skills are separated from AGENTS.md for three reasons:
1. **Context budget**: a fresh chat can load AGENTS.md + 2–3 relevant skills without hitting limits. Loading all 12 skills at once would be wasteful when only 2 apply to a given feature.
2. **Updatability**: when a rule needs sharpening after an eval failure, updating one skill file is precise and auditable. Editing AGENTS.md to add one rule risks destabilizing the whole router.
3. **Drift detection**: YAML frontmatter on skills enables the drift-detector sub-agent to systematically check that every file path, function name, and rule ID in a skill still exists in the repo.

---

## Why Templates Force Planning

The three templates (`01-product-spec`, `02-technical-spec`, `03-implementation-plan`) exist because agents that skip planning write code that contradicts the architecture. Specifically:
- Without a technical spec, agents don't think about DTOs before writing node code → DTOs end up defined in the wrong files
- Without an implementation plan, agents don't read existing code before adding new code → duplicate logic appears
- Without a product spec, agents confuse the problem with a solution they've already started implementing

The templates are a deliberate speed bump. The time cost of filling them is small; the time cost of refactoring wrong-architecture code is large.

---

## Why Markdown Evals are Separate from Python Evals

`evals/evaluators/` and `evals/metrics/` contain Python runtime evals that measure pipeline output quality (scores, placements, NKBA compliance). These are correct but they test the pipeline, not the harness.

`evals/harness/` contains Markdown eval cases that measure whether an agent follows the harness correctly. A passing harness eval means: the agent read AGENTS.md, filled templates, read skills, didn't invent SKUs, and didn't modify protected files. Whether the resulting layout is geometrically optimal is a separate question.

Keeping these separate prevents a category error: "the pipeline passes its evals" does not imply "the harness is guiding agents correctly."

---

## Why Checklists

Checklists (`pre-implementation-checklist.md`, `pre-commit-checklist.md`, `eval-review-checklist.md`) exist because rules in text are easier to skip than items in a list. The pre-commit checklist mirrors the harness's non-negotiable rules in gate form. A reviewer can mechanically check each box rather than re-reading AGENTS.md.

The pattern is borrowed from aviation: checklists don't replace expertise, they prevent expertise from being bypassed in a hurry.

---

## Why commands/ and .claude/commands/

`commands/` contains long-form paste-ready prompts for entire workflows. `.claude/commands/` contains shorter slash-command mirrors. This two-tier structure exists because:
- Slash commands (`/start-feature`) are convenient but limited to ~60 lines in Claude Code
- Long-form commands need more context than fits in a slash command
- Having both means the workflow is accessible whether you type `/start-feature` or paste from `commands/start-feature.md`

---

## Why the PR Review Agent

The `review/pr-review-agent.md` gives a coding assistant a specific role with a specific checklist. Without it, a "code review" request produces a generic quality review. With it, the review is anchored to this project's rules: protected files, DTO usage, model routing, validator bypass, etc.

---

## Why Hooks Are Deferred

Hooks (PreToolUse, PostToolUse) could enforce protected-file rules at the tool layer — making it structurally impossible to write to `render.py`. They were deferred to v2 because:
1. Hook scripts need testing on Windows (this repo runs on Windows 11, PowerShell)
2. A misconfigured hook silently blocks ALL settings from a `.claude/settings.json` file
3. V1's advisory deny list + human review is sufficient for the current team size

The v2 plan is documented in `decisions/0002-hooks-deferred.md`. Hooks are a future improvement, not an oversight.

---

## What Works Best for This System

- **Grounding in real files**: skills that reference `utils/rationale_lookup.py:RULE_EXPLANATIONS` or `pipeline/nkba_validator.py:WORK_TRIANGLE_MIN_MM` are used correctly. Generic skills that say "validate constraints" are ignored.
- **Over-constrained Agent 3**: the semantic vocabulary restriction (no mm coordinates) is the single most effective rule in the harness. It prevents a whole class of placement bugs at zero runtime cost.
- **Drift detection via frontmatter**: the `last_verified:` date in skill frontmatter is the only mechanism that surfaces staleness before it causes bugs.

---

## Limitations

- Markdown evals require human judgment — no automated scoring in v1
- Skills can still be skipped if the agent doesn't read them; the harness advises, it doesn't enforce (enforcement planned via hooks in v2)
- Context budgets depend on manual discipline; there is no automated AGENTS.md line-count gate in v1

---

## Future Improvements

1. **Claude Code hooks** (`PreToolUse` on `Write|Edit`) — block writes to protected files at the tool layer
2. **CI guardrails** — pre-commit hook running `ruff + mypy + pytest tests/unit/`
3. **Automated protected-file checks** — script that greps git diff for protected files
4. **Automated eval scoring** — script that compares result-notes.md to expected.md and computes a pass rate
5. **Richer golden-output evals** — case-specific snapshot tests for critical constraint scenarios
