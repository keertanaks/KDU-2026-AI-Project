# OpenSpec: Streamlit UI — Full Aesthetic Spec
## Files: `ui/app.py`, `ui/components/*.py`
## Branch: `feature/ui`
## Design Doc: §12

---

## Visual Identity

```
Background:      #0D1117   (GitHub-dark navy)
Surface:         #161B22   (card background)
Surface raised:  #1C2128   (elevated elements)
Border:          #30363D   (subtle borders)
Accent teal:     #00D4B1   (primary action, glow)
Accent teal dim: #00A896
Text primary:    #E6EDF3
Text secondary:  #8B949E
Text muted:      #484F58

Score green:     #39D353   (>0.8)
Score amber:     #F0A500   (0.6–0.8)
Score red:       #F85149   (<0.6)

Zone cooking:    #FF6B6B
Zone cleaning:   #00D4B1
Zone cooling:    #4DA6FF
Zone prep:       #FFD166
Zone storage:    #6E7681
```

---

## `.streamlit/config.toml`

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

## Global CSS — inject once at app start

```python
GLOBAL_CSS = """
<style>
/* ── Google Font ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif !important;
}

/* ── Hide Streamlit chrome ── */
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 1.5rem !important; max-width: 1400px !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #161B22; }
::-webkit-scrollbar-thumb { background: #30363D; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #00D4B1; }

/* ══════════════════════════════════════════
   HEADER HERO
══════════════════════════════════════════ */
.hero {
    background: linear-gradient(135deg, #0D1117 0%, #0d1f1c 50%, #0D1117 100%);
    border: 1px solid #1a3a35;
    border-radius: 16px;
    padding: 32px 40px;
    margin-bottom: 24px;
    position: relative;
    overflow: hidden;
}
.hero::before {
    content: '';
    position: absolute;
    top: -60px; right: -60px;
    width: 240px; height: 240px;
    background: radial-gradient(circle, rgba(0,212,177,0.12) 0%, transparent 70%);
    pointer-events: none;
}
.hero-title {
    font-size: 28px;
    font-weight: 700;
    letter-spacing: -0.5px;
    background: linear-gradient(90deg, #E6EDF3 0%, #00D4B1 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin: 0 0 6px 0;
}
.hero-subtitle {
    font-size: 14px;
    color: #8B949E;
    margin: 0;
    font-weight: 400;
}
.hero-badge {
    display: inline-block;
    background: rgba(0,212,177,0.1);
    border: 1px solid rgba(0,212,177,0.3);
    color: #00D4B1;
    font-size: 11px;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 20px;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    margin-bottom: 12px;
}

/* ══════════════════════════════════════════
   CARDS
══════════════════════════════════════════ */
.card {
    background: #161B22;
    border: 1px solid #30363D;
    border-radius: 12px;
    padding: 20px;
    transition: border-color 0.2s, box-shadow 0.2s;
}
.card:hover {
    border-color: #484F58;
    box-shadow: 0 4px 24px rgba(0,0,0,0.4);
}
.card-glow {
    background: #161B22;
    border: 1px solid #30363D;
    border-radius: 12px;
    padding: 20px;
    box-shadow: 0 0 0 1px transparent;
    transition: all 0.25s ease;
}
.card-glow:hover {
    border-color: rgba(0,212,177,0.4);
    box-shadow: 0 0 20px rgba(0,212,177,0.08), 0 4px 24px rgba(0,0,0,0.4);
}

/* ══════════════════════════════════════════
   ROOM PICKER CARDS
══════════════════════════════════════════ */
.room-card {
    background: #161B22;
    border: 2px solid #30363D;
    border-radius: 12px;
    padding: 18px 16px;
    cursor: pointer;
    transition: all 0.2s ease;
    text-align: center;
    height: 100%;
}
.room-card:hover {
    border-color: rgba(0,212,177,0.5);
    background: #1a2228;
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0,0,0,0.3);
}
.room-card.selected {
    border-color: #00D4B1;
    background: rgba(0,212,177,0.05);
    box-shadow: 0 0 0 1px #00D4B1, 0 0 20px rgba(0,212,177,0.1);
}
.room-card-icon {
    font-size: 28px;
    margin-bottom: 8px;
}
.room-card-name {
    font-size: 14px;
    font-weight: 600;
    color: #E6EDF3;
    margin-bottom: 4px;
}
.room-card-dims {
    font-size: 12px;
    color: #8B949E;
    font-family: 'JetBrains Mono', monospace;
    margin-bottom: 6px;
}
.room-card-tag {
    display: inline-block;
    font-size: 10px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 10px;
    text-transform: uppercase;
    letter-spacing: 0.4px;
}
.tag-core { background: rgba(77,166,255,0.15); color: #4DA6FF; }
.tag-bonus { background: rgba(255,214,102,0.15); color: #FFD166; }

/* ══════════════════════════════════════════
   GENERATE BUTTON
══════════════════════════════════════════ */
div[data-testid="stButton"] > button[kind="primary"] {
    background: linear-gradient(135deg, #00D4B1 0%, #00A896 100%) !important;
    border: none !important;
    border-radius: 10px !important;
    color: #0D1117 !important;
    font-weight: 700 !important;
    font-size: 15px !important;
    letter-spacing: 0.3px !important;
    padding: 14px 28px !important;
    transition: all 0.2s ease !important;
    box-shadow: 0 4px 16px rgba(0,212,177,0.25) !important;
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 8px 24px rgba(0,212,177,0.4) !important;
    background: linear-gradient(135deg, #00e6c0 0%, #00D4B1 100%) !important;
}
div[data-testid="stButton"] > button[kind="primary"]:active {
    transform: translateY(0px) !important;
}

/* ══════════════════════════════════════════
   PIPELINE LOG
══════════════════════════════════════════ */
.pipeline-container {
    background: #0D1117;
    border: 1px solid #21262D;
    border-radius: 10px;
    padding: 16px 20px;
    font-family: 'JetBrains Mono', monospace;
}
.pipeline-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 5px 0;
    font-size: 13px;
}
.pipeline-icon-done  { color: #39D353; font-size: 14px; }
.pipeline-icon-run   { color: #F0A500; font-size: 14px; animation: pulse 1s infinite; }
.pipeline-icon-wait  { color: #484F58; font-size: 14px; }
.pipeline-label-done { color: #8B949E; text-decoration: none; }
.pipeline-label-run  { color: #E6EDF3; font-weight: 500; }
.pipeline-label-wait { color: #484F58; }
.pipeline-time       { margin-left: auto; color: #39D353; font-size: 11px; }
.pipeline-time-run   { margin-left: auto; color: #F0A500; font-size: 11px; }
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0.4; }
}

/* ══════════════════════════════════════════
   VARIANT CARD
══════════════════════════════════════════ */
.variant-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 14px;
}
.variant-id {
    font-size: 13px;
    font-weight: 600;
    color: #8B949E;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    font-family: 'JetBrains Mono', monospace;
}
.variant-family {
    font-size: 20px;
    font-weight: 700;
    color: #E6EDF3;
    margin: 0 0 12px 0;
}

/* Score ring */
.score-ring-wrap {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 14px;
}
.score-ring {
    width: 56px; height: 56px;
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 15px; font-weight: 700;
    border: 3px solid;
    flex-shrink: 0;
}
.score-ring-green { border-color: #39D353; color: #39D353; background: rgba(57,211,83,0.08); }
.score-ring-amber { border-color: #F0A500; color: #F0A500; background: rgba(240,165,0,0.08); }
.score-ring-red   { border-color: #F85149; color: #F85149; background: rgba(248,81,73,0.08); }
.score-meta { display: flex; flex-direction: column; gap: 3px; }
.score-label { font-size: 12px; color: #8B949E; }
.score-stats { font-size: 12px; color: #E6EDF3; }

/* Stat pills */
.stat-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
.stat-pill {
    background: #1C2128;
    border: 1px solid #30363D;
    border-radius: 20px;
    padding: 3px 10px;
    font-size: 11px;
    color: #8B949E;
    display: flex; align-items: center; gap: 5px;
}
.stat-pill-val { color: #E6EDF3; font-weight: 600; }

/* Zone bar */
.zone-bar { display: flex; gap: 4px; margin-bottom: 12px; flex-wrap: wrap; }
.zone-chip {
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.3px;
}
.zone-cooking  { background: rgba(255,107,107,0.15); color: #FF6B6B; }
.zone-cleaning { background: rgba(0,212,177,0.15);   color: #00D4B1; }
.zone-cooling  { background: rgba(77,166,255,0.15);  color: #4DA6FF; }
.zone-prep     { background: rgba(255,209,102,0.15); color: #FFD166; }
.zone-storage  { background: rgba(110,118,129,0.2);  color: #8B949E; }

/* Violations */
.violation-row {
    display: flex; align-items: flex-start; gap: 8px;
    padding: 8px 10px;
    background: rgba(248,81,73,0.06);
    border: 1px solid rgba(248,81,73,0.2);
    border-radius: 8px;
    margin-bottom: 6px;
    font-size: 12px;
}
.violation-id   { color: #F85149; font-weight: 700; font-family: 'JetBrains Mono', monospace; flex-shrink: 0; }
.violation-text { color: #8B949E; }

/* Image frame */
.render-frame {
    background: #0D1117;
    border: 1px solid #21262D;
    border-radius: 10px;
    overflow: hidden;
    display: flex; align-items: center; justify-content: center;
    min-height: 200px;
}
.render-placeholder {
    color: #484F58;
    font-size: 13px;
    text-align: center;
    padding: 40px;
}

/* ══════════════════════════════════════════
   NKBA CHECKLIST
══════════════════════════════════════════ */
.rule-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 12px;
    border-radius: 8px;
    margin-bottom: 3px;
    font-size: 13px;
    transition: background 0.15s;
}
.rule-row:hover { background: #1C2128; }
.rule-pass  { border-left: 3px solid #39D353; }
.rule-warn  { border-left: 3px solid #F0A500; }
.rule-fail  { border-left: 3px solid #F85149; }
.rule-icon  { font-size: 14px; flex-shrink: 0; }
.rule-id    { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #8B949E; min-width: 100px; }
.rule-desc  { color: #E6EDF3; flex: 1; }
.rule-msg   { font-size: 11px; color: #F85149; }

/* ══════════════════════════════════════════
   CATALOG MANAGER
══════════════════════════════════════════ */
.status-dot {
    display: inline-block;
    width: 8px; height: 8px;
    border-radius: 50%;
    margin-right: 8px;
}
.dot-green { background: #39D353; box-shadow: 0 0 6px #39D353; }
.dot-red   { background: #F85149; box-shadow: 0 0 6px #F85149; }

.tool-row {
    display: flex; align-items: center; gap: 12px;
    padding: 8px 12px;
    border-radius: 8px;
    background: #1C2128;
    margin-bottom: 6px;
    font-size: 13px;
}
.tool-name { font-family: 'JetBrains Mono', monospace; color: #00D4B1; flex: 1; }
.tool-desc { color: #8B949E; font-size: 12px; flex: 2; }
.tool-ok   { color: #39D353; font-size: 12px; }

.log-box {
    background: #0D1117;
    border: 1px solid #21262D;
    border-radius: 8px;
    padding: 12px 16px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    max-height: 200px;
    overflow-y: auto;
    line-height: 1.8;
}
.log-call { color: #4DA6FF; }
.log-time { color: #484F58; }
.log-res  { color: #39D353; }

.sku-swatch-row {
    display: flex; align-items: center; gap: 10px;
    padding: 7px 10px;
    border-radius: 8px;
    background: #1C2128;
    margin-bottom: 5px;
    font-size: 13px;
}
.color-dot {
    width: 20px; height: 20px;
    border-radius: 4px;
    border: 1px solid rgba(255,255,255,0.1);
    flex-shrink: 0;
}
.sku-id   { font-family: 'JetBrains Mono', monospace; color: #8B949E; font-size: 11px; min-width: 70px; }
.sku-name { color: #E6EDF3; flex: 1; }
.hex-code { font-family: 'JetBrains Mono', monospace; color: #8B949E; font-size: 11px; }

/* ══════════════════════════════════════════
   TAB OVERRIDES
══════════════════════════════════════════ */
button[data-baseweb="tab"] {
    font-size: 13px !important;
    font-weight: 500 !important;
    padding: 10px 20px !important;
    color: #8B949E !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    color: #00D4B1 !important;
    border-bottom: 2px solid #00D4B1 !important;
}

/* ══════════════════════════════════════════
   SECTION LABELS
══════════════════════════════════════════ */
.section-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #484F58;
    margin-bottom: 10px;
    padding-bottom: 6px;
    border-bottom: 1px solid #21262D;
}
.section-title {
    font-size: 16px;
    font-weight: 600;
    color: #E6EDF3;
    margin-bottom: 16px;
}

/* ══════════════════════════════════════════
   DIVIDER
══════════════════════════════════════════ */
.divider { border: none; border-top: 1px solid #21262D; margin: 20px 0; }

/* ══════════════════════════════════════════
   SCORE COMPARISON TABLE
══════════════════════════════════════════ */
.compare-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.compare-table th {
    text-align: left; padding: 8px 12px;
    border-bottom: 1px solid #30363D;
    color: #8B949E; font-weight: 600;
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;
}
.compare-table td {
    padding: 8px 12px;
    border-bottom: 1px solid #21262D;
    color: #E6EDF3;
}
.compare-table tr:hover td { background: #1C2128; }
</style>
"""
```

---

## `ui/app.py` — Full Structure

```python
from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path

import streamlit as st

from ui.components.room_picker import render_room_picker
from ui.components.pipeline_log import PipelineLog
from ui.components.variant_card import render_variant_card
from ui.components.nkba_checklist import render_nkba_checklist

st.set_page_config(
    page_title="Auto-Design System",
    page_icon="■",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)   # inject once


def _hero() -> None:
    st.markdown("""
    <div class="hero">
      <div class="hero-badge">KDU · 2026 · AI Project</div>
      <div class="hero-title">Auto-Design System</div>
      <div class="hero-subtitle">
        AI-powered kitchen layout generator &nbsp;·&nbsp;
        3–5 variants per request &nbsp;·&nbsp;
        31 NKBA rules &nbsp;·&nbsp;
        Powered by Claude
      </div>
    </div>
    """, unsafe_allow_html=True)


def main() -> None:
    _hero()

    tab1, tab2, tab3, tab4 = st.tabs([
        "  Homeowner  ",
        "  Kitchen Designer  ",
        "  Catalog Manager  ",
        "  Design Reviewer  ",
    ])

    with tab1:  _tab_homeowner()
    with tab2:  _tab_designer()
    with tab3:  _tab_catalog()
    with tab4:  _tab_reviewer()


if __name__ == "__main__":
    main()
```

---

## Tab 1 — Homeowner

```python
def _tab_homeowner() -> None:
    col_input, col_results = st.columns([1, 2], gap="large")

    with col_input:
        st.markdown('<div class="section-label">Configure Your Kitchen</div>', unsafe_allow_html=True)

        # ── Room picker ──
        selected_room = render_room_picker()
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

        # ── Prompt ──
        st.markdown('<div class="section-label">Style Prompt</div>', unsafe_allow_html=True)
        prompt = st.text_area(
            label="",
            placeholder='e.g. "I want navy blue base cabinets with a modern minimalist feel"',
            height=90,
            label_visibility="collapsed",
        )

        # ── Budget ──
        st.markdown('<div class="section-label" style="margin-top:16px">Budget</div>', unsafe_allow_html=True)
        budget = st.radio("", ["Low", "Mid", "High"], index=1, horizontal=True, label_visibility="collapsed")

        # ── Must-have / Avoid ──
        c1, c2 = st.columns(2)
        with c1:
            st.markdown('<div class="section-label">Must Have</div>', unsafe_allow_html=True)
            must_have = st.multiselect(
                "", ["Dishwasher", "Hood", "Island", "Oven", "Microwave"],
                default=["Dishwasher", "Hood"], label_visibility="collapsed",
            )
        with c2:
            st.markdown('<div class="section-label">Avoid</div>', unsafe_allow_html=True)
            avoid = st.multiselect(
                "", ["Double sink", "Island", "Tall cabinets"],
                label_visibility="collapsed",
            )

        st.markdown("")
        generate = st.button("Generate Layouts", type="primary", use_container_width=True)

    with col_results:
        if generate and selected_room:
            _run_pipeline_tab1(selected_room, prompt, budget, must_have, avoid)
        elif "final_output" in st.session_state:
            _render_results_tab1(st.session_state["final_output"])
        else:
            # empty state
            st.markdown("""
            <div style="display:flex;flex-direction:column;align-items:center;
                        justify-content:center;height:400px;gap:16px;">
              <div style="font-size:56px;opacity:0.15">⬡</div>
              <div style="font-size:14px;color:#484F58;text-align:center;max-width:280px">
                Select a room, describe your style,<br>and click Generate Layouts
              </div>
            </div>
            """, unsafe_allow_html=True)


def _run_pipeline_tab1(room, prompt, budget, must_have, avoid) -> None:
    log = PipelineLog()
    log_placeholder = st.empty()

    with log_placeholder:
        log.show()

    # Build input JSON
    with open(room["file"]) as f:
        input_json = json.load(f)
    input_json["preferences"] = {
        "budget_tier": budget.lower(),
        "must_have":   [x.lower() for x in must_have],
        "avoid":       [x.lower().replace(" ", "_") for x in avoid],
        "prompt":      prompt or "",
        "catalogId":   "catalog",
    }

    # Run the LangGraph pipeline
    from graph.kitchen_graph import build_graph
    graph = build_graph()

    log.step("Parsing room geometry");        log_placeholder.empty(); log.show()
    # ... (each node updates the log via callback)
    result = asyncio.run(graph.ainvoke({"input_json": input_json}))

    st.session_state["final_output"] = result["final_output"]
    st.session_state["last_input"]   = input_json
    st.rerun()


def _render_results_tab1(final_output) -> None:
    n     = len(final_output.layouts)
    dur   = final_output.duration_ms
    best  = final_output.layouts[0].score if n else 0.0

    # Summary strip
    st.markdown(f"""
    <div style="display:flex;gap:24px;margin-bottom:20px;flex-wrap:wrap">
      <div class="card" style="flex:1;min-width:140px;padding:14px 18px">
        <div style="font-size:11px;color:#8B949E;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Variants</div>
        <div style="font-size:24px;font-weight:700;color:#E6EDF3">{n}</div>
      </div>
      <div class="card" style="flex:1;min-width:140px;padding:14px 18px">
        <div style="font-size:11px;color:#8B949E;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Generated In</div>
        <div style="font-size:24px;font-weight:700;color:#E6EDF3">{dur/1000:.1f}<span style="font-size:14px;color:#8B949E">s</span></div>
      </div>
      <div class="card" style="flex:1;min-width:140px;padding:14px 18px">
        <div style="font-size:11px;color:#8B949E;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Best Score</div>
        <div style="font-size:24px;font-weight:700;color:{'#39D353' if best>0.8 else '#F0A500' if best>=0.6 else '#F85149'}">{best:.2f}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    for variant in final_output.layouts:
        render_variant_card(variant)
        st.markdown("")
```

---

## `ui/components/room_picker.py`

```python
from __future__ import annotations
import streamlit as st

ROOMS = [
    {
        "id":       "input1",
        "file":     "input1.json",
        "icon":     "[S]",
        "name":     "Small Kitchen",
        "dims":     "3600 × 3200mm",
        "openings": "No openings",
        "walls":    "N + E walls",
        "tag":      "core",
    },
    {
        "id":       "input2",
        "file":     "input2.json",
        "icon":     "[L]",
        "name":     "Large Kitchen",
        "dims":     "42,000 × 42,000mm",
        "openings": "No openings",
        "walls":    "N + E walls",
        "tag":      "core",
    },
    {
        "id":       "input3",
        "file":     "input3.json",
        "icon":     "[O]",
        "name":     "Kitchen + Openings",
        "dims":     "4200 × 3000mm",
        "openings": "Door + 2 Windows",
        "walls":    "N + E walls",
        "tag":      "bonus",
    },
]

def render_room_picker() -> dict:
    st.markdown('<div class="section-label">Room</div>', unsafe_allow_html=True)

    if "selected_room" not in st.session_state:
        st.session_state["selected_room"] = ROOMS[0]

    cols = st.columns(3, gap="small")
    for col, room in zip(cols, ROOMS):
        with col:
            is_sel   = st.session_state["selected_room"]["id"] == room["id"]
            sel_cls  = "selected" if is_sel else ""
            tag_cls  = "tag-core" if room["tag"] == "core" else "tag-bonus"
            tag_text = "Core" if room["tag"] == "core" else "Bonus P1"

            st.markdown(f"""
            <div class="room-card {sel_cls}">
              <div class="room-card-icon">{room['icon']}</div>
              <div class="room-card-name">{room['name']}</div>
              <div class="room-card-dims">{room['dims']}</div>
              <div class="room-card-dims" style="margin-bottom:8px">{room['openings']}</div>
              <span class="room-card-tag {tag_cls}">{tag_text}</span>
            </div>
            """, unsafe_allow_html=True)

            if st.button("Select", key=f"room_{room['id']}", use_container_width=True):
                st.session_state["selected_room"] = room
                st.rerun()

    return st.session_state["selected_room"]
```

---

## `ui/components/pipeline_log.py`

```python
from __future__ import annotations
import time
import streamlit as st

STEPS = [
    "Parsing room geometry",
    "Parsing prompt intent",
    "Querying catalog via MCP",
    "Planning layout variants",
    "Computing coordinates",
    "Validating NKBA rules",
    "Writing rationale",
    "Rendering 2D + 3D views",
]

class PipelineLog:
    def __init__(self) -> None:
        self._done:    list[tuple[str, float]] = []   # (name, elapsed_s)
        self._current: str | None = None
        self._start:   float | None = None
        self._ph = st.empty()

    def step(self, name: str) -> None:
        self._current = name
        self._start   = time.perf_counter()
        self._render()

    def complete(self, name: str) -> None:
        elapsed = time.perf_counter() - (self._start or time.perf_counter())
        self._done.append((name, elapsed))
        self._current = None
        self._render()

    def _render(self) -> None:
        done_names = {n for n, _ in self._done}
        rows = []
        for step in STEPS:
            if step in done_names:
                t = next(t for n, t in self._done if n == step)
                rows.append(
                    f'<div class="pipeline-row">'
                    f'<span class="pipeline-icon-done">✓</span>'
                    f'<span class="pipeline-label-done">{step}</span>'
                    f'<span class="pipeline-time">{t:.1f}s</span>'
                    f'</div>'
                )
            elif step == self._current:
                rows.append(
                    f'<div class="pipeline-row">'
                    f'<span class="pipeline-icon-run">⟳</span>'
                    f'<span class="pipeline-label-run">{step}</span>'
                    f'<span class="pipeline-time-run">running...</span>'
                    f'</div>'
                )
            else:
                rows.append(
                    f'<div class="pipeline-row">'
                    f'<span class="pipeline-icon-wait">○</span>'
                    f'<span class="pipeline-label-wait">{step}</span>'
                    f'</div>'
                )

        html = (
            '<div class="pipeline-container">'
            '<div style="font-size:11px;font-weight:600;text-transform:uppercase;'
            'letter-spacing:1px;color:#484F58;margin-bottom:10px">Pipeline</div>'
            + "".join(rows) +
            '</div>'
        )
        self._ph.markdown(html, unsafe_allow_html=True)
```

---

## `ui/components/variant_card.py`

```python
from __future__ import annotations
import subprocess
from pathlib import Path
import streamlit as st

def _score_class(score: float) -> str:
    if score > 0.8:  return "green"
    if score >= 0.6: return "amber"
    return "red"

def render_variant_card(variant) -> None:
    sc     = variant.score
    cls    = _score_class(sc)
    pct    = variant.nkba_compliance_pct * 100

    with st.container():
        # Outer glow card
        st.markdown('<div class="card-glow">', unsafe_allow_html=True)

        # Header row
        st.markdown(f"""
        <div class="variant-header">
          <span class="variant-id">{variant.variant_id}</span>
          <span style="font-size:12px;color:#484F58">{variant.placement_count} items placed</span>
        </div>
        <div class="variant-family">{variant.family} Layout</div>
        """, unsafe_allow_html=True)

        col_score, col_renders = st.columns([1, 2], gap="medium")

        with col_score:
            # Score ring
            st.markdown(f"""
            <div class="score-ring-wrap">
              <div class="score-ring score-ring-{cls}">{sc:.2f}</div>
              <div class="score-meta">
                <div class="score-label">Design Score</div>
                <div class="score-stats">{pct:.0f}% NKBA compliant</div>
                <div class="score-stats">{variant.spillover_count} spillovers</div>
              </div>
            </div>
            """, unsafe_allow_html=True)

            # Zone chips
            zones = {item.get("zone_type") for item in variant.layout.values()
                     if isinstance(item, dict) and not item.get("is_wall")}
            zone_html = "".join(
                f'<span class="zone-chip zone-{z}">{z.title()}</span>'
                for z in sorted(zones) if z
            )
            if zone_html:
                st.markdown(f'<div class="zone-bar">{zone_html}</div>', unsafe_allow_html=True)

            # Violations
            if variant.violations:
                with st.expander(f"⚠  {len(variant.violations)} violation(s)", expanded=False):
                    for v in variant.violations:
                        st.markdown(f"""
                        <div class="violation-row">
                          <span class="violation-id">{v['rule_id']}</span>
                          <span class="violation-text">{v.get('message','')}</span>
                        </div>
                        """, unsafe_allow_html=True)

        with col_renders:
            view = st.radio(
                "", ["2D Top View", "3D View"],
                key=f"view_{variant.variant_id}",
                horizontal=True,
                label_visibility="collapsed",
            )
            suffix   = "top" if view == "2D Top View" else "3d"
            img_path = Path(f"renders/{variant.variant_id}_{suffix}.png")

            st.markdown('<div class="render-frame">', unsafe_allow_html=True)
            if img_path.exists():
                st.image(str(img_path), use_container_width=True)
            else:
                st.markdown(
                    '<div class="render-placeholder">Render not yet available</div>',
                    unsafe_allow_html=True,
                )
            st.markdown('</div>', unsafe_allow_html=True)

            if st.button(
                "Open Interactive 3D",
                key=f"3d_{variant.variant_id}",
                use_container_width=True,
            ):
                subprocess.Popen([
                    "python", "render.py", "output.json",
                    "--show", "--3d-only",
                ])

        st.markdown('</div>', unsafe_allow_html=True)   # close card-glow
```

---

## `ui/components/nkba_checklist.py`

```python
from __future__ import annotations
import streamlit as st

RULE_GROUPS = {
    "Project Rules": [
        ("NKBA-CL-01", "Fridge door swing ≥ 1067mm"),
        ("NKBA-CL-02", "Door swing 900×900mm clear"),
        ("WORKFLOW-01", "Dishwasher within 600mm of sink"),
        ("WORKFLOW-02", "Stove–fridge gap ≥ 600mm"),
        ("WORKFLOW-03", "Work triangle 3962–6600mm"),
        ("LAYOUT-01",   "Sink ± 300mm of window center"),
        ("LAYOUT-02",   "Hood ± 100mm above stove XY"),
        ("LAYOUT-03",   "Continuous run ≤ 50mm gap"),
        ("LAYOUT-04",   "Every appliance backed by base cabinet"),
        ("LAYOUT-05",   "Run terminates at base/corner"),
        ("LAYOUT-06",   "Fridge and tall at corners/ends"),
    ],
    "Official NKBA": [
        ("NKBA-01",    "Entry opening ≥ 813mm"),
        ("NKBA-02",    "No appliance door collision"),
        ("NKBA-03",    "Triangle total ≤ 7925mm"),
        ("NKBA-04",    "Tall cabinets don't separate work centers"),
        ("NKBA-05",    "No traffic path crosses triangle"),
        ("NKBA-06",    "Work aisle ≥ 1067mm (1 cook)"),
        ("NKBA-06b",   "Work aisle ≥ 1219mm (2+ cooks)"),
        ("NKBA-07",    "Walkway ≥ 914mm"),
        ("NKBA-08",    "Seating clearance ≥ 813/914mm"),
        ("NKBA-10",    "Sink adjacent to cooktop + fridge"),
        ("NKBA-11",    "Sink landing ≥ 610mm / 457mm"),
        ("NKBA-12",    "Prep area ≥ 762×610mm"),
        ("NKBA-13",    "DW within 914mm of sink"),
        ("NKBA-LA-01", "Fridge landing ≥ 381mm"),
        ("NKBA-LA-02", "Cooktop landing ≥ 305mm / 381mm"),
        ("NKBA-LA-03", "Oven landing ≥ 381mm"),
        ("NKBA-LA-05", "Microwave landing ≥ 381mm"),
        ("NKBA-18",    "Clearance above cooktop ≥ 610mm"),
        ("NKBA-19",    "Ducted hood ≥ 150 CFM"),
        ("NKBA-25",    "Total countertop ≥ 4013mm"),
    ],
}

def render_nkba_checklist(variant) -> None:
    violated = {v["rule_id"]: v.get("message", "") for v in variant.violations}
    warned   = {w.split(":")[0].strip() for w in variant.warnings if ":" in w}

    for group_name, rules in RULE_GROUPS.items():
        st.markdown(f'<div class="section-label" style="margin-top:16px">{group_name}</div>',
                    unsafe_allow_html=True)
        rows_html = ""
        for rule_id, desc in rules:
            if rule_id in violated:
                rows_html += f"""
                <div class="rule-row rule-fail">
                  <span class="rule-icon">✗</span>
                  <span class="rule-id">{rule_id}</span>
                  <span class="rule-desc">{desc}</span>
                  <span class="rule-msg">{violated[rule_id]}</span>
                </div>"""
            elif rule_id in warned:
                rows_html += f"""
                <div class="rule-row rule-warn">
                  <span class="rule-icon">⚠</span>
                  <span class="rule-id">{rule_id}</span>
                  <span class="rule-desc">{desc}</span>
                </div>"""
            else:
                rows_html += f"""
                <div class="rule-row rule-pass">
                  <span class="rule-icon">✓</span>
                  <span class="rule-id">{rule_id}</span>
                  <span class="rule-desc">{desc}</span>
                </div>"""
        st.markdown(rows_html, unsafe_allow_html=True)
```

---

## Tab 2 — Kitchen Designer

```python
def _tab_designer() -> None:
    if "final_output" not in st.session_state:
        st.info("Generate layouts from the Homeowner tab first.")
        return

    final  = st.session_state["final_output"]
    st.markdown('<div class="section-title">All Variants — Side by Side</div>', unsafe_allow_html=True)

    cols = st.columns(len(final.layouts), gap="small")
    for col, v in zip(cols, final.layouts):
        with col:
            sc  = v.score
            cls = _score_class(sc)
            st.markdown(f"""
            <div class="card" style="text-align:center">
              <div style="font-size:11px;color:#8B949E;margin-bottom:4px">{v.variant_id}</div>
              <div style="font-size:16px;font-weight:700;color:#E6EDF3">{v.family}</div>
              <div class="score-ring score-ring-{cls}" style="margin:10px auto">{sc:.2f}</div>
            </div>
            """, unsafe_allow_html=True)
            img = Path(f"renders/{v.variant_id}_top.png")
            if img.exists():
                st.image(str(img), use_container_width=True)
            # Zone breakdown
            zones_in_variant = {}
            for item in v.layout.values():
                if isinstance(item, dict) and not item.get("is_wall"):
                    z = item.get("zone_type", "unknown")
                    zones_in_variant[z] = zones_in_variant.get(z, 0) + 1
            chips = "".join(
                f'<span class="zone-chip zone-{z}">{z} ×{cnt}</span>'
                for z, cnt in sorted(zones_in_variant.items())
            )
            st.markdown(f'<div class="zone-bar" style="margin-top:8px">{chips}</div>',
                        unsafe_allow_html=True)
```

---

## Tab 3 — Catalog Manager

```python
def _tab_catalog() -> None:
    import json
    from pathlib import Path

    st.markdown('<div class="section-title">MCP Catalog Server</div>', unsafe_allow_html=True)

    # Status + catalog info
    catalog = json.loads(Path("catalog.json").read_text())
    items   = catalog.get("items", catalog) if "items" in catalog else list(catalog.values()) if isinstance(catalog, dict) else catalog
    n_skus  = len(items)

    col_a, col_b = st.columns(2, gap="large")
    with col_a:
        st.markdown(f"""
        <div class="card" style="margin-bottom:12px">
          <span class="status-dot dot-green"></span>
          <span style="color:#E6EDF3;font-size:14px;font-weight:600">MCP Server — Online</span><br>
          <span style="font-size:12px;color:#8B949E;margin-left:20px">catalog.json loaded · {n_skus} SKUs</span>
        </div>
        """, unsafe_allow_html=True)

        st.markdown('<div class="section-label" style="margin-top:16px">9 MCP Tools</div>',
                    unsafe_allow_html=True)
        TOOLS = [
            ("get_catalog_items()",             "List all SKUs"),
            ("get_skus_by_category(cat)",       "Filter by type"),
            ("get_sku_dimensions(sku_id)",       "width/depth/height"),
            ("get_sku_constraints(sku_id)",      "clearance/water/power"),
            ("get_skus_by_price_tier(tier)",     "low/mid/high"),
            ("get_skus_by_style(style)",         "modern/traditional"),
            ("resolve_color(keyword)",           "keyword → hex → SKU"),
            ("validate_placement(sku, mm)",      "fit + NKBA check"),
            ("check_clearance(sku, adj)",        "front clearance check"),
        ]
        for name, desc in TOOLS:
            st.markdown(f"""
            <div class="tool-row">
              <span class="tool-name">{name}</span>
              <span class="tool-desc">{desc}</span>
              <span class="tool-ok">✓</span>
            </div>
            """, unsafe_allow_html=True)

    with col_b:
        # SKU swatches
        st.markdown('<div class="section-label">SKUs in Last Layout</div>', unsafe_allow_html=True)
        if "final_output" in st.session_state:
            used_skus: set[str] = set()
            for v in st.session_state["final_output"].layouts:
                for item in v.layout.values():
                    if isinstance(item, dict) and not item.get("is_wall"):
                        if pid := item.get("product_id"):
                            used_skus.add(pid)
            catalog_flat = {s["sku_id"]: s for s in (items if isinstance(items, list) else items.values())}
            for sku_id in sorted(used_skus):
                sku  = catalog_flat.get(sku_id, {})
                name = sku.get("name", sku_id)
                hex_c = sku.get("color", "#484F58")
                st.markdown(f"""
                <div class="sku-swatch-row">
                  <div class="color-dot" style="background:{hex_c}"></div>
                  <span class="sku-id">{sku_id}</span>
                  <span class="sku-name">{name}</span>
                  <span class="hex-code">{hex_c}</span>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.caption("Generate layouts first to see used SKUs.")
```

---

## Tab 4 — Design Reviewer

```python
def _tab_reviewer() -> None:
    if "final_output" not in st.session_state:
        st.info("Generate layouts from the Homeowner tab first.")
        return

    final = st.session_state["final_output"]
    st.markdown('<div class="section-title">Full Technical Review</div>', unsafe_allow_html=True)

    variant_ids = [v.variant_id for v in final.layouts]
    selected_id = st.selectbox("Select Variant", variant_ids, label_visibility="visible")
    variant     = next(v for v in final.layouts if v.variant_id == selected_id)

    col_check, col_rationale = st.columns([1, 1], gap="large")

    with col_check:
        render_nkba_checklist(variant)

    with col_rationale:
        st.markdown('<div class="section-label">AI Rationale</div>', unsafe_allow_html=True)
        for entry in variant.rationale:
            st.markdown(f"""
            <div class="card" style="margin-bottom:8px;padding:12px 16px">
              <div style="font-size:11px;font-family:'JetBrains Mono',monospace;
                          color:#00D4B1;margin-bottom:4px">{entry['rule_id']}</div>
              <div style="font-size:13px;color:#E6EDF3">{entry['text']}</div>
            </div>
            """, unsafe_allow_html=True)

        # Score breakdown
        st.markdown('<div class="section-label" style="margin-top:20px">Score Breakdown</div>',
                    unsafe_allow_html=True)
        from pipeline.nkba_validator import RULE_WEIGHTS
        base = 1.0 + (variant.nkba_compliance_pct * 0.30)
        st.metric("Base Score", f"{base:.3f}")
        for rule_id, w in sorted(RULE_WEIGHTS.items(), key=lambda x: -x[1]):
            violated = any(v["rule_id"] == rule_id for v in variant.violations)
            color = "#F85149" if violated else "#39D353"
            st.markdown(f"""
            <div style="display:flex;justify-content:space-between;
                        padding:5px 10px;border-radius:6px;
                        background:{'rgba(248,81,73,0.06)' if violated else 'transparent'};
                        margin-bottom:3px;font-size:12px">
              <span style="font-family:'JetBrains Mono',monospace;color:{color}">{rule_id}</span>
              <span style="color:{color}">{'−' if violated else '+'}{w:.2f}</span>
            </div>
            """, unsafe_allow_html=True)
```

---

## Live Pipeline Progress (wired to graph nodes)

The `PipelineLog` instance is passed into the graph via `st.session_state["pipeline_log"]`.
Each LangGraph node calls `st.session_state["pipeline_log"].complete(step_name)` when it finishes.
This gives real-time step-by-step progress in the UI without polling.

---

## Validation

```bash
streamlit run ui/app.py
# Verify:
# - Dark background loads (no white flash)
# - Hero gradient title visible
# - 3 room cards render with icons and tags
# - Generate button has teal gradient
# - After generate: summary strip + variant cards with score rings
# - Variant card: score ring colour matches score value
# - Zone chips coloured correctly
# - Tab 3: all 9 MCP tools listed with checkmarks
# - Tab 4: NKBA checklist colour-coded pass/fail
# - No console errors
```
