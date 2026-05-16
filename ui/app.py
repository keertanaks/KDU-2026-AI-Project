"""KitchenAI Streamlit UI — 4-persona tabs, dark theme."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Add repo root to sys.path so graph/, utils/, layout.py, dtos/ are importable
# when Streamlit runs ui/app.py (which only adds ui/ to sys.path by default).
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import streamlit as st

from components.nkba_checklist import RULE_WEIGHTS, render_nkba_checklist
from components.pipeline_log import run_pipeline_with_log
from components.room_picker import render_room_picker
from components.variant_card import render_variant_card, score_badge, zone_pills_html
from utils.logger import get_logger

logger = get_logger(__name__)

# ============================================================================
# Design tokens
# ============================================================================

BG = "#0D1117"
SURFACE = "#161B22"
SURFACE2 = "#1C2128"
BORDER = "#30363D"
ACCENT = "#00D4B1"
TEXT = "#E6EDF3"
TEXT_MUTED = "#8B949E"
SCORE_GREEN = "#38A169"
SCORE_AMBER = "#D69E2E"
SCORE_RED = "#E53E3E"

GLOBAL_CSS = """
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
.main .block-container { background-color: #0D1117!important; color: #E6EDF3!important; }

[data-testid="stSidebar"] > div:first-child {
    background-color: #161B22!important;
    border-right: 1px solid #30363D;
}

.block-container { padding-top: 1.5rem!important; }

[data-testid="stTabs"] button { color: #8B949E!important; border-bottom: 2px solid transparent; }
[data-testid="stTabs"] button[aria-selected="true"] {
    color: #00D4B1!important;
    border-bottom: 2px solid #00D4B1!important;
    background: transparent!important;
}

.stButton > button {
    background-color: #00D4B1!important;
    color: #0D1117!important;
    border: none!important;
    border-radius: 6px!important;
    font-weight: 600!important;
}
.stButton > button:hover { background-color: #007A6B!important; }

[data-testid="stMetricLabel"] { color: #00D4B1!important; }

[data-testid="stTextArea"] textarea,
[data-testid="stSelectbox"] > div,
[data-testid="stMultiSelect"] > div {
    background-color: #1C2128!important;
    border: 1px solid #30363D!important;
    color: #E6EDF3!important;
}

[data-testid="stDataFrame"] { background-color: #161B22!important; }
iframe { background-color: #161B22!important; }
hr { border-color: #30363D!important; }
[data-testid="stAlert"] { border-radius: 6px!important; }

.card {
    background: #161B22;
    border: 1px solid #30363D;
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 16px;
}
.card-selected { border-color: #00D4B1!important; }
"""

# ============================================================================
# Page config — must be first Streamlit call
# ============================================================================

st.set_page_config(
    page_title="KitchenAI",
    page_icon="🍳",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(f"<style>{GLOBAL_CSS}</style>", unsafe_allow_html=True)

# ============================================================================
# Helpers
# ============================================================================


def _get(obj: object, key: str, default: Any = None) -> Any:
    """Unified access for dataclass results and dict results loaded from output.json."""
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)  # type: ignore[union-attr]


# ============================================================================
# Startup — load output.json if present
# ============================================================================

if "result" not in st.session_state and Path("output.json").exists():
    try:
        st.session_state["result"] = json.loads(Path("output.json").read_text())
    except Exception as e:
        logger.error("failed to load output.json: %s", e)

# ============================================================================
# Sidebar
# ============================================================================

with st.sidebar:
    st.markdown('<h1 style="color:#00D4B1;margin:0">🍳 KitchenAI</h1>', unsafe_allow_html=True)
    st.caption("Powered by Claude")
    st.divider()

    input_json = render_room_picker()
    st.divider()

    prompt = st.text_area(
        "Describe your dream kitchen...",
        height=90,
        placeholder="e.g. I want navy blue cabinets with an island",
    )
    budget = st.radio("Budget", ["Low", "Mid", "High"], horizontal=True, index=1)
    must_have = st.multiselect(
        "Must include", ["Dishwasher", "Hood", "Island", "Oven", "Microwave"]
    )
    avoid = st.multiselect("Avoid", ["Double sink", "Island", "Tall cabinets"])
    generate = st.button("✨ Generate Layouts", type="primary", use_container_width=True)

if generate and input_json:
    input_json.setdefault("preferences", {})
    input_json["preferences"]["prompt"] = prompt
    input_json["preferences"]["budget_tier"] = budget.lower()
    input_json["preferences"]["must_have"] = [x.lower().replace(" ", "_") for x in must_have]
    input_json["preferences"]["avoid"] = [x.lower().replace(" ", "_") for x in avoid]
    result = run_pipeline_with_log(input_json)
    if result is not None:
        st.session_state["result"] = result
        st.rerun()

# ============================================================================
# Tabs
# ============================================================================

tab1, tab2, tab3, tab4 = st.tabs(
    ["🏠 My Kitchen", "📐 Designer View", "📦 Catalog & MCP", "🔍 Design Review"]
)

# ============================================================================
# Tab 1 — My Kitchen
# ============================================================================

with tab1:
    result = st.session_state.get("result")
    if not result:
        st.markdown(
            """
<div style="text-align:center;padding:80px 0;color:#8B949E">
  <div style="font-size:4rem">🍳</div>
  <h2 style="color:#00D4B1;margin:8px 0">KitchenAI</h2>
  <p style="font-size:1.1rem">Select a room on the left,<br>describe your style, and hit<br>
  <span style="color:#00D4B1;font-weight:700">✨ Generate Layouts</span></p>
</div>
""",
            unsafe_allow_html=True,
        )
    else:
        layouts = _get(result, "layouts")
        for i, v in enumerate(layouts):
            render_variant_card(v, i)

# ============================================================================
# Tab 2 — Designer View
# ============================================================================

with tab2:
    result = st.session_state.get("result")
    if not result:
        st.info("Run Generate first to see the designer view.")
    else:
        layouts = _get(result, "layouts")
        cols = st.columns(len(layouts))
        for col, v in zip(cols, layouts, strict=False):
            with col:
                v_id = str(_get(v, "id") or "")
                family = str(_get(v, "family") or "")
                score = float(_get(v, "score") or 0.0)
                layout = dict(_get(v, "layout") or {})
                viols = list(_get(v, "violations") or [])

                st.markdown(
                    f"{score_badge(score)}"
                    f'<br><span style="color:#E6EDF3;font-weight:600">{v_id} -- {family}</span>',
                    unsafe_allow_html=True,
                )
                st.progress(min(score / 1.3, 1.0))

                img = f"renders/{v_id}_top.png"
                if Path(img).exists():
                    st.image(img, use_container_width=True)

                st.markdown(zone_pills_html(layout), unsafe_allow_html=True)

                wt_text = "N/A"
                for entry in _get(v, "rationale") or []:
                    if entry.get("rule_id") == "WORKFLOW-03":
                        wt_text = entry.get("text", "N/A")
                        break
                if wt_text == "N/A":
                    for viol in viols:
                        if viol.get("rule_id") == "WORKFLOW-03":
                            wt_text = viol.get("message", "Violated")
                            break
                st.metric("Work Triangle", wt_text)

                if viols:
                    st.error(f"{len(viols)} violation(s)")
                else:
                    st.success("✅ All rules passed")

                rows: list[dict[str, Any]] = []
                for name, item in layout.items():
                    if item.get("is_wall") or item.get("is_floor"):
                        continue
                    pos = item.get("position_mm", {})
                    rows.append(
                        {
                            "Item": name,
                            "Zone": item.get("zone_type", "--"),
                            "x mm": int(pos.get("x", 0)),
                            "y mm": int(pos.get("y", 0)),
                            "z mm": int(pos.get("z", 0)),
                            "SKU": item.get("product_id", "--"),
                        }
                    )
                if rows:
                    st.dataframe(rows, use_container_width=True, hide_index=True)

# ============================================================================
# Tab 3 — Catalog & MCP
# ============================================================================

with tab3:
    result = st.session_state.get("result")
    req_id = str(_get(result, "request_id")) if result else "--"

    st.markdown(
        f"""
<div class="card">
  <span style="color:#38A169">●</span> <b>MCP Server</b>
  <span style="color:#38A169;margin-left:8px">✅ Ready</span><br>
  <span style="color:#38A169">●</span> <b>Catalog</b>
  <span style="color:#8B949E;margin-left:8px">catalog.json -- 28 SKUs</span><br>
  <span style="color:#38A169">●</span> <b>Last run</b>
  <span style="color:#8B949E;margin-left:8px">{req_id}</span>
</div>
""",
        unsafe_allow_html=True,
    )

    st.selectbox("Active catalog", ["catalog"], disabled=True)
    st.caption("Swap catalog by changing catalogId in preferences JSON")

    MCP_TOOLS: list[tuple[str, str]] = [
        ("get_catalog_items()", "List all 28 SKUs"),
        ("get_skus_by_category(category)", "Filter by cabinet / appliance / fixture"),
        ("get_sku_dimensions(sku_id)", "width_mm, depth_mm, height_mm"),
        ("get_sku_constraints(sku_id)", "clearance, needs_water, needs_power"),
        ("get_skus_by_price_tier(tier)", "low / mid / high"),
        ("get_skus_by_style(style)", "modern / traditional / minimalist"),
        ("resolve_color(keyword)", "keyword -> hex -> catalog match"),
        ("validate_placement(sku_id, wall)", "fit check + NKBA constraints"),
        ("check_clearance(sku_id, items)", "front clearance verification"),
    ]
    st.dataframe(
        [{"Tool": t, "Status": "✅ Ready", "Description": d} for t, d in MCP_TOOLS],
        use_container_width=True,
        hide_index=True,
    )

    if result:
        try:
            catalog_data: list[dict[str, Any]] = json.loads(Path("catalog.json").read_text())
            sku_map_local: dict[str, dict[str, Any]] = {s["id"]: s for s in catalog_data}
            top_layout = dict(_get(_get(result, "layouts")[0], "layout") or {})
            used_ids = sorted(
                {item.get("product_id") for item in top_layout.values() if item.get("product_id")}
            )
            sku_rows: list[dict[str, Any]] = []
            for sku_id in used_ids:
                sku = sku_map_local.get(sku_id, {})
                color_hex = sku.get("color", "#888888")
                sku_rows.append(
                    {
                        "SKU": sku_id,
                        "Type": sku.get("type", sku_id),
                        "Category": sku.get("category", "--"),
                        "Color": color_hex,
                        "Width mm": sku.get("width_mm", "--"),
                        "Price tier": sku.get("price_tier", "--"),
                    }
                )
            st.subheader("SKUs used in top variant")
            for row in sku_rows:
                hex_c = row["Color"]
                st.markdown(
                    f'<span style="background:{hex_c};display:inline-block;width:14px;'
                    f"height:14px;border-radius:3px;vertical-align:middle;"
                    f'margin-right:6px"></span>'
                    f"**{row['SKU']}** -- {row['Type']} · {row['Category']} · "
                    f"{row['Width mm']}mm · {row['Price tier']}",
                    unsafe_allow_html=True,
                )
        except Exception as e:
            logger.error("catalog load failed: %s", e)
            st.error(f"Could not load catalog: {e}")

# ============================================================================
# Tab 4 — Design Review
# ============================================================================

with tab4:
    result = st.session_state.get("result")
    if not result:
        st.info("Run Generate first to see the design review.")
    else:
        layouts = _get(result, "layouts")
        variant_ids = [str(_get(v, "id")) for v in layouts]
        chosen_id = st.selectbox("Review variant", variant_ids)
        chosen_v = next(x for x in layouts if str(_get(x, "id")) == chosen_id)

        col_left, col_right = st.columns([1, 1])
        with col_left:
            render_nkba_checklist(chosen_v)

        with col_right:
            viols = list(_get(chosen_v, "violations") or [])
            penalty = sum(RULE_WEIGHTS.get(x["rule_id"], 0.0) for x in viols)
            nkba_pct = float(_get(chosen_v, "nkba_compliance_pct") or 0.0)
            spillover = int(_get(chosen_v, "spillover_count") or 0)
            score = float(_get(chosen_v, "score") or 0.0)

            st.subheader("Score Breakdown")
            st.markdown(
                f"""
| Component | Value |
|---|---|
| Base score | 1.00 |
| + NKBA compliance bonus | +{nkba_pct * 0.30:.2f} |
| - Spillover penalties | -{spillover * 0.05:.2f} |
| - Rule violation penalties | -{penalty:.2f} |
| **= Final score** | **{score:.2f}** |
"""
            )

            st.subheader("AI Rationale")
            for entry in _get(chosen_v, "rationale") or []:
                rid = entry.get("rule_id", "")
                text = entry.get("text", "")
                st.markdown(
                    f'<span style="background:#00D4B1;color:#0D1117;padding:2px 8px;'
                    f'border-radius:10px;font-size:0.75rem">{rid}</span> '
                    f'<span style="color:#E6EDF3">{text}</span>',
                    unsafe_allow_html=True,
                )

            color_match = [
                e for e in (_get(chosen_v, "rationale") or []) if e.get("rule_id") == "COLOR-MATCH"
            ]
            if color_match:
                st.success(f"✅ {color_match[0]['text']}")
            else:
                st.info("No color constraint in prompt")

        st.subheader("All Variants Comparison")
        comparison_rows: list[dict[str, Any]] = []
        for variant in layouts:
            comparison_rows.append(
                {
                    "Variant": str(_get(variant, "id") or ""),
                    "Score": f"{float(_get(variant, 'score') or 0.0):.2f}",
                    "Family": str(_get(variant, "family") or ""),
                    "NKBA %": f"{float(_get(variant, 'nkba_compliance_pct') or 0.0) * 100:.0f}%",
                    "Violations": len(list(_get(variant, "violations") or [])),
                    "Spillover": int(_get(variant, "spillover_count") or 0),
                    "Items": int(_get(variant, "placement_count") or 0),
                }
            )
        st.dataframe(comparison_rows, use_container_width=True, hide_index=True)
