"""NKBA 31-rule checklist component."""

from __future__ import annotations

from typing import Any

import streamlit as st

ALL_RULES: list[tuple[str, str, float]] = [
    ("NKBA-CL-01", "Fridge door swing -- >=1067mm clear in front", 0.10),
    ("NKBA-CL-02", "Door swing reservation -- 900x900mm clear inside arc", 0.10),
    ("WORKFLOW-01", "Sink near dishwasher -- DW within 600mm of sink", 0.10),
    ("WORKFLOW-02", "Stove not next to fridge -- >=600mm gap", 0.10),
    ("WORKFLOW-03", "Work triangle -- 3962-6600mm perimeter", 0.15),
    ("LAYOUT-01", "Sink under window -- +-300mm of window center", 0.08),
    ("LAYOUT-02", "Hood above stove -- +-100mm above stove XY", 0.08),
    ("LAYOUT-03", "Continuous run -- <=50mm gap between items", 0.08),
    ("LAYOUT-04", "Base cabinet coverage -- every appliance backed by base cab", 0.08),
    ("LAYOUT-05", "Mandatory base -- run terminates at base/corner", 0.07),
    ("LAYOUT-06", "Fridge at corner -- fridge + tall at corners/ends", 0.06),
    ("NKBA-01", "Kitchen entry clear opening >=813mm", 0.0),
    ("NKBA-02", "Appliance door interference -- doors must not collide", 0.0),
    ("NKBA-03", "Work triangle total <=7925mm maximum perimeter", 0.0),
    ("NKBA-04", "Tall obstacle separation -- tall cabs must not split work centers", 0.0),
    ("NKBA-05", "Work triangle traffic -- no primary path crosses triangle", 0.0),
    ("NKBA-06", 'Work aisle 1 cook >=1067mm (42")', 0.0),
    ("NKBA-06b", 'Work aisle 2+ cooks >=1219mm (48")', 0.0),
    ("NKBA-07", 'Walkway >=914mm (36") clearance', 0.0),
    ("NKBA-08", "Seating clearance >=813mm single, >=914mm multiple", 0.0),
    ("NKBA-10", "Sink adjacent to cooktop and refrigerator", 0.0),
    ("NKBA-11", "Sink landing >=610mm one side, >=457mm other", 0.0),
    ("NKBA-12", "Prep work area >=762x610mm counter next to sink", 0.0),
    ("NKBA-13", "Dishwasher within 914mm of sink + 533mm standing space", 0.0),
    ("NKBA-LA-01", "Fridge landing >=381mm on handle/latch side", 0.0),
    ("NKBA-LA-02", "Cooktop landing >=305mm one side AND >=381mm other", 0.0),
    ("NKBA-LA-03", "Oven landing >=381mm on either side", 0.0),
    ("NKBA-LA-05", "Microwave landing >=381mm below/beside handle side", 0.0),
    ("NKBA-18", "Clearance above cooktop >=610mm protected, >=762mm unprotected", 0.0),
    ("NKBA-19", "Ventilation -- ducted hood >=150 CFM", 0.0),
    ("NKBA-25", 'Total countertop >=4013mm (158") total frontage', 0.0),
]

RULE_WEIGHTS: dict[str, float] = {r[0]: r[2] for r in ALL_RULES}


def _get(obj: object, key: str) -> Any:
    """Unified access for dataclass and dict results."""
    return obj[key] if isinstance(obj, dict) else getattr(obj, key)


def render_nkba_checklist(v: Any) -> None:
    """Render the full 31-rule NKBA checklist for variant v."""
    violations_list: list[dict[str, Any]] = list(_get(v, "violations") or [])
    violated_ids = {x["rule_id"] for x in violations_list}
    viol_map = {x["rule_id"]: x for x in violations_list}

    project_rules = [r for r in ALL_RULES if r[2] > 0]
    official_rules = [r for r in ALL_RULES if r[2] == 0]

    with st.expander("📋 Project Rules (11) -- weighted penalties", expanded=True):
        for rule_id, desc, weight in project_rules:
            if rule_id in violated_ids:
                msg = viol_map[rule_id].get("message", "")
                st.markdown(
                    f"❌ **{rule_id}** -- {desc}  \n`{msg}`  "
                    f'<span style="color:#E53E3E">-{weight:.2f} pts</span>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(f"✅ **{rule_id}** -- {desc}")

    with st.expander("📋 Official NKBA Rules (20)", expanded=False):
        for rule_id, desc, _ in official_rules:
            if rule_id in violated_ids:
                msg = viol_map[rule_id].get("message", "")
                st.markdown(f"❌ **{rule_id}** -- {desc}  \n`{msg}`")
            else:
                st.markdown(f"✅ **{rule_id}** -- {desc}")
