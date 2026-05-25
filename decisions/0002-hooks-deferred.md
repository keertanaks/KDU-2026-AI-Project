# ADR-0002: Hooks Deferred to v2

## Status
Accepted

## Date
2026-05-24

## Context

Claude Code supports deterministic tool-layer hooks (PreToolUse, PostToolUse, Stop, UserPromptSubmit, PreCompact). These could enforce protected-file rules at the tool layer — preventing agents from ever writing to `render.py`, `layout.py`, or `catalog.json` regardless of instructions.

Implementing a complete hook set in v1 would add scope: designing hook scripts for each protected file, testing them on Windows (PowerShell), handling edge cases where the hook incorrectly blocks legitimate writes, and documenting the hook architecture.

## Decision

Hooks (PreToolUse, PostToolUse, Stop, UserPromptSubmit, PreCompact) are intentionally deferred to harness v2.

v1 enforces protected-file rules via:
1. Advisory deny list in `.claude/settings.example.json`
2. Explicit rules in `AGENTS.md` and every relevant skill
3. Human review via `checklists/pre-commit-checklist.md` and `review/pr-review-agent.md`
4. The `harness-reviewer` sub-agent in `.claude/agents/harness-reviewer.md`

## Consequences

### Positive
- v1 ships faster and simpler
- No risk of hook misconfiguration blocking legitimate file edits
- Works without requiring `.claude/hooks/` directory to exist

### Negative
- Protected-file rules are advisory, not blocking in v1
- A session can technically modify `render.py` if it ignores the rules; human review is the backstop
- Rule violations are caught at PR review time, not at tool-call time

### Neutral
- v2 plan is documented — the path to implementation is clear
- `.claude/hooks/` directory is intentionally absent from the repo

## v2 Implementation Plan (future)

When hooks are implemented, the plan is:
1. PreToolUse hook matching `Write|Edit` — checks file path against protected list, returns `decision: block` with reason
2. PostToolUse hook matching `Write|Edit` — runs `ruff format && ruff check` on changed files
3. Stop hook — reminds user to run `pytest tests/unit/`
4. Scripts stored in `.claude/hooks/scripts/` (to be created in v2)

## Alternatives Considered

- **Ship full hooks set in v1**: rejected — adds scope; hook scripts need testing on Windows
- **Pre-commit Git hooks only**: deferred — belongs with CI work, separate from Claude Code harness
- **Soft advisory only (current approach)**: accepted for v1

## Supersedes
—

## Superseded-by
—
