"""Room selection picker component."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st

from utils.logger import get_logger

logger = get_logger(__name__)

ROOMS: list[dict[str, str]] = [
    {
        "file": "input1.json",
        "icon": "🏠",
        "name": "Compact Kitchen",
        "dims": "3600 x 3200mm",
        "openings": "No openings",
    },
    {
        "file": "input2.json",
        "icon": "🏗️",
        "name": "Open Plan",
        "dims": "42000 x 42000mm",
        "openings": "No openings",
    },
    {
        "file": "input3.json",
        "icon": "🪟",
        "name": "Family Kitchen",
        "dims": "4200 x 3000mm",
        "openings": "Door + 2 Windows",
    },
]


def render_room_picker() -> dict[str, Any]:
    """Render 3 room selection cards; return loaded input JSON for selected room."""
    if "selected_room" not in st.session_state:
        st.session_state["selected_room"] = 0

    st.markdown("**Select a room**")
    for i, room in enumerate(ROOMS):
        selected = st.session_state["selected_room"] == i
        border = "#00D4B1" if selected else "#30363D"
        bg = "#1C2128" if selected else "#161B22"
        st.markdown(
            f'<div style="border:1px solid {border};background:{bg};border-radius:8px;'
            f'padding:10px 14px;margin-bottom:6px">'
            f'<span style="font-size:1.3rem">{room["icon"]}</span> '
            f'<span style="color:#E6EDF3;font-weight:600">{room["name"]}</span><br>'
            f'<span style="color:#8B949E;font-size:0.85rem">'
            f"{room['dims']} · {room['openings']}</span></div>",
            unsafe_allow_html=True,
        )
        if st.button(f"Select {room['name']}", key=f"room_btn_{i}", use_container_width=True):
            st.session_state["selected_room"] = i
            st.rerun()

    chosen = ROOMS[st.session_state["selected_room"]]
    try:
        data: dict[str, Any] = json.loads(Path(chosen["file"]).read_text())
        return data
    except Exception as e:
        logger.error("failed to load %s: %s", chosen["file"], e)
        st.error(f"Could not load {chosen['file']}: {e}")
        return {}
