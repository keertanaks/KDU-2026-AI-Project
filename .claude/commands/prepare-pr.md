# /prepare-pr — Summarize a feature for a pull request

## Quick Steps

1. Read the filled `features/active/<name>/01-product-spec.md`
2. Read the filled `features/active/<name>/02-technical-spec.md`
3. Read the filled `features/active/<name>/03-implementation-plan.md`
4. Run the review: `/review-impl`
5. Compose the PR summary using the format below

## PR Summary Format
```
## Product Change
<one paragraph from product spec>

## Technical Change
<pipeline layers affected, DTOs changed, graph wiring changes>

## Files Changed
<list of files added/modified/deleted>

## Tests Run
- pytest tests/unit/ — <pass/fail>
- pytest tests/integration/ — <pass/fail or skipped>
- Harness eval: <case name or N/A> — <pass/fail>

## Harness Rules Followed
<list rules from AGENTS.md non-negotiable section — confirm each>

## Risks / Known Limitations
<any assumptions, partial coverage, deferred items>

## Eval Pass/Fail
<result-notes.md summary if applicable>
```

## Full Playbook
See `commands/prepare-pr.md` for the complete workflow.

Now do the work described above.
