# features/ — Per-Feature Work Folders

Each new feature gets its own folder under `features/active/<feature-name>/`.

---

## How to Start a Feature

1. Run `/start-feature` in Claude Code, or follow `commands/start-feature.md`
2. Create `features/active/<feature-name>/`
3. Copy and fill all three templates:
   - `templates/01-product-spec-template.md` → `features/active/<name>/01-product-spec.md`
   - `templates/02-technical-spec-template.md` → `features/active/<name>/02-technical-spec.md`
   - `templates/03-implementation-plan-template.md` → `features/active/<name>/03-implementation-plan.md`
4. Read all relevant skill files
5. **Do NOT write code until `03-implementation-plan.md` is complete**

---

## Feature Folder Structure

```
features/active/<feature-name>/
  01-product-spec.md         filled product spec
  02-technical-spec.md       filled technical spec
  03-implementation-plan.md  filled implementation plan (source of truth for coding)
  result-notes.md            (optional) eval result if feature came from evals/harness/
```

---

## Linking to Eval Cases

If a feature maps to an existing eval case, note it in the product spec:
```
## Expected Eval Case
evals/harness/case-01-budget-optimizer/
```

---

## Lifecycle

- Active work: `features/active/<name>/`
- Completed features may be moved to `features/completed/<name>/` after merge (optional)
- Abandoned features: delete the folder or move to `features/abandoned/` with a note explaining why

---

## Rules

- All three templates must be filled before coding begins
- The filled `03-implementation-plan.md` is the source of truth during coding — if you deviate, update it
- If the feature came from an eval case, fill `result-notes.md` after completion
