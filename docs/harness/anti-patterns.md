# Anti-Patterns — Living Catalog

Known failure modes seen in this codebase or in agent sessions on this repo.

**Rule**: Add an entry the second time a mistake recurs. A new skill rule or sharpened constraint is born the third time.

---

## Format

Each entry:
- **Pattern**: what went wrong
- **First observed**: when / in which eval case
- **Example snippet**: concrete code showing the mistake
- **Root cause**: why the agent made this choice
- **Fix**: which skill/rule prevents it
- **Status**: `prevented` | `recurring` | `rare`

---

## AP-001 — Hardcoded Model Strings

**Pattern**: Agent writes `model="claude-sonnet-4-6"` directly in an agent file instead of using `utils/model_selector.py`

**First observed**: Early implementation of `agents/layout_strategist.py` (pre-`model_selector.py`)

**Example snippet**:
```python
# WRONG — in agents/layout_strategist.py
result = await client.messages.create(
    model="claude-sonnet-4-6",  # hardcoded
    ...
)
```

**Root cause**: Agent knows the correct model name from context and uses it directly without checking for a utility function.

**Fix**: `skills/llm-routing-and-observability.md` Rule 1 — "Never hardcode model strings; always use `utils/model_selector.py`"

**Status**: prevented (rule exists in AGENTS.md Non-Negotiable Rules)

---

## AP-002 — Reading catalog.json Directly

**Pattern**: Agent code opens and reads `catalog.json` with `json.load()` instead of calling `mcp_server/server.py` tools

**First observed**: Early agent implementations before MCP server was established

**Example snippet**:
```python
# WRONG — in agents/catalog_selector.py
with open("catalog.json") as f:
    catalog = json.load(f)
items = [v for v in catalog.values() if v["category"] == "base_cabinet"]
```

**Root cause**: Direct file read is simpler and more familiar; agent doesn't know about or doesn't check for the MCP abstraction.

**Fix**: `skills/catalog.md` Rule 1 — "Never read `catalog.json` directly from agent or pipeline code — always use MCP tools"

**Status**: prevented (rule exists in skills/catalog.md and AGENTS.md)

---

## AP-003 — Agent 3 Outputting mm Coordinates

**Pattern**: Layout Strategist outputs mm coordinates (e.g., `"x": 1200, "y": 600`) instead of semantic vocabulary terms

**First observed**: Initial implementation of `agents/layout_strategist.py` before semantic vocabulary was enforced

**Example snippet**:
```python
# WRONG — Agent 3 output
{
  "sink": {"x": 1200, "y": 0, "z": 0},  # mm coordinates — should be semantic term
  "stove": {"x": 600, "y": 0, "z": 0}
}

# CORRECT — Agent 3 output
{
  "sink": {"position": "centre of north wall"},
  "stove": {"position": "left end of east wall"}
}
```

**Root cause**: Agent 3's system prompt uses spatial reasoning, making it naturally produce coordinates. Without explicit enforcement of the semantic vocabulary, it defaults to numbers.

**Fix**: `skills/variant-generation.md` and `AGENT_SPECS.md` — "Agent 3 MUST NEVER output coordinates, mm values, or any numbers"

**Status**: prevented (hard constraint in AGENTS.md and skill, but watch for recurrence after model updates)

---

*Add entries here when a mistake recurs for the second time.*
*After the third recurrence: update the relevant skill's `## Must Not Do` section AND add a gate to `checklists/pre-commit-checklist.md`.*
