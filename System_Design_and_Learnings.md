# Auto-Design System — Technical Design Document
## Kitchen Layout Visualizer | Project 2
### Author: Keertana | Date: May 2026

---

## Table of Contents

1. [System Architecture & Problem Breakdown](#1-system-architecture--problem-breakdown)
2. [Prompting Strategy & Reasoning Design](#2-prompting-strategy--reasoning-design)
3. [Retrieval, Planning & Layout Generation](#3-retrieval-planning--layout-generation)
4. [Reliability, Validation & Evaluation](#4-reliability-validation--evaluation)
5. [Cost Optimization & Scalability](#5-cost-optimization--scalability)
6. [Learnings, Design Decisions & Future Improvements](#6-learnings-design-decisions--future-improvements)

---

## 1. System Architecture & Problem Breakdown

### 1.1 The Core Problem

Designing a kitchen layout is a constrained, multi-objective problem. You have a fixed room with walls, doors, windows, and columns. You have a catalog of cabinets and appliances — each with a specific width, depth, and height. And you have a set of design standards from the National Kitchen & Bath Association (NKBA) governing everything from the work triangle perimeter to fridge door clearance, ventilation requirements, and landing area dimensions beside every appliance. On top of this, you want to satisfy a user's aesthetic preferences: a color keyword, a layout shape, a style, a budget.

The challenge is not just satisfying one of these requirements — it is satisfying all of them simultaneously while generating multiple meaningfully different variants that give the user a real choice. And it needs to do this end-to-end from a JSON description of a kitchen room.

The system could have been built as a single large LLM call. It was deliberately not. The reason is that LLMs reason well over abstract strategy — "where should the sink go relative to the window, and why" — but they are unreliable for precise arithmetic. An LLM given wall lengths in millimeters will sometimes produce placements that overlap, violate clearances by a few millimeters, or quietly ignore constraints it cannot hold in attention simultaneously. Making a model solely responsible for both spatial reasoning and coordinate arithmetic is a recipe for compounding errors.

The design decision that shaped everything else was therefore this: **LLMs plan in semantic terms. Deterministic code converts to coordinates and validates.**

### 1.2 High-Level Architecture

The system is a five-layer sequential-then-parallel pipeline, orchestrated by LangGraph:

```
input.json
    │
    ▼
Layer 1 — Spatial Engine          (deterministic Python)
    │
    ▼
Layer 2 — Preprocessor            (Agent 1 → MCP catalog → Agent 2, sequential)
    │
    ▼
Layer 3 — Zone Planner            (Agent 3 × 3 variants, parallel)
    │
    ▼
Layer 4 — Placement Engine        (deterministic Python × 3 variants, parallel)
    │
    ▼
Layer 5 — NKBA Validator          (deterministic math × 3 variants, parallel)
    │
    ▼
    ├──[ score ≥ 0.60 and no critical violations ] ──▶ Output Generator
    │
    └──[ score < 0.60 OR WORKFLOW-03 OR NKBA-CL-01 violated ] ──▶ Retry: Agent 3 on Opus
                                                                          └──▶ Placement → NKBA → Output
    ▼
Output Generator → output.json + PNGs
    │
    ▼
Streamlit UI (4 persona tabs)
```

This pipeline runs end-to-end in roughly 15–25 seconds for three variants. The sequential layers (1 and 2) must complete before the parallel layers can begin, because the spatial geometry and selected SKUs are shared inputs for all variant generation. Layers 3 through 5, however, are fully independent per variant and run concurrently via `asyncio.gather`.

### 1.3 Layer-by-Layer Responsibility

**Layer 1 — Spatial Engine**

This is pure geometry parsing with zero LLM involvement. It reads the input JSON describing the room — walls with their lengths and cabinet-bearing flags, openings (doors, windows) with their offsets, widths, and sill heights — and computes:

- A list of `Wall` objects with their dimensions
- `free_segments` per wall: the spans where base cabinets can be placed, after subtracting door footprints and swing arcs
- `wall_free_segments`: the spans where wall cabinets can be placed, after subtracting window frames
- `layout_capacity`: whether the room supports an I-shape (one cabinet wall), L-shape (two adjacent walls), or U-shape (three walls)
- `flow_order`: the walls in priority order, longest first

This layer is the ground truth of the physical space. Nothing that comes later can override it. If a wall is only 2000mm long, no agent can pretend otherwise.

One important early bug here: `input2.json` had room dimensions listed as `42000mm × 42000mm` — a factor-of-ten error on what should have been `4200mm`. The spatial engine was parsing it faithfully and handing off an enormous room to the rest of the pipeline. Variants were then being placed with enormous spans of empty counter. This was caught through integration testing, corrected in the catalog expansion commit, and a note was added to the README about coordinate unit expectations.

**Layer 2 — Preprocessor: Agent 1 + MCP + Agent 2**

This layer runs once per request and produces a shared `PreprocessingOutput` used by all variants. It has three sub-stages:

1. **Agent 1 (Prompt Parser)** reads the user's free-text prompt and extracts structured intent: color keyword and hex code, layout family preference, style, cabinet preference, special requests. This is an LLM call, but the outputs are validated and deterministic overrides are applied (a regex for hex color extraction always wins over whatever the model produced).

2. **MCP Catalog Server** is queried with 9 tools to retrieve available SKUs. The catalog has 120 items. The agent filters by budget tier, color match (CIE76 delta-E ≤ 15), and style, and assembles a gap-fill pool of cabinets in each standard width (1200, 900, 750, 600, 450, 300mm) to ensure the placement engine always has sizes to fill awkward gaps.

3. **Agent 2 (Catalog Selector)** uses the MCP tools to select the final SKU set, grouped by zone (cooling, cleaning, cooking, preparation, storage), and computes `zone_min_widths` — the minimum wall space each zone needs. These minimum widths feed the placement engine's landing area allocator.

**Layer 3 — Zone Planner (Agent 3)**

Three calls to Agent 3 run in parallel, each with a different seed strategy suffix. Agent 3's output is purely semantic — a description of where items should go using a controlled vocabulary ("at north-west corner", "next to sink", "above stove", "near north window"). No numbers. No coordinates. Just spatial intent. The Placement Engine is the translator.

**Layer 4 — Placement Engine**

This is entirely deterministic Python. It takes the semantic strategy from Agent 3, the SKU dimensions from preprocessing, and the wall geometry from spatial, and computes exact millimeter coordinates for every item. It handles:

- Anchored items first (sink, fridge, stove) — these have fixed semantic positions
- Dependent items next (hood above stove, dishwasher next to sink)
- Fill items last (base cabinets, wall cabinets, tall cabinets)
- Spillover to adjacent walls when a wall runs out of space
- A dynamic programming algorithm for wall cabinet fill to avoid awkward residual gaps
- Collision detection with a whitelist for physically valid overlaps (hood above stove, tap on sink)

**Layer 5 — NKBA Validator**

Pure math against 31 rules: 11 project-defined rules and 20 official NKBA guidelines. No LLM call. Produces a weighted violation list and a score between 0 and 1.3. Rationale text is generated from a static lookup table keyed on violation IDs — zero additional API cost.

### 1.4 Why LLMs Were Used Where They Were Used

The LLM calls in this system are concentrated in exactly three places, each chosen because the task benefits from language understanding rather than arithmetic:

- **Agent 1 (parsing)**: Understanding that "midnight navy" maps to `#1F3A5F`, that "cozy cottage kitchen" implies traditional style, or that "make it accessible" should set an accessibility seed. This is semantic interpretation — a regex cannot do it reliably across thousands of possible phrasings.
- **Agent 2 (selection)**: Matching user intent to catalog items when the vocabulary between "modern flat-front base cabinet" and the catalog's style tags is not a direct string match. Also deciding which SKUs are necessary vs optional given the room dimensions.
- **Agent 3 (strategy)**: Reasoning about which wall the sink should go on given the room's window positions, how to close a work triangle in a U-shape, and where to place the fridge relative to the cooking zone. These are design decisions that benefit from spatial reasoning across multiple constraints simultaneously — not arithmetic.

Everything else — geometry parsing, coordinate conversion, rule checking, scoring — is deterministic code. This is not a cost-saving compromise. It is the architecturally correct division.

### 1.5 How the System Maintains Consistency

Several mechanisms ensure correctness and determinism:

- **DTOs as contracts**: All data crossing pipeline layer boundaries is typed via Python dataclasses (`dtos/contracts.py`). Each layer knows exactly what it receives and what it must produce. There is no loose dictionary passing between layers.
- **Semantic vocabulary constraint**: Agent 3 can only produce one of eleven position terms. Any term not matching the vocabulary is replaced with a fallback ("left end of [wall]") and logged. This means the Placement Engine never receives ambiguous instructions.
- **No coordinates until Placement Engine**: The prohibition on Agent 3 producing any numbers eliminates an entire class of errors where an LLM hallucinates a coordinate that sounds plausible but is physically impossible.
- **Shared preprocessing**: All three variants use the same SKU pool, the same zone min-widths, and the same spatial geometry. Variants differ in strategy, not in the foundational facts they are built on.
- **All measurements in mm**: Consistent with `catalog.json`, `render.py`, and the NKBA measurement tables. Mixing units was explicitly prohibited in `CODING_STANDARDS.md`.

---

## 2. Prompting Strategy & Reasoning Design

### 2.1 Philosophy: Structured Output Over Free Text

The most important prompt engineering decision in this project was the rejection of free-text LLM output.

When an agent produces free text, the downstream code that parses that text becomes a secondary problem. It is fragile — a single changed sentence structure, a different synonym, an extra word — can silently break parsing. It also creates a dependency on the exact wording of every response, which makes the system brittle across model versions or prompt changes.

Instead, every agent in this system uses `tool_choice` — forced structured output via the tool use API. Each agent has a single tool whose schema defines exactly what the model must produce. The model has no option to produce prose; it can only fill in the tool schema. This eliminates parsing fragility entirely.

```python
# Agent 1 — tool_choice forcing structured extraction
response = client.messages.create(
    model=model,
    tools=[extract_intent_tool_schema],
    tool_choice={"type": "tool", "name": "extract_intent"},
    ...
)
# Response always has exactly one tool_use block with the exact schema
tool_input = response.content[0].input
```

Agent 2 uses a multi-turn tool loop pattern — the model can call MCP tools multiple times before finalizing its selection, which allows it to progressively refine queries (first get all SKUs by category, then filter by price tier, then check dimensions).

### 2.2 Agent 1 — Prompt Parser: Prompting Strategy

Agent 1's system prompt is deliberately permissive. The key insight was that a kitchen design assistant that refuses requests or says "I cannot determine the color" is worse than useless — it produces a null result that propagates through the pipeline and gives the user no design. The system prompt therefore has one overriding rule: **never fail, always extract best effort**.

```
You are a kitchen design intent extractor.
Rules:
- NEVER fail or return an error — always extract best-effort information
- If a field cannot be determined from the prompt, set it to null
- Extract kitchen-related requests ONLY — log non-kitchen requests in "ignored"
- Color keywords must be resolved to a hex code
- Layout family: L (two walls), U (three walls), I (single wall run)
  — only set if the user explicitly mentions a shape
Always respond using the extract_intent tool.
```

A critical lesson learned here: the initial prompt did not include the instruction "only set layout_family if explicitly mentioned." This caused the model to infer a layout family even when the user said nothing about shape — for example, inferring "L-shape" from "I have a corner kitchen." That inference was frequently wrong and forced all three variants into the wrong shape. Adding the explicit qualifier "only set if the user explicitly mentions" eliminated the false positives.

**Deterministic overrides on top of LLM output**: Even after the tool response comes back, two fields are always re-derived deterministically:

- `color_hex`: If the prompt contains a hex code (`#[0-9A-Fa-f]{6}`), a regex extracts it and overwrites whatever the LLM produced. LLMs sometimes approximate hex codes when they should be exact.
- `layout_family`: A lookup against a 30-entry table of color keywords is used to normalize color names to hex before the LLM call, reducing the chance of the model inventing an incorrect hex code for obscure color names.

### 2.3 Agent 2 — Catalog Selector: Prompting Strategy

Agent 2's prompt is the most complex because it interacts with MCP tools. The system prompt explains the 9 available tools and the selection goal:

```
You are a kitchen catalog selector. Your task is to select appropriate
kitchen items from the catalog based on the user's intent and the room's
spatial constraints.

Available tools:
- get_skus_by_category(category) — returns SKUs filtered by category
- get_skus_by_price_tier(tier) — filters by low/mid/high/premium
- get_sku_dimensions(sku_id) — returns exact dimensions in mm
- resolve_color(keyword) — returns nearest catalog color hex
[... 5 more tools ...]

Rules:
- NEVER invent a SKU — only use what the tools return
- Select at minimum: one fridge, one sink, one stove, one hood,
  one dishwasher, and enough base cabinets to fill the primary wall
- If a must-have item is not available in the budget tier,
  try the adjacent tier (mid → high)
```

The key prompt engineering insight here was moving the full catalog JSON into the system prompt cache block. The initial implementation passed the catalog as a user message on each turn of the tool loop. This meant the model was re-reading 120 SKUs on every call, and caching wasn't being applied to the most expensive context. Moving it to the system prompt's cached block immediately reduced token costs on repeat calls by roughly 15%.

**Gap-fill pool logic**: The user prompt to Agent 2 also includes explicit instructions about width coverage:

```
The room's primary wall is {primary_wall_length_mm}mm long.
Ensure the selected base cabinet set includes at least one SKU of each
standard width (1200, 900, 750, 600, 450, 300mm) so the Placement Engine
can fill any residual gaps without spillover.
```

This prevents the scenario where the placement engine runs out of appropriately-sized filler cabinets and is forced to either leave large gaps or mark items as spillover.

### 2.4 Agent 3 — Layout Strategist: Semantic Vocabulary Design

Agent 3's prompt design is the most carefully engineered in the system, because its output directly controls coordinates. A single hallucinated number from Agent 3 could produce a physically impossible placement.

The solution was designing a controlled semantic vocabulary — eleven position terms, no more, no less — and building the placement engine as a deterministic translator of these exact terms:

| Term | What the Placement Engine Does |
|------|-------------------------------|
| `"at north-west corner"` | x=0, y=wall_depth |
| `"at north-east corner"` | x=wall_length−item_width, y=wall_depth |
| `"at south-west corner"` | x=0, y=0 |
| `"at south-east corner"` | x=wall_length−item_width, y=0 |
| `"near {wall} window"` | x=window_center ± item_width/2, clamped to free segment |
| `"centre of {wall}"` | x=(wall_length−item_width)/2 |
| `"left end of {wall}"` | x=start of first free segment |
| `"right end of {wall}"` | x=wall_length−item_width |
| `"next to {item_name}"` | x=referenced_item.x + referenced_item.width |
| `"above {item_name}"` | z=referenced_item.z + referenced_item.height |
| `"leave gap before {item_name}"` | 600mm buffer before named item |

The system prompt for Agent 3 repeats this vocabulary three times — once as a list, once with examples, once as a constraint — and ends with: "Using ANY other term is a violation. If you are uncertain, use 'left end of [wall]'."

Despite this, the model occasionally produced hybrid terms like "at the right corner of the north wall" or "along the north_wall near the corner." These are not in the vocabulary and cannot be parsed deterministically. The output validation step (`_validate_terms`) uses regex pattern matching to catch these and replace them with the fallback. Importantly, this replacement is always logged so the system's behavior is auditable.

### 2.5 Variant Seed Differentiation

One of the harder design problems was producing three genuinely different kitchen layouts. Without seed differentiation, three concurrent calls to the same model with the same input would often converge to nearly identical layouts — the model would find one good solution and repeat it.

The seed strategy injects a different design philosophy into each variant call:

```python
SEEDS = {
    1: "Prefer L-shape. Maximise counter run on the longest wall. Fridge at far end.",
    2: "Prefer U-shape. Close the work triangle tightly. Dishwasher opposite the sink wall.",
    3: "Prefer I-shape or island. Minimise total cabinet cost. Use narrower SKUs where possible.",
    4: "Maximise storage. Prioritise tall cabinets and wall cabinets over base units.",
    5: "Accessibility focus. Maximise aisle widths. No tall cabinets blocking circulation.",
}
```

This approach worked well, but there was an early bug: the seed suffix was being appended to the user message on the outer turn, not injected into the per-variant strategy. All three variants were therefore receiving all three seed strings concatenated, which confused the model into producing a compromise between strategies rather than a committed design in one direction. The fix was injecting exactly one seed string, chosen by `variant_index`, into each call's prompt context.

**Mode A vs Mode B** is another important branch in the strategy. If the user specifies a layout shape explicitly (Mode A), all variants use that shape and vary only in zone placement and item priorities. If the user does not specify a shape (Mode B), the seed determines the shape — variant 1 produces an L-shape, variant 2 a U-shape, variant 3 an I-shape or island. This gives the user three qualitatively different structural options when they have not expressed a preference.

### 2.6 Retry Prompt Extension

When a variant scores below 0.60, or violates WORKFLOW-03 (work triangle outside 3962–6600mm) or NKBA-CL-01 (fridge clearance below 1067mm), the system retries with Agent 3 running on Claude Opus 4.7 and an extended prompt:

```
RETRY MODE: The previous plan for {variant_id} violated these rules:
[
  {"rule_id": "WORKFLOW-03", "message": "Work triangle 3200mm — below 3962mm minimum"},
  {"rule_id": "NKBA-CL-01",  "message": "Fridge clearance 800mm — below 1067mm minimum"}
]

Re-plan to fix ALL violations listed above. Pay special attention to:
- Work triangle perimeter must be 3962mm–6600mm (NKBA official minimum = 13 feet)
- Fridge must have 1067mm clear space in front of its door swing
The previously placed items are available in your context.
```

The violations are passed back as structured JSON so the model can reason over them precisely rather than interpreting a prose description of what went wrong.

### 2.7 Prompt Caching Architecture

All three agents use Anthropic's prompt caching on their static content:

- **Agent 1**: System prompt cached (NKBA rule list + extraction schema). User prompt is never cached (unique per request).
- **Agent 2**: System prompt + full catalog JSON cached together. This is the largest cache block — 120 SKUs with dimensions, constraints, and metadata. Savings on repeat requests are substantial.
- **Agent 3**: System prompt + room geometry template cached. Variant-specific seed suffix and retry violations are not cached.

The key lesson was understanding that caching applies to the prefix of the message, not arbitrary sections. The order of content blocks matters: static content must appear first. The initial Agent 2 implementation placed catalog JSON in the user message on each tool loop turn, which prevented caching. Moving it to the system prompt block was a significant change in how the API call was structured.

---

## 3. Retrieval, Planning & Layout Generation

### 3.1 Catalog Retrieval Strategy

The catalog contains 120 SKUs across all major categories: base cabinets (9 width variants), wall cabinets (7 widths), tall cabinets, appliances (fridge, stove, hood, dishwasher, microwave, oven), sinks, islands, and fixtures.

Retrieval is a multi-stage filter rather than a single query:

**Stage 1 — Budget filter**: The `get_skus_by_price_tier(tier)` MCP tool returns all SKUs matching the budget tier (low/mid/high/premium). This is the initial population before any further filtering.

**Stage 2 — Color filter**: The `resolve_color(keyword)` tool converts the user's color keyword to a hex code via CIE76 delta-E comparison (tolerance ≤ 15). This means "navy blue" and "#1F3A5F" and "midnight navy" all resolve to the same catalog color group. SKUs within that color group are flagged for priority selection.

**Stage 3 — Style filter**: The `get_skus_by_style(style)` tool returns SKUs tagged with the matching aesthetic style. Style preferences override budget tier when the user has expressed a strong style preference.

**Stage 4 — Must-have guarantee**: Regardless of budget tier results, the system always ensures at least one SKU for: fridge, sink, stove, hood, dishwasher, base cabinets. If any must-have category is absent from the budget tier results, the adjacent tier is searched. If still absent, the full catalog is searched. Appliances and key fixtures are never left out.

**Stage 5 — Gap-fill pool**: One cabinet of every standard width (1200, 900, 750, 600, 450, 300mm) is added to the selection pool, even if not explicitly chosen. This ensures the placement engine's fill pass always has the right cabinet width to close any residual gap on a wall without requiring spillover.

**What we tried first and abandoned**: The initial approach passed a simple text prompt to Agent 2 asking it to "select appropriate cabinets." Without tool_choice, the model produced a list of cabinet names in free text that did not always match catalog IDs exactly. Parsing this introduced a normalization layer that was fragile. Moving to a tool loop where every selection step is verified against MCP tool results eliminated the hallucination problem entirely.

### 3.2 Zoning and Planning Decisions

Before Agent 3 can produce a layout strategy, the system has already determined:

- Which walls exist and their lengths
- Which walls support cabinets (`has_cabinets` flag)
- The free segments on each wall after subtracting openings
- The layout capacity (I / L / U)
- The priority ordering of walls (longest first)

Agent 3 then receives this spatial context and produces zone assignments: which kitchen function (cleaning, cooking, cooling, preparation, storage) goes on which wall. These assignments drive the work triangle calculation — sink, stove, and fridge must be distributed to form a valid triangle perimeter of 3962–6600mm.

The zone-to-wall assignment is where the LLM's spatial reasoning adds genuine value. Given a room with a window on the north wall, the model consistently assigns the sink to the north wall (near the window, for natural light and ventilation) and places the stove on an adjacent wall to create a usable work triangle. It knows not to put the stove and fridge adjacent without a separation gap. This knowledge is not programmed — it comes from the model's training on kitchen design content.

### 3.3 Layout Typology Enforcement

Three layout families are supported, each with different wall requirements:

- **I-shape**: Single wall of cabinets. Placement engine fills one wall linearly.
- **L-shape**: Two adjacent walls. The primary wall gets the bulk of the run; the secondary wall gets the corner-anchored items (fridge, tall cabinets) and overflow.
- **U-shape**: Three walls. The work triangle can be tighter. Dishwasher is typically placed opposite the sink wall. The third wall is often storage-heavy.

Layout capacity is determined purely by the spatial engine — it checks how many walls have `has_cabinets=True` and whether they form a connected path. Agent 3 cannot override this. If the room only has two cabinet walls, a U-shape plan from Agent 3 triggers a capacity-aware fallback in the placement engine that degrades to L-shape and logs a constraint violation.

This is another example of the LLM/deterministic division: the model chooses shape strategy, but the deterministic code enforces physical feasibility.

### 3.4 The Placement Engine's DP Algorithm for Fill Cabinets

One of the more interesting engineering decisions in the placement engine was replacing a greedy fill algorithm with dynamic programming for wall cabinet placement.

The greedy approach was simple: after anchored items were placed, scan the remaining free segments from left to right and fill with the widest available cabinet that fits. This worked adequately for well-proportioned rooms but produced ugly results for unusual segment lengths. For example, a free segment of 1050mm would be filled with a 900mm cabinet, leaving a 150mm gap that was too small for any standard cabinet (minimum 300mm) and triggered a "residual gap" warning. A segment of 1350mm would get a 1200mm cabinet with a 150mm residual.

The DP solution treats this as an interval partitioning problem: given a list of available cabinet widths and a free segment length, find the combination of cabinets that covers the segment most completely with minimum residual gap, preferring wider cabinets to avoid fragmentation. The objective function penalizes gaps greater than 50mm (the LAYOUT-03 rule threshold).

```python
# Wide-biased DP: prefer larger cabinets, minimize residual gap
def _dp_fill(self, segment_length: float, available_widths: list[float]) -> list[float]:
    widths = sorted(set(available_widths), reverse=True)  # widest first
    dp = {0: []}  # maps filled_length → cabinet_list
    for w in widths:
        new_dp = {}
        for filled, cabs in dp.items():
            new_filled = filled + w
            if new_filled <= segment_length + 50:  # allow 50mm tolerance
                new_dp[new_filled] = cabs + [w]
        dp.update(new_dp)
    best = max(dp.keys(), key=lambda x: x - abs(segment_length - x))
    return dp[best]
```

This eliminated the 1050mm and 1350mm gap problems that were generating false LAYOUT-03 violations on otherwise valid layouts.

### 3.5 Variant Differentiation in Practice

With the seed system, three variants generated for the same input room are structurally different:

- **Variant 1 (L-shape, counter-maximizing)**: Uses the longest wall for a full counter run from sink to stove, fridge at the far end of the secondary wall. Maximum continuous countertop. High NKBA-25 (countertop total ≥ 4013mm) compliance.
- **Variant 2 (U-shape, tight triangle)**: Distributes appliances across three walls to minimize work triangle perimeter. Dishwasher placed on the wall opposite the sink. Best work triangle scores.
- **Variant 3 (I-shape or island, cost-minimizing)**: Uses narrower SKUs, fewer wall cabinets, prioritizes affordability. Often the lowest-cost variant.

The guarantee that variants are meaningfully different comes from two mechanisms: seed injection ensuring different strategies, and variant-level scoring that allows each variant to succeed or fail on its own merits through the retry mechanism.

---

## 4. Reliability, Validation & Evaluation

### 4.1 The 31-Rule NKBA Validation Engine

The NKBA validator is the system's single largest module at 1,502 lines. It implements 31 rules in pure Python with no LLM calls. Every rule is either a distance check, a clearance check, an adjacency check, or a coverage check — all computable from the `positioned_items` dictionary.

Rules are grouped into two sets:

**Project Rules (11)** — These are the system's internal design quality checks:
- `NKBA-CL-01`: Fridge door swing — 1067mm clear in front of fridge
- `NKBA-CL-02`: Door swing reservation — 900×900mm clear inside door arc
- `WORKFLOW-01`: Dishwasher within 600mm of sink edge
- `WORKFLOW-02`: Stove at least 600mm from fridge on same wall
- `WORKFLOW-03`: Work triangle perimeter 3962–6600mm (critical — highest weight)
- `LAYOUT-01`: Sink within 300mm of nearest window centerline
- `LAYOUT-02`: Hood centered over stove within 100mm
- `LAYOUT-03`: No gap > 50mm between consecutive items on same wall
- `LAYOUT-04`: Every appliance backed by a base cabinet
- `LAYOUT-05`: Counter run terminates at base cabinet or corner
- `LAYOUT-06`: Fridge and tall cabinets at ends or corners only

**Official NKBA Rules (20)** — The published 2023 NKBA guidelines:
- NKBA-01: Entry clearance ≥ 813mm
- NKBA-06: Work aisle ≥ 1067mm (single cook), ≥ 1219mm (two-cook)
- NKBA-11: Sink landing areas ≥ 610mm one side, 457mm other
- NKBA-13: Dishwasher within 914mm of sink
- NKBA-18: Clearance above cooktop ≥ 610mm
- NKBA-25: Total countertop frontage ≥ 4013mm
- (plus 14 others covering landings, seating, ventilation, and paths)

### 4.2 The Scoring Formula

Each variant receives a composite score between 0 and 1.3:

```
SCORE = 1.0
      + (rules_passed / 31) × 0.30         # NKBA compliance bonus
      − (spillover_count × 0.05)            # penalty per dropped item
      − (collision_count × 0.05)            # penalty per collision
      − sum(RULE_WEIGHTS[v] for v in violations)  # weighted rule penalties
```

Rule weights reflect severity: WORKFLOW-03 (work triangle) carries 0.15 because a kitchen with an invalid work triangle is fundamentally unusable. NKBA-CL-01 (fridge clearance) and NKBA-CL-02 (door arc) each carry 0.10 because they represent real safety and usability hazards. Minor layout rules like LAYOUT-06 carry 0.06.

A score above 0.80 indicates a high-quality layout. 0.60–0.80 is acceptable with some violations. Below 0.60 triggers the retry mechanism.

The maximum theoretical score of 1.30 (all 31 rules pass, no spillover, no collisions) is rarely achieved in practice because typical room geometries involve at least a few soft violations — a window placement that makes LAYOUT-01 technically fail, or a room that is too small to achieve the full NKBA-25 countertop frontage. Scores in the 0.85–1.10 range are the observed norm for well-designed variants.

### 4.3 Collision Detection and the Whitelist

Collision detection is a 3D axis-aligned bounding box check. Two items collide if their x-ranges, y-ranges, and z-ranges all overlap simultaneously.

However, not all overlaps are errors. Four pairs are whitelisted:
- `hood ↔ stove`: The hood hangs above the stove. Their bounding boxes share the z-axis range between counter height and hood mounting height.
- `tap ↔ sink`: A tap is a sub-item of the sink unit and occupies the same x/y footprint.
- `wall_cabinet ↔ base_cabinet`: Wall cabinets are mounted above base cabinets. They share the same x-range on the wall.
- `dishwasher ↔ base_cabinet`: Integrated dishwasher panels share an x boundary with adjacent base cabinets.

Without this whitelist, the collision detector would flag every valid kitchen layout — there is always a hood above the stove. The whitelist is a good example of domain knowledge that must be explicitly encoded.

### 4.4 Handling Malformed LLM Outputs

The system has multiple defensive layers against malformed LLM output:

**Agent 1 failures**: If the API call fails entirely, `parse()` catches the exception and returns an empty but valid `IntentDTO` with all nulls. The pipeline continues with defaults from the input JSON preferences.

**Agent 2 failures**: If SKU selection fails, the system falls back to the full catalog (no filtering) and selects baseline must-have items by category. The user gets a default set rather than a pipeline failure.

**Agent 3 term validation**: Every semantic term in the `wall_strategies` output is validated against the vocabulary regex. Unknown terms are replaced with `"left end of {wall}"` and logged as warnings. The placement engine always has a valid input.

**Placement geometry failures**: If a semantic position resolves to coordinates outside the wall's free segments (for example, "at north-east corner" on a wall where the corner is occupied by a door), the placement engine clamps the position to the nearest valid free segment start and logs a constraint warning.

**Retry on low score**: If the first-pass score is below threshold, the system retries with more capable reasoning (Opus) and explicit violation context. The maximum retry depth is one — if the retry also fails, the original variant is kept with its warnings intact rather than producing a failure.

### 4.5 Key Bug Discovered: WORKFLOW-03 Minimum Value

One of the more consequential bugs in the system was using `3600mm` as the minimum work triangle perimeter. The system was accepting layouts where the triangle was as small as 3600mm as valid.

The official NKBA standard states the minimum as 13 feet, which converts to 3962mm — not 3600mm. This bug meant that approximately one in five I-shape variants was receiving a "valid" score for a work triangle that would fail an NKBA inspection. The fix was updating the constant in the validator:

```python
# Wrong — was using 3600mm
WORK_TRIANGLE_MIN_MM = 3600.0

# Correct — official NKBA minimum = 13 feet
WORK_TRIANGLE_MIN_MM = 3962.0  # 13 feet × 304.8mm/foot
```

This bug was discovered during integration testing when a layout with a clearly tight kitchen scored well on WORKFLOW-03 while failing the visual inspection. The comment in the code now explicitly states the feet-to-mm conversion to prevent the mistake from being reintroduced.

### 4.6 Rationale Generation: The Pivot Away from LLM

The original design included a fourth LLM agent (Agent 4 — RationaleWriter) that received each variant's placement result and NKBA violations and produced a set of human-readable rationale statements explaining the design decisions and any rule violations.

This was implemented and shipped. It worked. But it was also the most expensive operation in the pipeline: three Haiku calls per request, all for text that was fundamentally templated. The rationale for "fridge door clearance is 1200mm — exceeds the 1067mm NKBA minimum" is the same every time NKBA-CL-01 passes. The rationale for "work triangle is 3500mm, below 3962mm minimum" is the same every time WORKFLOW-03 fails.

The pivot was replacing Agent 4 with `utils/rationale_lookup.py` — a static lookup table keyed on rule ID and pass/fail state:

```python
RATIONALE_LOOKUP = {
    ("WORKFLOW-03", "pass"): "Work triangle perimeter within the 3962–6600mm NKBA range.",
    ("WORKFLOW-03", "fail"): "Work triangle perimeter outside NKBA range ({perimeter}mm). "
                             "Consider redistributing sink, stove, or fridge to different walls.",
    ("NKBA-CL-01", "pass"): "Fridge door has {clearance}mm clear — exceeds 1067mm NKBA minimum.",
    ("NKBA-CL-01", "fail"): "Fridge clearance {clearance}mm is below 1067mm NKBA minimum. "
                             "Relocate to a wall end with more open space in front.",
    # ... 29 more entries ...
}
```

Values in braces are filled in from the violation data. The result is rationale text that is consistent, accurate, and zero-cost per request. The trade-off is that the language is more templated than what a fine-tuned writer would produce — but for a technical compliance report, consistent templated language is actually a feature, not a limitation.

### 4.7 Evaluation Signals

The system produces four layers of evaluation signal for every variant:

1. **Score (0.0–1.3)**: Composite weighted score visible in the UI with color-coded badge (green >0.8, amber 0.6–0.8, red <0.6).
2. **NKBA compliance percentage**: The fraction of the 31 rules passed. Displayed as a checklist in the Design Review tab.
3. **Violation list**: Structured list of rule IDs, human-readable messages, and severity. Each violation has a corresponding rationale entry.
4. **Spillover and collision logs**: Named items that could not be placed on their primary wall, and any collision pairs (after whitelist filtering).

---

## 5. Cost Optimization & Scalability

### 5.1 Model Tiering

The most impactful cost decision is using three different model tiers for different tasks:

| Agent | Model | Why |
|-------|-------|-----|
| Prompt Parser (Agent 1) | Claude Haiku 4.5 | Intent extraction is pattern recognition, not reasoning. Fast and cheap. |
| Catalog Selector (Agent 2) | Claude Haiku 4.5 | Multi-turn tool use for filtering. Haiku handles tool loops well. |
| Layout Strategist (Agent 3) primary | Claude Sonnet 4.6 | Spatial reasoning across multiple constraints. Needs the reasoning capacity. |
| Layout Strategist (Agent 3) retry | Claude Opus 4.7 | Only triggered on clear failure. Reserved for hard constraint recovery. |

The cost profile per request (3 variants, no retry) is approximately:
- Agent 1: ~200 input tokens, ~100 output tokens (Haiku) — negligible
- Agent 2: ~3,000 input tokens (catalog + context), ~500 output tokens across 3 tool turns (Haiku)
- Agent 3 × 3: ~1,500 input tokens each, ~300 output tokens each (Sonnet) — dominant cost

Retry with Opus adds substantially more cost per failing variant. The retry trigger thresholds (score < 0.60) are therefore calibrated conservatively — mild violations that do not indicate fundamental layout failure are not retried.

**Model selection is centralized in `utils/model_selector.py`**: no agent file contains a model string. This allows switching models project-wide for any agent without touching agent code:

```python
from utils.model_selector import for_agent
model = for_agent("layout_strategist")          # → "claude-sonnet-4-6"
model = for_agent("layout_strategist", is_retry=True)  # → "claude-opus-4-7"
```

### 5.2 Prompt Caching

All three agents cache their static system prompts using the `cache_control: {"type": "ephemeral"}` header on the system message. The benefits are:
- Roughly 10–20% reduction in billed input tokens on repeat requests (cache hits)
- Improved latency on cached blocks (typically 2–3× faster for cached content)
- Agent 2's catalog JSON is the biggest savings: 120 SKUs × ~50 tokens/SKU = ~6,000 tokens cached on second and subsequent requests

The initial implementation placed the catalog JSON in the user message instead of the system message. This was architecturally wrong — user messages are not eligible for prefix caching in the same way, and the catalog content was being re-read as uncached tokens on every turn of the tool loop. Moving the catalog to a cached system block required restructuring the Agent 2 prompt but immediately showed measurable token savings on integration tests.

### 5.3 Deterministic Rationale (Zero Agent 4 Cost)

As discussed in Section 4.6, replacing the RationaleWriter LLM call with a static lookup table eliminated an entire class of API calls. For a production deployment handling many requests per day, this is significant — approximately 3 Haiku calls per request (one per variant) eliminated entirely.

### 5.4 MCP Queries Run Once

Agent 2's MCP tool calls run once and their results are stored in `PreprocessingOutput.skus` and `PreprocessingOutput.zone_groups`. These are shared across all three variants. The system does not re-query the catalog for each variant — a common antipattern that would triple the MCP overhead.

### 5.5 Parallel Execution

Layers 3 through 5 run in parallel per variant using `asyncio.gather`. For three variants, the wall-clock time for these layers is approximately equal to the time for a single variant rather than three times as long.

An early performance bug: Agent 3's initial implementation used synchronous Anthropic API calls inside an `async` coroutine. Python's event loop does not parallelize blocking calls — `asyncio.gather` on three coroutines that each block the thread is functionally sequential. The fix was wrapping the synchronous API call in `asyncio.to_thread`:

```python
# Wrong — blocks event loop, no true parallelism
async def _plan_single(self, ...):
    response = self.client.messages.create(...)  # synchronous — blocks

# Correct — releases event loop between calls
async def _plan_single(self, ...):
    response = await asyncio.to_thread(
        self.client.messages.create, ...
    )
```

After this fix, three concurrent Agent 3 calls for three variants ran in approximately the time of one serial call.

### 5.6 Scalability Considerations

The current system scales horizontally well because:
- Each request is fully independent — no shared state between requests
- The MCP server can be pre-started as a sidecar and its connection reused across requests
- The LangGraph state machine is stateless between invocations

For a larger catalog (say, 500 SKUs instead of 120), the main bottleneck would be Agent 2's token context. Mitigation options would include:
- Pre-filtering the catalog to the top-N SKUs for the budget tier before building the Agent 2 prompt
- Indexing SKUs into a vector store and using semantic retrieval to pass only the most relevant SKUs to the LLM
- Splitting Agent 2 into two phases: a retrieval phase (vector search) and a selection phase (LLM reasoning over the retrieved subset)

For higher request volume, the main cost driver would be Agent 3 (Sonnet calls). This could be mitigated by caching the zone plans for identical room geometries and intent signatures (a hash of the spatial output and intent), since the same room with the same preferences should produce the same variants.

---

## 6. Learnings, Design Decisions & Future Improvements

### 6.1 What Went Well

**The LLM/deterministic split**: The decision to restrict LLMs to semantic reasoning and keep all coordinate computation deterministic was the right call. The system's correctness is anchored in the deterministic layers, and the LLMs add value in exactly the places where rule-based approaches would struggle (natural language understanding, design trade-off reasoning).

**Tool_choice for structured output**: Every agent produces structured output via the tool API rather than free text. This made downstream parsing zero-fragility and allowed the system to be built with confidence that the interface contracts between agents would hold.

**Semantic vocabulary constraint**: Designing a controlled vocabulary for Agent 3 and building the placement engine as a translator of that vocabulary was the decision that made the placement layer tractable. It is the core architectural insight of the system.

**LangGraph for orchestration**: Using LangGraph meant the retry logic, conditional edges, and state passing between nodes were all declarative rather than hand-coded. The conditional edge `should_retry → zone_planner | output` is a one-line definition that encapsulates the entire retry mechanism. Without a framework, this would have been a tangle of callback chains.

**Static rationale lookup**: Replacing Agent 4 with a lookup table was a good pragmatic call. The rationale text quality is consistent and accurate, the cost is zero, and the system has one fewer external API call in the critical path.

### 6.2 What Did Not Work Well

**Initial free-text output from Agent 3**: Before the semantic vocabulary was enforced, Agent 3 was given latitude to describe positions in natural language. This produced phrases like "near the eastern end, slightly offset from the corner" that the placement engine could not parse reliably. Two weeks of iteration on parsing logic were eliminated by the vocabulary constraint.

**Greedy wall cabinet fill**: The greedy fill algorithm worked for simple cases but consistently failed on rooms with walls whose free segments had lengths that were not multiples of standard cabinet widths. The DP replacement was more complex to implement but eliminated a long tail of false LAYOUT-03 violations.

**Plotly 3D viewer**: The initial 3D visualization used Plotly's 3D scatter/mesh plot. It was slow to render, had poor interaction, and the camera controls were unintuitive. Replacing it with a Three.js viewer embedded in an HTML component improved render performance by roughly 10× and gave proper orbit controls.

**Async not truly parallel**: The synchronous API call inside an async coroutine was a subtle performance bug that was only caught through profiling. The fix was straightforward once identified, but it illustrates how easy it is to create false parallelism in async Python.

**WORKFLOW-03 constant error**: Using 3600mm instead of 3962mm as the work triangle minimum was a unit conversion error. The constant looked reasonable (10 feet in rough terms) but was actually wrong. This was caught by NKBA reference checking during integration testing. The lesson is that NKBA constants need to be sourced directly from the specification, not approximated.

**input2.json dimension bug**: Test input `input2.json` had room dimensions listed as 42000mm × 42000mm — apparently a copy-paste error when creating the file (one too many zeros). The spatial engine and placement engine both handled it without errors, which made the bug invisible until a rendered output showed a room the size of a warehouse. The lesson here is the importance of sanity checks on inputs at the system boundary, not just internal validation.

### 6.3 Key Architectural Decisions

**Define DTOs first**: All data contracts (`dtos/contracts.py`) were defined before any pipeline implementation began. This forced clarity about what each layer's interface actually was, and prevented later integration pain where layers were producing and consuming incompatible data shapes.

**No coordinates in LLM output**: This was a pre-commitment. Once the vocabulary was defined and the placement engine was written as its interpreter, there was no path back. This constraint also made testing much easier — the test for Agent 3 does not need to check coordinate values, only vocabulary compliance.

**One retry pass per variant, Opus only**: The retry threshold and escalation policy were calibrated to be conservative. Over-retrying would triple costs for marginal score gains. The policy triggers only on clear failures (score < 0.60 or the two highest-weight rule violations).

**Validation rationale from lookup, not LLM**: This decision was made after the RationaleWriter was already implemented and tested. The upgrade was driven by cost, not quality — Haiku rationale quality was acceptable but not exceptional, and the templated version was indistinguishable to users. The trade-off was entirely one-sided in favor of the lookup approach.

### 6.4 Patterns Worth Reusing in Future LLM Systems

**Semantic vocabulary as the LLM/code interface**: The pattern of designing a controlled output vocabulary and building a deterministic interpreter of that vocabulary is generalizable to any system where an LLM must produce structured decisions. It separates the "what" (LLM reasoning) from the "how" (deterministic execution) cleanly.

**Dual-mode variant generation (Mode A / Mode B)**: When users can either constrain a parameter or leave it open, handling both modes explicitly — rather than trying to handle the null case with default logic — produces much better results. Mode A (user-specified shape) and Mode B (seed-determined shape) have different semantic requirements and should be handled as distinct prompting branches.

**MCP as a clean retrieval abstraction**: Using MCP to expose the catalog as a set of queryable tools (rather than dumping the entire catalog into the prompt) gave Agent 2 structured access to filtered views. Even though the full catalog is cached for token efficiency, the tool structure forces the model to think in terms of query operations rather than scanning a flat list.

**Centralized model selection**: Never hardcoding model names in agent code paid dividends when model versions were updated. Switching from an older Haiku to Haiku 4.5, or from Sonnet 4.5 to 4.6, was a single constant change in `utils/model_selector.py`.

### 6.5 Tradeoffs Encountered

**LLM cost vs. quality on retry**: Escalating to Opus on retry significantly improves variant quality for the most complex room geometries. But it also substantially increases cost for that request. The threshold of 0.60 is a pragmatic balance — below this score, the layout is likely genuinely unusable, and the cost of Opus is justified.

**Semantic vocabulary expressiveness vs. determinism**: The eleven-term vocabulary cannot express everything a designer might want. Some legitimate placements — "third cabinet from the left" or "between the window and the door" — cannot be expressed in the vocabulary and collapse to the nearest term. This is the cost of the deterministic interpreter guarantee. The alternative would be a richer vocabulary with more complex parsing, which re-introduces fragility.

**Three variants vs. five**: The system is designed to support 3–5 variants (as reflected in the seed table). Running with three is the default for latency and cost reasons. The architecture supports five without code changes — just passing `n_variants=5`.

**Tight NKBA enforcement vs. permissive scoring**: The 31-rule NKBA validator is rigorous. Many real kitchens would fail several rules due to space constraints that a homeowner simply cannot change. The scoring system handles this gracefully — violations reduce the score but do not prevent the variant from appearing. The user sees what rules are violated and can make an informed choice.

### 6.6 What Would Be Improved With More Time

**CSP/solver integration**: For placement, a constraint satisfaction solver (such as Google OR-Tools or Z3) could replace the current greedy+DP approach. A CSP would guarantee optimal placement subject to all constraints simultaneously, rather than handling them in priority order (anchored → dependent → fill). The current approach occasionally places a fill cabinet that then blocks a clearance zone that could have been avoided by a different ordering.

**Self-critique loop**: A more sophisticated retry mechanism would not just re-call Agent 3 with violation context — it would have Agent 3 score its own plan before passing it to the placement engine, allowing the model to catch semantic violations (like placing the fridge on a wall that is too short for the required clearance) before they become placement engine errors.

**Better evaluation harness**: The current evaluation relies on the NKBA validator and visual inspection. A stronger evaluation would include:
- Automated comparison of layouts against a set of reference designs labeled by kitchen design professionals
- A "design sensibility" scoring model fine-tuned on designer ratings
- Systematic regression testing on all three input JSON files after any code change to detect scoring regressions

**Vector-indexed catalog**: For larger catalogs, replacing the filtered MCP queries with semantic vector search would improve selection quality. A query like "modern handleless base cabinet with soft-close hinges" would benefit from dense retrieval over a flat keyword filter.

**Layout rendering with measurements**: The current renderer produces a clean top-down view but does not annotate measurements. Adding mm annotations (wall lengths, item widths, aisle widths, work triangle perimeter) directly on the rendered output would make the Designer View tab significantly more useful for professional review.

**Progressive streaming UI**: The current UI runs the entire pipeline and then displays all results at once. A streaming approach would show each variant as it completes placement and scoring, rather than waiting for all three plus the output generator. This would make the user experience feel substantially faster even if wall-clock time is unchanged.

---

## Appendix A: Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         Kitchen Auto-Design System                               │
│                                                                                  │
│  input.json                                                                      │
│      │                                                                           │
│      ▼                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │  Layer 1 — Spatial Engine                          [DETERMINISTIC]       │    │
│  │  • Parse walls, openings, free segments                                  │    │
│  │  • Compute layout_capacity (I/L/U), flow_order                          │    │
│  └──────────────────────────────┬──────────────────────────────────────────┘    │
│                                 │ SpatialEngineOutput                           │
│                                 ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │  Layer 2 — Preprocessor                           [AGENT 1 + MCP + AGENT 2]  │
│  │  • Agent 1 (Haiku): parse prompt → IntentDTO                             │    │
│  │  • MCP server: catalog queries (9 tools)                                 │    │
│  │  • Agent 2 (Haiku): select SKUs, zone groups, min widths                 │    │
│  └──────────────────────────────┬──────────────────────────────────────────┘    │
│                                 │ PreprocessingOutput                           │
│                                 ▼                                               │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  Layer 3 — Zone Planner                           [AGENT 3 × 3 PARALLEL]  │   │
│  │  • Variant 1: seed "L-shape, max counter"                                │   │
│  │  • Variant 2: seed "U-shape, tight triangle"                             │   │
│  │  • Variant 3: seed "I-shape, cost-minimize"                              │   │
│  │  → ZonePlannerOutput[] (semantic positions, zero coordinates)            │   │
│  └────────┬────────────┬────────────┬────────────────────────────────────── ┘  │
│           │            │            │                                           │
│           ▼            ▼            ▼   (Layer 4 × 3 in parallel)              │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  Layer 4 — Placement Engine                       [DETERMINISTIC × 3]    │   │
│  │  • Resolve semantic → mm coordinates                                      │   │
│  │  • DP fill for wall cabinets                                              │   │
│  │  • Collision detection (whitelist applied)                               │   │
│  │  • Spillover to adjacent walls                                           │   │
│  └────────┬────────────┬────────────┬─────────────────────────────────────── ┘  │
│           │            │            │                                           │
│           ▼            ▼            ▼   (Layer 5 × 3 in parallel)              │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  Layer 5 — NKBA Validator                         [DETERMINISTIC × 3]    │   │
│  │  • 31 rules, pure math                                                   │   │
│  │  • Weighted scoring formula                                              │   │
│  │  • Rationale from static lookup table                                   │   │
│  └──────────────────────────────┬──────────────────────────────────────────┘   │
│                                 │                                               │
│             ┌───────────────────┴──────────────────┐                           │
│             │                                       │                           │
│      score ≥ 0.60 &                         score < 0.60 OR                    │
│   no WORKFLOW-03/CL-01                   WORKFLOW-03 OR CL-01                  │
│             │                                       │                           │
│             │                               Retry: Agent 3 on Opus             │
│             │                               + violation context                 │
│             │                               → Placement → NKBA                 │
│             │                                       │                           │
│             └──────────────────┬────────────────────┘                           │
│                                │                                               │
│                                ▼                                               │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  Output Generator                                 [DETERMINISTIC]        │   │
│  │  • Sort by score desc                                                    │   │
│  │  • Serialize to output.json                                              │   │
│  │  • Trigger render.py → PNGs                                              │   │
│  └──────────────────────────────┬──────────────────────────────────────────┘   │
│                                 │                                               │
│                                 ▼                                               │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  Streamlit UI (4 persona tabs)                                           │   │
│  │  Tab 1 — My Kitchen   Tab 2 — Designer View                             │   │
│  │  Tab 3 — Catalog/MCP  Tab 4 — Design Review (NKBA checklist)            │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## Appendix B: Example Agent 3 Output (ZonePlannerOutput)

```json
{
  "variant_id": "variant-1",
  "family": "L",
  "wall_strategies": {
    "north_wall": [
      "sink near north window",
      "dishwasher next to sink",
      "stove right end of north_wall",
      "leave gap before stove"
    ],
    "east_wall": [
      "fridge at north-east corner",
      "tall cabinet next to fridge"
    ]
  },
  "zone_assignments": {
    "cleaning": "north_wall",
    "cooking": "north_wall",
    "cooling": "east_wall",
    "preparation": "north_wall",
    "storage": "east_wall"
  },
  "work_triangle_priority": "tight",
  "adjacency_hints": ["dishwasher next to sink", "stove away from fridge"],
  "avoid_zones": [],
  "self_assessment_score": 0.82
}
```

---

## Appendix C: Scoring Example

**Input**: 4200mm × 3000mm room (input3.json), L-shape, north wall 4200mm, east wall 3000mm, window on north wall at offset 900mm, door on south wall.

**Variant 1 result (L-shape)**:
- Rules passed: 27 / 31
- Violations: LAYOUT-03 (one 80mm gap between dishwasher and stove), NKBA-11 (sink landing 520mm — below 610mm), NKBA-LA-01 (fridge landing 350mm — below 381mm), NKBA-25 (countertop 3800mm — below 4013mm)
- Spillover count: 0
- Score: 1.0 + (27/31 × 0.30) − 0 − 0 − (0.08 + 0.06 + 0.05 + 0.05) = 1.0 + 0.261 − 0.24 = **1.021**
- Badge: green (>0.80)

**Variant 2 result (U-shape)**:
- Rules passed: 29 / 31
- Violations: NKBA-25 (countertop 3950mm — below 4013mm), WORKFLOW-02 (stove-fridge gap 550mm — below 600mm)
- Score: 1.0 + (29/31 × 0.30) − 0 − 0 − (0.05 + 0.10) = 1.0 + 0.281 − 0.15 = **1.131**
- Badge: green

---

## Appendix D: Major Git Commits and What They Represent

| Commit | Description |
|--------|-------------|
| `355af11` | Foundation: all DTOs defined, project scaffold, coding standards |
| `b9b045b` | MCP server: 9 tools, catalog loader, color resolver |
| `4c6178c` | Spatial engine: wall parsing, free segments, layout capacity |
| `e320733` | Agent 1: tool_choice structured extraction, deterministic color/layout overrides |
| `e7624a8` | Agent 2: MCP tool loop, SKU selection, zone grouping |
| `347c722` | Agent 2 fix: catalog JSON moved to cached system block |
| `2e03717` | Agent 3: semantic vocabulary, Mode A/B variants, Opus retry |
| `bdd7daf` | Agent 3 fix: sync API wrapped in asyncio.to_thread for true parallelism |
| `8465309` | Placement engine: semantic→mm resolution, landing allocator, collision detection |
| `0189d09` | Placement fix: landing area allocator wired, adjacent-wall spillover |
| `1313d31` | NKBA validator: all 31 rules, weighted scoring |
| `2c1102b` | NKBA fix: WORKFLOW-03 minimum corrected to 3962mm, room depth derivation fixed |
| `b38989e` | Output generator: rationale via Agent 4 (RationaleWriter) |
| `a96e970` | LangGraph: full state graph, conditional retry edge |
| `954d835` | LangGraph fix: preprocessing node made truly async |
| `c4b9ed4` | Catalog expansion to 120 SKUs, input2.json dimensions corrected from 42000mm→4200mm |
| `6433738` | Placement: greedy wall-cab fill replaced with wide-biased DP algorithm |
| `9560acf` | Placement fix: wall cabs fill above microwave (z-overlap check vs z-level split) |
| `df107c8` | Agents+placement: variant differentiation fixes, U-shape corners, Mode A/B |
| `d346962` | UI: Plotly 3D replaced with Three.js viewer, guardrail report in Tab 4 |
| `cc17a08` | UI: guard llmops import, graceful fallback |

---

*Document version 1.0 — Kitchen Layout Auto-Design System, Project 2*
*All measurements in millimeters. NKBA rule codes reference the 2023 NKBA Kitchen & Bath Planning Guidelines.*
