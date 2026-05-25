# Technical Spec — color-fallback

> Reference real file paths from this repo — no generic placeholders.

---

## Pipeline Layers Affected

| Layer | File | Change Type | Description |
|-------|------|-------------|-------------|
| MCP | mcp_server/color_resolver.py | modify | Add `ColorResolution` dataclass + `resolve_color_keyword()` returning exact_match flag |
| Layer 2 | agents/catalog_selector.py | modify | Call `resolve_color_keyword()` early in `select()`; generate warning if `not exact_match`; store in color_warnings |
| NKBA | pipeline/nkba_validator.py | modify | Merge `preprocessing.color_warnings` into `VariantSummaryDTO.warnings` |
| DTO | dtos/contracts.py | modify | Add `color_warnings: list[str]` field to `PreprocessingOutput` |
| UI | ui/components/variant_card.py | modify | Display warnings in amber ⚠️ style in `render_variant_card()` |
| Layer 1 | pipeline/spatial_engine.py | none | |
| Layer 2 | pipeline/preprocessor.py | none | |
| Layer 2 | agents/prompt_parser.py | none | PromptParser already extracts color_keyword correctly |
| Layer 3 | pipeline/zone_planner.py | none | |
| Layer 3 | agents/layout_strategist.py | none | |
| Layer 4 | pipeline/placement_engine.py | none | |
| Layer 5 | pipeline/output_generator.py | none | Already serializes warnings[] |

---

## DTO / Data Contract Changes

```python
# dtos/contracts.py — modify PreprocessingOutput

@dataclass
class PreprocessingOutput:
    """Result of Layer 2: Intent parsed, SKUs selected, groups formed."""
    intent: IntentDTO
    skus: dict[str, SKU]
    zone_groups: dict[str, list[SKU]]
    zone_min_widths: dict[str, float]
    nkba_constraints: dict[str, Any]
    # NEW: human-readable warnings generated when color keyword was not exact match.
    # Empty list = no substitution. Non-empty = at least one color fallback applied.
    color_warnings: list[str] = field(default_factory=list)
```

No changes to `IntentDTO`, `VariantSummaryDTO`, or `KitchenGraphState`.
`VariantSummaryDTO.warnings` already exists — color_warnings get merged into it in nkba_validator.

---

## MCP / Catalog Changes

### `mcp_server/color_resolver.py` — add `ColorResolution` and `resolve_color_keyword()`

```python
from dataclasses import dataclass

@dataclass
class ColorResolution:
    """Result of resolving a color keyword to a hex code."""
    hex_code: str          # 6-char uppercase hex WITHOUT # (e.g., "9CA3AF")
    exact_match: bool      # True only if keyword is an exact key in _COLOR_TABLE
    matched_keyword: str   # The _COLOR_TABLE key that matched (empty if fallback)

def resolve_color_keyword(keyword: str) -> ColorResolution:
    """Resolve a color keyword with metadata about match quality.

    Returns ColorResolution with exact_match=False when:
    - keyword was not in _COLOR_TABLE (used prefix/substring match)
    - keyword had no match at all (used _FALLBACK_HEX)

    Never raises. Always returns a valid hex.
    """
    key = keyword.strip().lower()

    # 1. Exact match
    if key in _COLOR_TABLE:
        return ColorResolution(hex_code=_COLOR_TABLE[key], exact_match=True, matched_keyword=key)

    # 2. Prefix/substring match (existing logic from keyword_to_hex)
    for table_key, table_hex in _COLOR_TABLE.items():
        if table_key in key or key in table_key:
            return ColorResolution(hex_code=table_hex, exact_match=False, matched_keyword=table_key)

    # 3. No match — return neutral fallback
    return ColorResolution(hex_code=_FALLBACK_HEX, exact_match=False, matched_keyword="")
```

`keyword_to_hex()` updated to delegate to `resolve_color_keyword()` (backward compat preserved).

### `mcp_server/server.py` — update `resolve_color()` to surface `nearest_match`

```python
def resolve_color(keyword: str) -> dict[str, Any]:
    resolution = resolve_color_keyword(keyword)
    match = match_catalog_color(resolution.hex_code, catalog)
    return {
        "hex": resolution.hex_code,
        "matched_sku": ...,
        "delta_e": ...,
        "nearest_match": not resolution.exact_match,   # NEW
    }
```

---

## Agent Changes

### `agents/catalog_selector.py` — add warning generation

In `select()`, immediately after resolving `filtered = self._filter_catalog(intent)`, add:

```python
color_warnings: list[str] = []
if intent.color_keyword:
    resolution = resolve_color_keyword(intent.color_keyword)
    if not resolution.exact_match:
        # Find best matching SKU name for the warning message
        target_hex = resolution.hex_code
        best = match_catalog_color(target_hex, self._catalog)
        if best:
            sku_id, _ = best
            sku_name = self._catalog[sku_id].get("name", sku_id)
            warning = (
                f"Requested color '{intent.color_keyword}' not available — "
                f"using nearest match: {sku_name} (#{target_hex}) SKU: {sku_id}"
            )
        else:
            warning = (
                f"Requested color '{intent.color_keyword}' not available — "
                f"no catalog color match found; using fallback #{target_hex}"
            )
        color_warnings.append(warning)
        logger.warning("Color fallback: %s", warning)
```

Return `PreprocessingOutput(..., color_warnings=color_warnings)` in the success path.
Also update `_fallback_output()` to pass `color_warnings=color_warnings` (warnings already accumulated).

Import changes in `catalog_selector.py`:
```python
from mcp_server.color_resolver import delta_e, match_catalog_color, resolve_color_keyword
```

---

## LangGraph State and Graph Changes

No graph changes. `PreprocessingOutput` already flows through `KitchenGraphState.preprocessing_output`.

---

## UI Changes

### `ui/components/variant_card.py` — display warnings

In `render_variant_card()`, after the violations section, add:

```python
warnings = list(_get(v, "warnings") or [])
if warnings:
    for w in warnings:
        st.markdown(
            f'<div style="background:#2D1F00;border-left:3px solid #D69E2E;'
            f'padding:6px 12px;border-radius:4px;margin:4px 0;color:#D69E2E;'
            f'font-size:0.85rem">⚠️ {w}</div>',
            unsafe_allow_html=True,
        )
```

Business logic stays in pipeline — UI only renders the warning strings it receives.

---

## Validation Requirements

No new NKBA rules. No new validation rules in `pipeline/nkba_validator.py`.
Only change: merge `preprocessing.color_warnings` into the `warnings` list before constructing
`VariantSummaryDTO`.

---

## Logging / Observability Requirements

- `agents/catalog_selector.py`: `logger.warning("Color fallback: %s", warning)` — already planned.
- `mcp_server/color_resolver.py`: existing `logger.warning` for unknown keywords preserved.
- No new llmops tracing.

---

## Testing Requirements

| Test File | Test Name | What It Tests |
|-----------|-----------|---------------|
| tests/unit/test_color_resolver.py | test_unknown_keyword_returns_nearest_match | "dark grey" → ColorResolution with valid hex |
| tests/unit/test_color_resolver.py | test_unknown_keyword_no_crash | Any unknown color keyword never raises |
| tests/unit/test_color_resolver.py | test_resolved_color_has_real_sku | Resolved hex maps to a real catalog SKU |
| tests/unit/test_color_resolver.py | test_nearest_match_flag_is_set | exact_match=False for "dark grey" |
| tests/unit/test_color_resolver.py | test_exact_keyword_no_warning | exact_match=True for "white" (known keyword) |
| tests/unit/test_color_resolver.py | test_case_insensitive_matching | "Dark Grey" == "dark grey" == "DARK GREY" |

---

## Relevant Skills

- [x] skills/color-resolution.md — core resolution chain, fallback rules, warning format
- [x] skills/catalog.md — SKU integrity, no invented SKUs, MCP-only access
- [x] skills/testing-strategy.md — unit test location, naming, no fake SKUs

---

## Files Expected to Change

- `mcp_server/color_resolver.py`
- `dtos/contracts.py`
- `agents/catalog_selector.py`
- `pipeline/nkba_validator.py`
- `ui/components/variant_card.py`
- `tests/unit/test_color_resolver.py` (new file)
- `mcp_server/server.py` (minor: surface nearest_match flag)

---

## Files That MUST NOT Be Touched

- render.py
- layout.py
- catalog.json
- CLAUDE.md
- CODING_STANDARDS.md
- input1.json, input2.json, input3.json
- output.json, latest_run.json
- AGENT_SPECS.md

---

## Review Criteria

- `resolve_color_keyword()` is deterministic — same keyword always returns same result.
- Warning format exactly matches: "Requested color '{keyword}' not available — using nearest match: {name} ({hex}) SKU: {sku_id}"
- No `print()` calls — only `logger.*`.
- All new functions have full type annotations with `from __future__ import annotations`.
- `color_warnings` default is `field(default_factory=list)` — no mutable default argument.
