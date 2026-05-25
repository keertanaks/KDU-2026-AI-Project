# Harness CHANGELOG

Semantic versioning for the harness itself. Every skill sharpening, new ADR, new eval case, or workflow change adds an entry here.

Format: [version] — date, then Added / Changed / Deprecated / Removed / Fixed sections.

---

## [1.0.0] — 2026-05-24

### Added
- Initial harness scaffold for Kitchen-Layout-Visualizer (brownfield).
- `AGENTS.md` router (≤200 lines) — points to all skills, templates, commands, and reviews.
- `AGENT_SPECS.md` — renamed from `AGENTS.md`; legacy Agent 1–4 runtime specifications preserved unchanged.
- 12 skill files in `skills/` with YAML frontmatter (`name`, `description`, `version`, `last_verified`, `applies_to`, `tool_risk`):
  - `catalog.md`, `color-resolution.md`, `layout-typology.md`, `constraint-validation.md`
  - `variant-generation.md`, `continuous-run.md`, `rendering.md`, `langgraph-workflow.md`
  - `dto-contracts.md`, `testing-strategy.md`, `ui-integration.md`, `llm-routing-and-observability.md`
- `.claude/` native primitives:
  - `settings.example.json` — deny list, no-hooks comment, allow list for linting/tests
  - `settings.json` — Write and Edit tool calls allowed without prompting
  - 4 sub-agents: `constraint-checker.md`, `harness-reviewer.md`, `skill-sharpener.md`, `drift-detector.md`
  - 6 slash commands: `start-feature.md`, `run-eval.md`, `review-impl.md`, `sharpen-skill.md`, `prepare-pr.md`, `drift-check.md`
- 3 templates in `templates/`: `01-product-spec-template.md`, `02-technical-spec-template.md`, `03-implementation-plan-template.md`
- 3 checklists: `pre-implementation-checklist.md`, `pre-commit-checklist.md`, `eval-review-checklist.md`
- 5 long-form command playbooks in `commands/`: `start-feature.md`, `run-harness-eval.md`, `review-implementation.md`, `sharpen-skill.md`, `prepare-pr.md`
- 5 review files: `pr-review-agent.md`, `architecture-review-checklist.md`, `test-review-checklist.md`, `safety-review-checklist.md`, `drift-check.md`
- 2 MADR decision records: `0001-harness-structure.md`, `0002-hooks-deferred.md` + `README.md` + `INDEX.md`
- 6 Markdown harness eval cases in `evals/harness/` (separate from Python evals in `evals/evaluators/`): cases 01–06 each with `prompt.md`, `expected.md`, `result-notes.md`
- `features/README.md` + `features/active/.gitkeep`
- `docs/harness/` pack: `how-to-use-the-harness.md`, `design-decisions-and-learnings.md`, `glossary.md`, `context-budget.md`, `anti-patterns.md` (seeded with 3 real examples), `fresh-chat-starter.md`
- `harness/CHANGELOG.md` (this file)

### Rename
- `AGENTS.md` → `AGENT_SPECS.md` (git mv, content unchanged, history preserved)

---

*Next entry: first skill sharpening, new eval case, or ADR.*
