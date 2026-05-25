# /run-eval — Run a harness Markdown eval case

## Quick Steps

1. Read `AGENTS.md`
2. Read `evals/harness/README.md`
3. Open the target case: `evals/harness/<case>/prompt.md`
4. Follow the full 12-step feature workflow from `AGENTS.md` without intervention
5. Build the feature as instructed in `prompt.md`
6. Compare your output to `evals/harness/<case>/expected.md`
7. Fill `evals/harness/<case>/result-notes.md` with the outcome
8. If the eval fails: identify which skill needs sharpening → run `/sharpen-skill`

## Rules
- Do NOT ask clarifying questions unless genuinely blocked
- Do NOT skip templates — fill all three before coding
- Do NOT run Python runtime evals (those live in `evals/evaluators/`)
- Do NOT modify `evals/evaluators/` or `evals/metrics/`

## Recommended First Eval
`evals/harness/case-03-walkway-constraint/` — smallest surface, tests constraint-validation hardest

## Full Playbook
See `commands/run-harness-eval.md` for the complete workflow.

Now do the work described above.
