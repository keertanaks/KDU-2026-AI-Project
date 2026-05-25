# evals/harness/ — Markdown Harness Eval Cases

These are **Markdown harness evals** — not the Python runtime evaluators in `evals/evaluators/` and `evals/metrics/`.

---

## What These Test

These eval cases test whether a Claude Code / Cursor session correctly uses the harness:
- Does it read AGENTS.md first?
- Does it fill templates before coding?
- Does it read the relevant skill files?
- Does it follow repo conventions (CODING_STANDARDS.md)?
- Does its output match the expected behavior?

They do NOT test pipeline output quality (scores, rendered PNGs, etc.) — that's what the Python evals are for.

---

## How to Run an Eval

1. Start a **fresh chat** (no prior context about this repo)
2. Read `AGENTS.md`
3. Open `evals/harness/<case>/prompt.md`
4. Paste the prompt into the fresh chat — let the agent work **without intervention**
5. Do NOT clarify questions unless the agent is completely blocked
6. When the agent finishes, compare output to `evals/harness/<case>/expected.md`
7. Fill `evals/harness/<case>/result-notes.md`
8. If the eval fails → run `commands/sharpen-skill.md`

Full workflow: see `commands/run-harness-eval.md`

---

## Cases

| Case | Feature | Skills Stressed | Difficulty |
|------|---------|----------------|------------|
| case-01-budget-optimizer | Estimated budget optimizer | 9 skills | High |
| case-02-style-transfer | Style keyword → palette → SKUs | 5 skills | Medium |
| case-03-walkway-constraint | Walkway width NKBA rule | 4 skills | Low |
| case-04-accessibility-agent | Accessibility advisor agent | 5 skills | High |
| case-05-color-fallback | Dark grey → nearest match | 3 skills | Low |
| case-06-export-design-report | Exportable design report | 5 skills | Medium |

---

## Recommended Order

1. **First eval**: `case-03-walkway-constraint` — smallest surface, hardest constraint test. If the agent fails this, skills/constraint-validation.md needs sharpening before anything else.
2. **Second eval**: `case-05-color-fallback` — tests color-resolution and catalog governance.
3. **Bigger demo**: `case-01-budget-optimizer` — stress-tests 9 skills simultaneously.

---

## Passing Criteria (all cases)

An eval PASSES if:
1. Agent read AGENTS.md first
2. Agent created `features/active/<name>/` and filled all three templates
3. Agent read all relevant skills (listed in `expected.md`)
4. No Non-Negotiable Rule from AGENTS.md was violated
5. Protected files were not touched
6. Tests were added as specified in `expected.md`
7. Output matches the behavior described in `expected.md`

An eval FAILS if any of the above is false. Partial failures drive specific skill sharpening.

---

## Separation from Python Evals

Do NOT touch `evals/evaluators/` or `evals/metrics/` when working with these Markdown evals.
Those Python evals test runtime pipeline output (scores, placements, NKBA compliance).
These Markdown evals test harness workflow compliance.
