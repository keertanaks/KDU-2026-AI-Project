"""Variant card component — renders score, images, zone pills, and rationale."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
import streamlit as st

from utils.logger import get_logger

ZONE_COLORS: dict[str, str] = {
    "cooking": "#FF6B6B",
    "cleaning": "#4ECDC4",
    "cooling": "#45B7D1",
    "preparation": "#FFD700",
    "default": "#95A5A6",
}

logger = get_logger(__name__)


def _get(obj: object, key: str, default: Any = None) -> Any:
    """Unified access for dataclass and dict results."""
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)  # type: ignore[union-attr]


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
        if not item.get("is_wall")
        and not item.get("is_floor")
        and not item.get("is_door")
        and not item.get("is_window")
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
    v_id = str(_get(v, "id") or "")
    family = str(_get(v, "family") or "")
    score = float(_get(v, "score") or 0.0)
    count = int(_get(v, "placement_count") or 0)
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

    view = st.radio(
        "View",
        ["2D Top View", "3D View"],
        horizontal=True,
        key=f"view_{v_id}_{index}",
        label_visibility="collapsed",
    )
    img_path = f"renders/{v_id}_top.png" if view == "2D Top View" else f"renders/{v_id}_3d.png"
    if Path(img_path).exists():
        st.image(img_path, width="stretch")
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

    if st.button("🔄 Interactive 3D", key=f"3d_{v_id}_{index}"):
        fig = go.Figure()

        # Get room dimensions
        env = _get(v, "environment") or {}
        floor_data = env.get("floor", {})
        walls_data = env.get("wall", [])

        floor_dims = floor_data.get("dimensions_mm", {})
        floor_x = float(floor_dims.get("width", 3600))
        floor_y = float(floor_dims.get("depth", 3200))

        # Add floor plane (light gray, bottom)
        fig.add_trace(
            go.Surface(
                x=[[0, floor_x], [0, floor_x]],
                y=[[0, 0], [floor_y, floor_y]],
                z=[[0, 0], [0, 0]],
                colorscale=[[0, "#F5F5F5"], [1, "#F5F5F5"]],
                showscale=False,
                name="Floor",
                hoverinfo="skip",
            )
        )

        # Add walls (semi-transparent pink)
        for wall in walls_data:
            wall_dims = wall.get("dimensions_mm", {})
            wall_x = float(wall_dims.get("width", 3600))
            wall_y = float(wall_dims.get("depth", 100))
            wall_z = float(wall_dims.get("height", 2500))
            pos = wall.get("position_mm", {})
            x0 = float(pos.get("x", 0))
            y0 = float(pos.get("y", 0))

            fig.add_trace(
                go.Surface(
                    x=[[x0, x0 + wall_x], [x0, x0 + wall_x]],
                    y=[[y0, y0], [y0 + wall_y, y0 + wall_y]],
                    z=[[0, 0], [wall_z, wall_z]],
                    colorscale=[[0, "#D9A8A8"], [1, "#D9A8A8"]],
                    showscale=False,
                    opacity=0.4,
                    hoverinfo="skip",
                )
            )

        # Add items as box meshes
        zone_colors = {
            "cooking": "#FF6B6B",
            "cleaning": "#4ECDC4",
            "cooling": "#45B7D1",
            "preparation": "#FFD700",
            "storage": "#95A5A6",
        }

        for item in layout.values():
            if (item.get("is_wall") or item.get("is_floor") or
                item.get("is_door") or item.get("is_window")):
                continue

            pos = item.get("position_mm", {})
            x = float(pos.get("x", 0))
            y = float(pos.get("y", 0))
            z = float(pos.get("z", 0))

            w = float(item.get("width_mm", 600))
            d = float(item.get("depth_mm", 600))
            h = float(item.get("height_mm", 900))

            item_name = item.get("product_id", item.get("name", "unknown"))
            zone_type = item.get("zone_type", "storage")
            color = zone_colors.get(zone_type, "#95A5A6")

            # Box vertices
            vertices = [
                [x, y, z], [x + w, y, z], [x + w, y + d, z], [x, y + d, z],
                [x, y, z + h], [x + w, y, z + h], [x + w, y + d, z + h], [x, y + d, z + h],
            ]

            # Box faces as triangles
            i, j, k = [], [], []
            faces = [[0, 1, 2, 3], [4, 7, 6, 5], [0, 4, 5, 1], [2, 6, 7, 3], [0, 3, 7, 4], [1, 5, 6, 2]]

            for face in faces:
                for idx in range(len(face) - 2):
                    i.extend([face[0], face[idx + 1], face[idx + 2]])
                    j.extend([face[idx + 1], face[idx + 2], face[0]])
                    k.extend([face[idx + 2], face[0], face[idx + 1]])

            x_v, y_v, z_v = zip(*vertices)

            fig.add_trace(
                go.Mesh3d(
                    x=x_v, y=y_v, z=z_v, i=i, j=j, k=k,
                    color=color, opacity=0.8, name=item_name,
                )
            )

        fig.update_layout(
            scene=dict(
                xaxis=dict(title="X (mm)", backgroundcolor="#1C2128"),
                yaxis=dict(title="Y (mm)", backgroundcolor="#1C2128"),
                zaxis=dict(title="Z (mm)", backgroundcolor="#1C2128"),
                bgcolor="#161B22", aspectmode="data",
            ),
            title=f"Interactive 3D: {v_id} ({family})",
            template="plotly_dark", font=dict(color="#E6EDF3"),
            paper_bgcolor="#161B22", plot_bgcolor="#1C2128", height=650,
        )

        st.plotly_chart(fig, use_container_width=True)

    st.markdown("<hr style='border-color:#30363D;margin:8px 0'>", unsafe_allow_html=True)
