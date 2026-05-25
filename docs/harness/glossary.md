# Glossary — Kitchen-Layout-Visualizer

One-page reference for all domain terms. Extracted and condensed from `CLAUDE.md` and `AGENT_SPECS.md`.

---

## NKBA Terms

| Term | Definition |
|------|-----------|
| **NKBA** | National Kitchen & Bath Association — publishes the 31 kitchen design guidelines this system validates |
| **NKBA-CL-01** | Fridge front clearance rule — minimum 1067mm (3.5 ft) in front of the refrigerator |
| **WORKFLOW-03** | Work triangle perimeter rule — must be 3962–6600mm. **Minimum is 3962mm (13 ft) — NOT 3600mm** |
| **LAYOUT-06** | Cabinet overflow/spillover penalty — item forced to corner due to space constraints |
| **COLOR-MATCH** | Rationale entry confirming color keyword was resolved to a catalog SKU |
| **LAYOUT-03** | Gap between adjacent base cabinets > 50mm — violation |
| **LAYOUT-02** | Dishwasher and sink more than 600mm apart — violation |
| **NKBA-CL-02** | Door opening zone — requires 900×900mm clear |

---

## Semantic Vocabulary (Agent 3 only — never mm coordinates)

| Term | Placement Engine Resolution |
|------|---------------------------|
| `"at north-west corner"` | x=0, y=wall_depth |
| `"at north-east corner"` | x=wall_length−item_width, y=wall_depth |
| `"at south-west corner"` | x=0, y=0 |
| `"at south-east corner"` | x=wall_length−item_width, y=0 |
| `"near {wall} window"` | x=window_center ± item_width/2, clamped to free segment |
| `"centre of {wall}"` | x=(wall_length−item_width)/2 |
| `"left end of {wall}"` | x=0 (start of first free segment) |
| `"right end of {wall}"` | x=wall_length−item_width |
| `"next to {item_name}"` | placed immediately adjacent to named item |
| `"above {item_name}"` | z=named_item.z+named_item.height, same x/y centred |
| `"leave gap before {item_name}"` | 600mm buffer before named item |

---

## Mode A vs Mode B

| Mode | Trigger | Behavior |
|------|---------|----------|
| **Mode A** | User specifies `layout_family` in input JSON ("L", "U", or "I") | All variants use that shape; seeds only change zone/item placement strategy |
| **Mode B** | `layout_family=null` | Seed slot determines shape: slot 1→L, slot 2→U, slot 3→I (with capacity fallbacks) |

---

## Variant Seeds

| Slot | Mode B Shape | Strategy |
|------|-------------|---------|
| 1 | L | Maximise counter run on longest wall, fridge at far end |
| 2 | U | Close work triangle tightly, dishwasher opposite sink wall |
| 3 | I/island | Minimise cost, narrower SKUs |
| 4 | any | Maximise storage — tall cabinets and wall cabinets |
| 5 | any | Accessibility focus — wide aisles, no tall cabinets blocking circulation |

---

## Zones

| Zone | Color (UI) | Typical Items |
|------|-----------|--------------|
| Cooking | `#E53E3E` | Stove, hood, oven, microwave |
| Cleaning | `#00D4B1` | Sink, dishwasher |
| Cooling | `#3182CE` | Refrigerator |
| Prep | `#D69E2E` | Base cabinets used for food prep |
| Storage | `#718096` | Wall cabinets, tall cabinets |

---

## Scoring Formula

```
SCORE = 1.0
+ (passed_NKBA / total_NKBA) × 0.30
- (spillover_count × 0.05)
- (adjacency_violations × 0.05)
- sum(RULE_WEIGHTS[v] for v in violations)
```

Score colors: green > 0.8, amber 0.6–0.8, red < 0.6

---

## Spillover Priority

1. wall_cabinet (spill first)
2. island (if applicable)
3. **NEVER** drop appliances or tall cabinets — log LAYOUT-06, place at nearest corner/end

---

## Collision Whitelist (not flagged as errors)

| Pair | Reason |
|------|--------|
| `hood ↔ stove` | z-axis: hood is above stove |
| `tap ↔ sink` | tap is a sub-item of sink unit |
| `wall_cab ↔ base_cab` | z-axis: upper above lower |
| `dishwasher ↔ base_cab` | integrated panel, shared x boundary |

---

## Coordinate System

- All coordinates in **mm**
- Origin: **south-west corner** of the room
- +x → east, +y → north, +z → up
