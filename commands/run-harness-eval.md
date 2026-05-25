# Command: run-harness-eval

How to run a Markdown harness eval case. Do not confuse with the Python runtime evals in `evals/evaluators/`.

---

## Fresh Chat Required

Start a fresh Claude Code or Cursor chat. Do not use an existing thread with repo context. Each eval run is independent.

---

## When to Use
- Testing whether a Claude Code / Cursor session can correctly implement a feature using this harness
- Validating skill coverage before building a real feature
- After sharpening a skill, confirm the fix works

## Recommended Order
1. **Start here**: `evals/harness/case-03-walkway-constraint/` — smallest surface, hardest constraint test
2. **Bigger demo**: `evals/harness/case-01-budget-optimizer/` — stress-tests 9 skills simultaneously

---

## Paste-Ready Prompt

```
Read AGENTS.md at the repo root. Then:

1. Read docs/harness/glossary.md
2. Read evals/harness/README.md
3. Open evals/harness/<case-folder>/prompt.md and read it completely
4. Follow the full 12-step new-feature workflow from AGENTS.md — no shortcuts
5. Build the feature described in prompt.md without asking clarifying questions
   (unless you are genuinely blocked by a missing definition)
6. After building, compare your output against evals/harness/<case-folder>/expected.md
7. Fill evals/harness/<case-folder>/result-notes.md with:
   - Date
   - Tool used (Claude Code / Cursor / version)
   - What passed
   - What failed
   - Rules violated
   - Skills that need updates
   - Follow-up action
8. If any expected item was missed: identify which skill needs sharpening

Case folder: evals/harness/[CASE FOLDER NAME]
```

---

## Rules
- Do NOT intervene while the agent is building — let it run the full workflow
- Do NOT run the Python runtime evals (`evals/evaluators/`) — these are separate
- Do NOT modify `evals/evaluators/` or `evals/metrics/`
- Do NOT skip the result-notes.md — it drives skill sharpening

## After the Eval
- If PASS: commit `result-notes.md`, move on
- If FAIL: run `commands/sharpen-skill.md` for each identified skill
- If repeated failure: check `docs/harness/anti-patterns.md` — add new entry if pattern recurs

## Linked Resources
- `evals/harness/README.md` — eval system overview
- `checklists/eval-review-checklist.md` — systematic pass/fail assessment
- `commands/sharpen-skill.md` — follow-on action on failure
