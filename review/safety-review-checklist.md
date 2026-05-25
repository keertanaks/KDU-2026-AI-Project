# Safety Review Checklist

Use for features touching LLM calls, catalog data, cost estimates, or output contracts.

---

## Secrets and Credentials
- [ ] No API keys, tokens, or credentials hardcoded anywhere
- [ ] Sensitive config comes from `.env` (gitignored) via `python-dotenv`
- [ ] `.env.example` updated if a new variable is required

## SKU Integrity
- [ ] No fake/invented SKU IDs anywhere — all from real `catalog.json`
- [ ] No test creates a SKU that looks real but isn't in the catalog
- [ ] Fixtures use real SKU IDs from `catalog.json`

## Hidden Validation Failures
- [ ] No variant returned without running `pipeline/nkba_validator.py`
- [ ] No violation silently swallowed — all violations surface in `VariantSummaryDTO.violations`
- [ ] UI components display all warnings and violations from `VariantSummaryDTO`

## Silent Fallbacks
- [ ] Every nearest-color fallback adds a `warnings[]` entry
- [ ] Every spillover placement logs `LAYOUT-06` penalty
- [ ] Every failed retry keeps the variant with `warnings[]` — never silent drop
- [ ] Every `try/except` on Claude API calls logs the error at WARNING level

## Uncontrolled LLM Calls
- [ ] No new LLM call added without documented: model route, fallback, cost controls
- [ ] No unconditional Opus call — Opus only via `should_use_opus()` retry trigger
- [ ] Prompt caching applied to all static system prompts

## Protected-File Edits
- [ ] `render.py` — untouched
- [ ] `layout.py` — untouched
- [ ] `catalog.json` — untouched (or ADR filed with justification)

## Misleading Cost / Budget Claims
- [ ] Any cost/budget output uses `catalog.json` `price_tier`, not real prices
- [ ] All cost output labeled "Estimated Cost" with documented estimated price map
- [ ] No feature claims to show "real prices" unless real price data is added to catalog

## Output Contract Stability
- [ ] `FinalOutput` and `PlacedItem` fields not removed without migrating callers
- [ ] Breaking DTO changes have ADR filed in `decisions/`
- [ ] `render.py` still produces valid output with the new `PlacedItem` shape

## Catalog Mutation
- [ ] `catalog.json` not modified during tests
- [ ] No code writes to `catalog.json` at runtime
