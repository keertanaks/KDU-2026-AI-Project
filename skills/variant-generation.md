---
name: variant-generation
description: Use when modifying how layout variants are created, seeded, parallelized, retried, or deduplicated. Covers the LangGraph parallel branch pattern, spillover priority, and the 5-seed differentiation table.
version: 1.0.0
last_verified: 2026-05-24
applies_to:
  - agents/layout_strategist.py
  - pipeline/zone_planner.py
  - graph/kitchen_graph.py
  - dtos/contracts.py
tool_risk: high
---

# Variant Generation Skill

## Purpose
Ensure 3–5 meaningful, differentiated variants are produced via the parallel LangGraph branch pattern with correct seeding, retry logic, and spillover handling.

## When to Use
Any feature that changes how many variants are produced, how they differ, how they're parallelized, or how retry is triggered.

## Existing Repo Pattern

**`N_VARIANTS = 3`** in `agents/layout_strategist.py`; variants run in parallel via `asyncio.gather`.

**Parallel branch pattern in `graph/kitchen_graph.py`:** Each variant is a parallel branch node; results are merged into `placed_variants` in `KitchenGraphState`. Do NOT replace with an ad-hoc sequential loop.

**5 variant seeds** (from `CLAUDE.md` and `AGENT_SPECS.md`):
| Slot | Shape (Mode B) | Strategy |
|------|---------------|---------|
| 1 | L | Maximise counter run, fridge at far end |
| 2 | U | Tight work triangle, dishwasher opposite sink wall |
| 3 | I/island | Minimise cost, narrower SKUs |
| 4 | any | Maximise storage, tall + wall cabinets |
| 5 | any | Accessibility focus, wide aisles |

**Retry trigger** (conditional edge in `graph/kitchen_graph.py`): score < 0.60 OR WORKFLOW-03 violated OR NKBA-CL-01 violated → re-run Agent 3 with Sonnet (first retry) or Opus (second retry) with violation list injected.

**Spillover priority**: wall_cabinet → island → NEVER drop appliances or tall cabinets. Tall cabinets: log `LAYOUT-06` penalty, place at nearest corner/end.

## Rules
1. **Never replace the parallel `asyncio.gather` pattern with a sequential loop** — see `pipeline/zone_planner.py` and `graph/kitchen_graph.py`
2. **3 variants minimum at all times** — if retry fails, keep the variant with warnings[], never drop it
3. **Preserve meaningful diversity** — never let all variants collapse to the same shape or placement
4. **Spillover order is mandatory**: wall_cabinet first, then island, never appliances or talls
5. **Retry must inject the violation list** as context to Agent 3 — not just re-run blindly

## Bad Example
```python
# WRONG — sequential, replaces parallel pattern
variants = []
for i in range(N_VARIANTS):
    v = await layout_strategist.run_single(...)
    variants.append(v)

# WRONG — drops a variant on retry failure
if retry_failed:
    variants.remove(bad_variant)  # must keep with warnings
```

## Good Example
```python
# CORRECT — parallel
tasks = [self._plan_single(spatial, preprocessing, i+1) for i in range(N_VARIANTS)]
variants = await asyncio.gather(*tasks)

# CORRECT — keep variant with warnings on retry failure
if retry_also_failed:
    variant.warnings.append("Retry failed: WORKFLOW-03 still violated")
    # keep variant in placed_variants
```

## Common Failure Modes
- Generating 3 variants all with "L" shape — seed differentiation not applied
- Dropping a variant instead of keeping it with warnings when retry fails
- Spillover drops an appliance or tall cabinet — LAYOUT-06 required, never drop

## Must Not Do
- Never replace parallel graph branches with a sequential Python loop
- Never drop a variant — always keep with warnings if retry fails
- Never drop appliances or tall cabinets during spillover

## Completion Checklist
- [ ] Variants run in parallel via `asyncio.gather` or graph branch
- [ ] 3 variants minimum produced, never fewer
- [ ] Each variant uses its designated seed strategy
- [ ] Retry injects violation context
- [ ] Spillover follows wall_cabinet → island priority order
- [ ] Failed retry keeps variant with warnings[]
