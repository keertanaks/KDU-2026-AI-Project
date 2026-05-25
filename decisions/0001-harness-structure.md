# ADR-0001: Harness Structure

## Status
Accepted

## Date
2026-05-24

## Context

The Kitchen-Layout-Visualizer is a brownfield project with an established 5-layer pipeline, LangGraph orchestration, MCP catalog server, and NKBA constraint validation. New features are built in fresh Claude Code / Cursor chat sessions that begin without project context.

Without a harness, each session must rediscover the architecture, reinvent conventions, and risk violating rules that are only implicit in the code. This produced bugs: model strings hardcoded, catalog.json read directly, render.py accidentally modified.

The harness must work across tools (Claude Code, Cursor) and must be maintainable without being a maintenance burden itself.

## Decision

1. **`AGENTS.md` is the router** (≤200 lines): it points to everything but explains nothing at depth. Inline skill content is forbidden — context budget is finite.
2. **`skills/`** holds deep guidance (≤1000 tokens/skill), each with YAML frontmatter for machine-readability and drift detection.
3. **`templates/`** forces planning before coding — three templates must be filled before any code is written.
4. **`evals/harness/`** holds Markdown eval cases (separate from Python runtime evals in `evals/evaluators/`). Markdown evals test harness guidance quality; Python evals test pipeline output quality.
5. **`.claude/` primitives** (agents, commands, settings.example.json) layer on top for Claude Code users.
6. **MADR ADRs** in `decisions/` for harness design choices.
7. **Semver** on the harness itself via `harness/CHANGELOG.md`.

## Consequences

### Positive
- Modular: skill files are independently updatable without touching AGENTS.md
- Drift-checkable: skill frontmatter enables automated staleness detection
- Cross-tool: AGENTS.md works in any text-aware coding tool, not just Claude Code
- Skills are sharpenable: eval failures drive precise, targeted updates

### Negative
- More files to maintain (~65 files in the harness)
- Context budgets must be enforced — AGENTS.md can grow beyond 200 lines if undisciplined
- Initial setup overhead (paid back after 2nd feature)

### Neutral
- Markdown evals require human judgment to pass/fail — no automated scoring in v1

## Alternatives Considered

- **Everything in AGENTS.md**: rejected — would quickly exceed 200 lines and become unreadable
- **Only CLAUDE.md**: rejected — Claude-only convention, Cursor users would not benefit
- **Skills without evals**: rejected — no validation that skills actually prevent the mistakes they claim to prevent
- **Single flat RULES.md**: rejected — ungrouped rules are hard to navigate and maintain

## Supersedes
—

## Superseded-by
—
