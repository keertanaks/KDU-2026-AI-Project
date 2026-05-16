"""Variant card component — renders score, images, zone pills, and rationale."""

from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import streamlit as st

from layout import ZONE_COLORS
from utils.logger import get_logger

logger = get_logger(__name__)


def _get(obj: object, key: str) -> Any:
    """Unified access for dataclass and dict results."""
    return obj[key] if isinstance(obj, dict) else getattr(obj, key)


def score_badge(score: float) -> str:
    """Return HTML badge string for the given score."""
    color = "#38A169" if score > 0.8 else "#D69E2E" if score >= 0.6 else "#E53E3E"
    emoji = "🟢" if score > 0.8 else "🟡" if score >= 0.6 else "🔴"
    return (
        f'<span style="color:{color};font-weight:700;font-size:1.3rem">{emoji} {score:.2f}</span>'
    )


def zone_pills_html(layout_dict: dict[str, Any]) -> str:
    """Return HTML zone pill spans for items in layout_dict."""
    zone_counts: Counter[str] = Counter(
        item.get("zone_type", "unknown")
        for item in layout_dict.values()
        if not item.get("is_wall") and not item.get("is_floor")
    )
    return " ".join(
        f'<span style="background:{ZONE_COLORS.get(z, ZONE_COLORS["default"])};'
        f"color:#0D1117;padding:3px 10px;border-radius:12px;"
        f'font-size:0.8rem;margin:2px;display:inline-block">'
        f"{z.title()} ({n})</span>"
        for z, n in sorted(zone_counts.items())
    )


def render_variant_card(v: Any, index: int) -> None:
    """Render a full variant card with score, images, zones, violations, and rationale."""
    v_id = str(_get(v, "id"))
    family = str(_get(v, "family"))
    score = float(_get(v, "score"))
    count = int(_get(v, "placement_count"))
    violations = list(_get(v, "violations") or [])
    rationale = list(_get(v, "rationale") or [])
    layout = dict(_get(v, "layout") or {})

    st.markdown(
        f'<div class="card">'
        f"{score_badge(score)}"
        f'<span style="color:#8B949E;margin:0 12px">·</span>'
        f'<span style="color:#E6EDF3;font-weight:600">{v_id} -- {family}</span>'
        f'<span style="color:#8B949E;margin-left:12px;font-size:0.9rem">'
        f"{count} items placed</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    view = st.radio("", ["2D Top View", "3D View"], horizontal=True, key=f"view_{v_id}_{index}")
    img_path = f"renders/{v_id}_top.png" if view == "2D Top View" else f"renders/{v_id}_3d.png"
    if Path(img_path).exists():
        st.image(img_path, use_container_width=True)
    else:
        st.markdown(
            '<div style="background:#1C2128;border:1px dashed #30363D;border-radius:6px;'
            'padding:40px;text-align:center;color:#8B949E">Render not available -- '
            "run Generate to produce images</div>",
            unsafe_allow_html=True,
        )

    st.markdown(zone_pills_html(layout), unsafe_allow_html=True)

    if violations:
        st.markdown(
            f'<span style="color:#E53E3E">❌ {len(violations)} violation(s)</span>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown('<span style="color:#38A169">✅ No violations</span>', unsafe_allow_html=True)

    if rationale:
        for entry in rationale[:2]:
            rid = entry.get("rule_id", "")
            text = entry.get("text", "")
            st.markdown(
                f'<span style="background:#00D4B1;color:#0D1117;padding:1px 7px;'
                f'border-radius:8px;font-size:0.75rem">{rid}</span>'
                f'<span style="color:#8B949E;font-size:0.9rem;margin-left:6px">{text}</span>',
                unsafe_allow_html=True,
            )

    if st.button("🔄 Open Interactive 3D", key=f"3d_{v_id}_{index}"):
        subprocess.Popen(["python", "render.py", "output.json", "--show", "--3d-only"])

    st.markdown("<hr style='border-color:#30363D;margin:8px 0'>", unsafe_allow_html=True)
