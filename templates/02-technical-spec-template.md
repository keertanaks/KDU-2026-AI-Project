# Technical Spec — [Feature Name]

> Fill every field before writing a single line of code.
> Reference real file paths from this repo — no generic placeholders.

---

## Pipeline Layers Affected
<!-- Be explicit: which .py file in each layer? What changes? -->

| Layer | File | Change Type | Description |
|-------|------|-------------|-------------|
| Layer 1 | pipeline/spatial_engine.py | none / add / modify | |
| Layer 2 | pipeline/preprocessor.py | none / add / modify | |
| Layer 2 | agents/prompt_parser.py | none / add / modify | |
| Layer 2 | agents/catalog_selector.py | none / add / modify | |
| Layer 3 | pipeline/zone_planner.py | none / add / modify | |
| Layer 3 | agents/layout_strategist.py | none / add / modify | |
| Layer 4 | pipeline/placement_engine.py | none / add / modify | |
| NKBA | pipeline/nkba_validator.py | none / add / modify | |
| Layer 5 | pipeline/output_generator.py | none / add / modify | |

## DTO / Data Contract Changes
<!-- Define all changes to dtos/contracts.py FIRST.
     New TypedDict fields, new dataclass fields, new DTOs.
     If none: write "No DTO changes." -->

```python
# Proposed changes to dtos/contracts.py:
```

## MCP / Catalog Changes
<!-- Any new tools added to mcp_server/server.py?
     Any new categories or SKU queries in mcp_server/catalog_loader.py?
     Any color resolver changes in mcp_server/color_resolver.py?
     If none: write "No MCP changes." -->

## Agent Changes
<!-- Which agent (prompt_parser, catalog_selector, layout_strategist) changes?
     New system prompt content? New tool schema? New output field?
     If none: write "No agent changes." -->

## LangGraph State and Graph Changes
<!-- Changes to KitchenGraphState in dtos/contracts.py?
     New nodes in graph/kitchen_graph.py?
     New edges or conditional routing?
     New parallel branches?
     If none: write "No graph changes." -->

```python
# Proposed KitchenGraphState additions (if any):
```

## UI Changes
<!-- Changes to ui/app.py or ui/components/?
     New tab? New component? New display field?
     Remember: UI components must not contain business logic.
     If none: write "No UI changes." -->

## Rendering / Output Changes
<!-- Changes to output JSON shape that render.py consumes?
     New fields in PlacedItem or FinalOutput?
     NEVER modify render.py or layout.py — fix data, not renderer.
     If none: write "No rendering changes." -->

## Validation Requirements
<!-- New NKBA rules to add to pipeline/nkba_validator.py?
     Rule ID, weight, logic, and rationale entry in utils/rationale_lookup.py?
     If none: write "No new validation rules." -->

| Rule ID | Weight | Condition | Rationale Text |
|---------|--------|-----------|----------------|

## Logging / Observability Requirements
<!-- New log calls (use utils/logger.py only)?
     New llmops/ tracing or cost tracking?
     If none: write "None beyond existing logging." -->

## Testing Requirements
<!-- List the new tests that MUST be added.
     Unit tests: tests/unit/test_<module>.py
     Integration tests: tests/integration/test_graph.py
     Fixture data: tests/fixtures/sample_inputs.py -->

| Test File | Test Name | What It Tests |
|-----------|-----------|---------------|

## Relevant Skills
<!-- Which skills did you read? List them here — reviewer confirms. -->
-
-

## Files Expected to Change
<!-- Exhaustive list. Every file you will touch. -->
-
-

## Files That MUST NOT Be Touched
<!-- At minimum, always list these: -->
- render.py
- layout.py
- catalog.json
- CLAUDE.md
- CODING_STANDARDS.md
- input1.json, input2.json, input3.json
- output.json, latest_run.json
- AGENT_SPECS.md

## Review Criteria
<!-- What will the reviewer check specifically for this feature? -->
-
-
