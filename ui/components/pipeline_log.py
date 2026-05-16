"""Live pipeline stage log component."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import anthropic
import streamlit as st

from graph.kitchen_graph import KitchenGraph
from utils.logger import get_logger

logger = get_logger(__name__)

STAGES: list[str] = [
    "Parsing room geometry",
    "Parsing prompt intent",
    "Querying catalog via MCP",
    "Planning layout variants",
    "Computing coordinates",
    "Validating NKBA rules",
    "Writing rationale",
    "Rendering 2D + 3D views",
]


def _render_stages(placeholder: Any, done: bool, active_idx: int = 0) -> None:
    """Render stage list into placeholder."""
    lines: list[str] = []
    for i, stage in enumerate(STAGES):
        if done:
            lines.append(f"✅ {stage}")
        elif i == active_idx:
            lines.append(f"⏳ {stage}...")
        else:
            lines.append(f'<span style="color:#8B949E">· {stage}</span>')
    placeholder.markdown("\n\n".join(lines), unsafe_allow_html=True)


def run_pipeline_with_log(input_json: dict[str, Any]) -> Any | None:
    """Run KitchenGraph with live stage display. Returns FinalOutput or None on error."""
    log_placeholder = st.empty()
    _render_stages(log_placeholder, done=False, active_idx=0)
    t0 = time.time()

    try:
        client = anthropic.Anthropic()
        result = asyncio.run(KitchenGraph(client, output_path="output.json").run(input_json))
        elapsed = time.time() - t0
        _render_stages(log_placeholder, done=True)
        log_placeholder.markdown(
            "\n\n".join([f"✅ {s}" for s in STAGES]) + f"\n\n**Total: {elapsed:.1f}s ✅**",
            unsafe_allow_html=True,
        )
        return result
    except Exception as e:
        logger.error("pipeline failed: %s", e)
        st.error(f"Pipeline failed: {e}")
        return None
