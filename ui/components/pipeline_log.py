"""Live pipeline stage log component."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import Any

import anthropic
import streamlit as st

from graph.kitchen_graph import KitchenGraph
from utils.logger import get_logger
from utils.openrouter_compat import OpenRouterCompat

logger = get_logger(__name__)

# Union type accepted by KitchenGraph
_AnyClient = anthropic.Anthropic | OpenRouterCompat


def _make_client() -> _AnyClient:
    """Return the appropriate LLM client.

    • OPENROUTER_API_KEY set → OpenRouterCompat (routes via openai SDK to OpenRouter)
    • Otherwise            → anthropic.Anthropic (uses ANTHROPIC_API_KEY)

    OpenRouter exposes an OpenAI-compatible endpoint only; the Anthropic SDK's
    /messages path does not exist there, so we use our own shim instead.
    """
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_key:
        logger.info("Using OpenRouter via OpenAI-compat shim (OPENROUTER_API_KEY set)")
        return OpenRouterCompat(api_key=openrouter_key)
    logger.info("Using Anthropic API directly (ANTHROPIC_API_KEY)")
    return anthropic.Anthropic()  # uses ANTHROPIC_API_KEY from env


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


def _run_async_in_thread(coro: Any) -> Any:
    """Run a coroutine in a dedicated thread with its own event loop.

    Streamlit may already have a running event loop in the script thread;
    creating a new loop in a daemon thread avoids RuntimeError conflicts.
    """
    result_holder: list[Any] = [None]
    exc_holder: list[BaseException | None] = [None]

    def _target() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result_holder[0] = loop.run_until_complete(coro)
        except Exception as exc:
            exc_holder[0] = exc
        finally:
            loop.close()

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=600)

    if exc_holder[0] is not None:
        raise exc_holder[0]
    return result_holder[0]


def run_pipeline_with_log(input_json: dict[str, Any]) -> Any | None:
    """Run KitchenGraph with live stage display. Returns FinalOutput or None on error."""
    log_placeholder = st.empty()
    _render_stages(log_placeholder, done=False, active_idx=0)
    t0 = time.time()

    try:
        client = _make_client()
        result = _run_async_in_thread(
            KitchenGraph(client, output_path="latest_run.json").run(input_json)
        )
        elapsed = time.time() - t0
        log_placeholder.markdown(
            "\n\n".join([f"✅ {s}" for s in STAGES]) + f"\n\n**Total: {elapsed:.1f}s ✅**",
            unsafe_allow_html=True,
        )
        return result
    except Exception as e:
        logger.error("pipeline failed: %s", e)
        st.error(f"Pipeline failed: {e}")
        return None
