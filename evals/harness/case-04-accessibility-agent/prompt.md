# Eval Case 04 — Accessibility Advisor Agent

Read AGENTS.md at the repo root before doing anything else.

---

## Feature Request

Build a new accessibility advisor agent that post-processes generated layouts for accessibility concerns.

After the NKBA validator runs on each variant, the accessibility advisor should:
1. Check counter heights (standard 900mm vs accessible 810–860mm)
2. Check knee clearance under at least one counter section (min 690mm height, 760mm width)
3. Verify aisle widths meet wheelchair-accessible standards (min 1525mm for turning radius)
4. Flag tall cabinet placement that blocks reach zones (max reachable height 1370mm for seated users)
5. For each issue found, suggest a specific trade-off (e.g., "lower counter height reduces storage by ~15%")

The advisor outputs a structured `AccessibilityReportDTO` that is displayed in a new UI tab or panel.

## Instructions

- Read AGENTS.md first
- Follow the full 12-step new-feature workflow from AGENTS.md
- Fill all three templates in `templates/` before writing any code
- Identify and read all relevant skill files
- Do NOT ask clarifying questions unless completely blocked
- The new agent must use `utils/model_selector.py` — no hardcoded model strings
- The new agent must be wired into `graph/kitchen_graph.py` as a proper node
- Define `AccessibilityReportDTO` in `dtos/contracts.py` BEFORE writing the agent

## Constraints

- New agent class in `agents/accessibility_advisor.py`
- New graph node wired after `nkba_validator` node in `graph/kitchen_graph.py`
- `AccessibilityReportDTO` defined in `dtos/contracts.py` first
- New UI panel in `ui/components/accessibility_report.py` (display only)
- No hardcoded model strings
- All API calls in try/except returning fallback DTO
- Prompt caching on static system prompt
