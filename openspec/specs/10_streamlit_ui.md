# OpenSpec: Streamlit UI
## Files: `ui/app.py`, `ui/components/*.py`
## Branch: `feature/ui`
## Design Doc: §12

---

## Goal
4-persona Streamlit UI with dark navy theme, aesthetic design, live pipeline progress.
Very cool. Very polished. Runs with: `streamlit run ui/app.py`

---

## Theme Configuration

### `.streamlit/config.toml` (create this file)
```toml
[theme]
base = "dark"
primaryColor = "#00D4B1"
backgroundColor = "#0D1117"
secondaryBackgroundColor = "#161B22"
textColor = "#E6EDF3"
font = "sans serif"
```

---

## Color Constants (used throughout UI)

```python
# ui/app.py top of file
COLORS = {
    "bg":          "#0D1117",
    "bg_secondary":"#161B22",
    "accent":      "#00D4B1",
    "accent_dim":  "#00A896",
    "text":        "#E6EDF3",
    "text_muted":  "#8B949E",
    "score_green": "#38A169",
    "score_amber": "#D69E2E",
    "score_red":   "#E53E3E",
    "zone_cooking":"#E53E3E",
    "zone_clean":  "#00D4B1",
    "zone_cool":   "#3182CE",
    "zone_prep":   "#D69E2E",
    "zone_store":  "#718096",
}
```

### Custom CSS Injection
```python
st.markdown("""
<style>
/* Dark card style */
.variant-card {
    background: #161B22;
    border: 1px solid #30363D;
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
}

/* Score badge */
.score-badge-green { background: #1A3A2A; color: #38A169; padding: 4px 12px; border-radius: 20px; font-weight: 700; }
.score-badge-amber { background: #3A2F0A; color: #D69E2E; padding: 4px 12px; border-radius: 20px; font-weight: 700; }
.score-badge-red   { background: #3A0A0A; color: #E53E3E; padding: 4px 12px; border-radius: 20px; font-weight: 700; }

/* Pipeline step */
.pipeline-step { font-family: monospace; padding: 6px 0; }
.pipeline-done  { color: #38A169; }
.pipeline-running { color: #D69E2E; }

/* Room card */
.room-card {
    background: #161B22;
    border: 2px solid #30363D;
    border-radius: 10px;
    padding: 16px;
    cursor: pointer;
    transition: border-color 0.2s;
}
.room-card:hover { border-color: #00D4B1; }
.room-card-selected { border-color: #00D4B1 !important; }

/* Zone chip */
.zone-chip {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
    margin: 2px;
}
</style>
""", unsafe_allow_html=True)
```

---

## `ui/app.py`

### Main Structure
```python
import streamlit as st
import asyncio, json, time, subprocess
from pathlib import Path
from graph.kitchen_graph import build_graph
from ui.components.room_picker import render_room_picker
from ui.components.pipeline_log import PipelineLog
from ui.components.variant_card import render_variant_card
from ui.components.nkba_checklist import render_nkba_checklist

st.set_page_config(
    page_title="Auto-Design System",
    page_icon="[KITCHEN]",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Inject CSS + colors
inject_custom_css()

# Header
st.markdown("# Auto-Design System")
st.markdown("##### AI-Powered Kitchen Layout Generator | Powered by Claude")
st.divider()

# 4 Tabs
tab1, tab2, tab3, tab4 = st.tabs([
    "Homeowner",
    "Kitchen Designer",
    "Catalog Manager",
    "Design Reviewer",
])

with tab1: render_homeowner_tab()
with tab2: render_designer_tab()
with tab3: render_catalog_tab()
with tab4: render_reviewer_tab()
```

---

## Tab 1 — Homeowner

```python
def render_homeowner_tab():
    col_left, col_right = st.columns([1, 2])

    with col_left:
        st.markdown("### Configure Your Kitchen")

        # Room selector — 3 cards
        selected_room = render_room_picker()

        # Prompt
        prompt = st.text_area(
            "Describe your style",
            placeholder="I want navy blue base cabinets with a modern feel...",
            height=100,
        )

        # Budget
        budget = st.radio("Budget", ["Low", "Mid", "High"], index=1, horizontal=True)

        # Must-have
        must_have = st.multiselect(
            "Must have", ["Dishwasher", "Hood", "Island", "Oven", "Microwave"],
            default=["Dishwasher", "Hood"],
        )

        # Avoid
        avoid = st.multiselect(
            "Avoid", ["Double sink", "Island", "Tall cabinets"],
        )

        # Generate button — glowing teal
        generate = st.button(
            "Generate Layouts",
            type="primary",
            use_container_width=True,
        )

    with col_right:
        if generate and selected_room:
            _run_pipeline(selected_room, prompt, budget, must_have, avoid)
        elif "final_output" in st.session_state:
            _render_results(st.session_state["final_output"])
        else:
            # Empty state illustration
            st.markdown("""
            <div style='text-align:center; padding:80px 40px; color:#8B949E'>
                <div style='font-size:64px; margin-bottom:16px'>[ ]</div>
                <div style='font-size:18px'>Select a room and click Generate to create layouts</div>
            </div>
            """, unsafe_allow_html=True)
```

### Pipeline Runner
```python
def _run_pipeline(room, prompt, budget, must_have, avoid):
    with st.spinner(""):
        log = PipelineLog()
        log.show()

        # Build input
        with open(room["file"]) as f:
            input_json = json.load(f)
        input_json["preferences"] = {
            "budget_tier": budget.lower(),
            "must_have": [x.lower() for x in must_have],
            "avoid": [x.lower().replace(" ", "_") for x in avoid],
            "prompt": prompt,
            "catalogId": "catalog",
        }

        # Run graph
        graph = build_graph()
        log.step("Parsing room geometry")
        result = asyncio.run(graph.ainvoke({"input_json": input_json}))

        st.session_state["final_output"] = result["final_output"]
        log.done("Pipeline complete")
    st.rerun()
```

### Results Renderer
```python
def _render_results(final_output):
    st.markdown(f"### {len(final_output.layouts)} Layout Variants")
    st.caption(f"Generated in {final_output.duration_ms/1000:.1f}s")

    for variant in final_output.layouts:
        render_variant_card(variant)
```

---

## Tab 2 — Kitchen Designer

Side-by-side variant comparison:
- 2D floor plan + 3D render per variant
- Zone breakdown table with color-coded chips
- Work triangle measurement
- Item coordinates table (sortable)
- Score with progress bar

---

## Tab 3 — Catalog Manager

- MCP server live status indicator (green/red dot)
- Catalog file loaded + SKU count
- All 9 MCP tools listed (checkmarks)
- Live tool call log from last run (scrollable)
- SKUs used in last layout with color swatches (colored square + hex code)
- Catalog switcher dropdown (catalogId)

---

## Tab 4 — Design Reviewer

- Variant selector (tabs or dropdown)
- Full NKBA rule checklist per variant: `render_nkba_checklist(variant)`
- Score breakdown: bar chart showing which rules deducted points
- Full AI rationale text per decision
- Color compliance confirmation
- Comparison table across all variants (rule pass rates)

---

## `ui/components/room_picker.py`

```python
ROOMS = [
    {
        "id": "input1",
        "file": "input1.json",
        "name": "Small Kitchen",
        "dimensions": "3600 × 3200mm",
        "walls": "2 cabinet walls (N+E)",
        "openings": "None",
        "tag": "Core",
    },
    {
        "id": "input2",
        "file": "input2.json",
        "name": "Large Open Kitchen",
        "dimensions": "42,000 × 42,000mm",
        "walls": "2 cabinet walls (N+E)",
        "openings": "None",
        "tag": "Core",
    },
    {
        "id": "input3",
        "file": "input3.json",
        "name": "Kitchen with Openings",
        "dimensions": "4200 × 3000mm",
        "walls": "2 cabinet walls (N+E)",
        "openings": "Door (S) + 2 Windows (N, E)",
        "tag": "Bonus P1",
    },
]

def render_room_picker() -> dict | None:
    st.markdown("#### Select Room")
    selected = st.session_state.get("selected_room", ROOMS[0])

    cols = st.columns(len(ROOMS))
    for i, (col, room) in enumerate(zip(cols, ROOMS)):
        with col:
            is_selected = selected["id"] == room["id"]
            border_color = "#00D4B1" if is_selected else "#30363D"
            if st.button(f"**{room['name']}**\n\n{room['dimensions']}\n{room['openings']}",
                         key=f"room_{room['id']}", use_container_width=True):
                st.session_state["selected_room"] = room
                selected = room
    return selected
```

---

## `ui/components/pipeline_log.py`

```python
class PipelineLog:
    STEPS = [
        ("Parsing room geometry",      0.3),
        ("Parsing prompt intent",       0.8),
        ("Querying catalog via MCP",    1.2),
        ("Planning layout variants",    4.1),
        ("Computing coordinates",       0.9),
        ("Validating NKBA rules",       0.4),
        ("Writing rationale",           1.8),
        ("Rendering 2D + 3D views",     2.1),
    ]

    def __init__(self):
        self._placeholder = st.empty()
        self._completed = []
        self._current = None

    def step(self, name: str):
        self._current = name
        self._render()

    def done(self, name: str):
        self._completed.append(name)
        self._current = None
        self._render()

    def _render(self):
        lines = []
        for step_name, _ in self.STEPS:
            if step_name in self._completed:
                lines.append(f'<div class="pipeline-step pipeline-done">✓ {step_name}</div>')
            elif step_name == self._current:
                lines.append(f'<div class="pipeline-step pipeline-running">⟳ {step_name}...</div>')
            else:
                lines.append(f'<div class="pipeline-step" style="color:#8B949E">○ {step_name}</div>')
        self._placeholder.markdown("\n".join(lines), unsafe_allow_html=True)
```

---

## `ui/components/variant_card.py`

```python
def render_variant_card(variant):
    score = variant.score
    if score > 0.8:
        badge_class = "score-badge-green"
        score_emoji = "✓"
    elif score >= 0.6:
        badge_class = "score-badge-amber"
        score_emoji = "~"
    else:
        badge_class = "score-badge-red"
        score_emoji = "!"

    with st.container():
        col_info, col_views = st.columns([1, 2])

        with col_info:
            st.markdown(f"### {variant.variant_id}")
            st.markdown(f'<span class="{badge_class}">{score_emoji} Score: {score:.2f}</span>',
                       unsafe_allow_html=True)
            st.caption(f"Family: {variant.family}")
            st.caption(f"Items placed: {variant.placement_count}")
            st.caption(f"NKBA: {variant.nkba_compliance_pct*100:.0f}% compliant")

            if variant.violations:
                with st.expander(f"⚠ {len(variant.violations)} violation(s)"):
                    for v in variant.violations:
                        st.warning(f"**{v['rule_id']}**: {v['message']}")

        with col_views:
            view = st.radio("", ["2D Top View", "3D View"], key=f"view_{variant.variant_id}",
                           horizontal=True)
            variant_id = variant.variant_id
            img_path = f"renders/{variant_id}_{'top' if view == '2D Top View' else '3d'}.png"

            if Path(img_path).exists():
                st.image(img_path, use_container_width=True)
            else:
                st.info("Rendering not available")

            if st.button("Open Interactive 3D", key=f"3d_{variant.variant_id}"):
                subprocess.Popen(["python", "render.py", "output.json",
                                  "--show", "--3d-only",
                                  "--catalog", "catalog.json"])
```

---

## `ui/components/nkba_checklist.py`

```python
RULE_GROUPS = {
    "Project Rules": ["NKBA-CL-01","NKBA-CL-02","WORKFLOW-01","WORKFLOW-02",
                      "WORKFLOW-03","LAYOUT-01","LAYOUT-02","LAYOUT-03",
                      "LAYOUT-04","LAYOUT-05","LAYOUT-06"],
    "Official NKBA": ["NKBA-01","NKBA-02","NKBA-03","NKBA-04","NKBA-05",
                      "NKBA-06","NKBA-06b","NKBA-07","NKBA-08","NKBA-10",
                      "NKBA-11","NKBA-12","NKBA-13","NKBA-LA-01","NKBA-LA-02",
                      "NKBA-LA-03","NKBA-LA-05","NKBA-18","NKBA-19","NKBA-25"],
}

def render_nkba_checklist(variant):
    violated = {v["rule_id"]: v["message"] for v in variant.violations}

    for group_name, rule_ids in RULE_GROUPS.items():
        st.markdown(f"**{group_name}**")
        for rule_id in rule_ids:
            if rule_id in violated:
                st.error(f"✗ {rule_id}: {violated[rule_id]}")
            else:
                st.success(f"✓ {rule_id}")
```

---

## Validation
```bash
streamlit run ui/app.py
# Open browser at localhost:8501
# Verify: dark theme loads
# Verify: 4 tabs visible
# Verify: room picker shows 3 cards
# Verify: generate button visible
# Verify: no console errors on startup
```
