# Fresh Chat Starter

Copy-paste these prompts into a new Claude Code / Cursor chat session to bootstrap context instantly.

---

## Starter 1 — Building a Feature

Paste this at the beginning of any new session where you want to build a feature:

```
Read AGENTS.md at the repo root. Then read docs/harness/glossary.md and
docs/harness/context-budget.md. Do not write any code yet. Once loaded,
ask me which feature I want to build and I will paste the feature request.
```

**What happens next**: The agent loads the harness context, confirms it's ready, and waits for your feature description. You can then paste the feature request directly or point to an eval case.

---

## Starter 2 — Running a Harness Eval

Paste this to run a Markdown eval case:

```
Read AGENTS.md at the repo root. Then read evals/harness/README.md.
I will give you a case folder name. Open that case's prompt.md and
follow the full harness workflow without intervention. Do not ask
clarifying questions unless you are completely blocked.

Case folder: evals/harness/[CASE NAME]/
```

**Recommended first eval**: `case-03-walkway-constraint` — smallest surface, tests constraint-validation hardest. See `evals/harness/README.md` for the full case list.

---

## Starter 3 — PR Review

Paste this to get a structured PR review:

```
Read AGENTS.md and review/pr-review-agent.md. Then review the
implementation of the [FEATURE NAME] feature.

Files changed: [LIST OR "run git diff"]

Produce a structured review report per review/pr-review-agent.md.
Do not modify any files unless I explicitly ask.
```

---

## Tips

- **Always start fresh** — do not continue a long session for a new feature; context pollution causes mistakes
- **Point to the feature folder** — `features/active/<name>/` contains the implementation plan that anchors the session
- **Drift-check monthly** — run `/drift-check` after any large refactor to catch stale skill references
- **After an eval fails** — run `/sharpen-skill` immediately; don't wait for it to fail again
