"""Budget display component — renders Estimated Cost and substitution results.

UI rules (skills/ui-integration.md):
- This file contains ONLY display logic — no placement math, NKBA scoring,
  or catalog queries.
- All cost figures must be labeled "Estimated Cost" — not real prices.
- Business logic lives in pipeline/budget_optimizer.py, not here.
- Reads pre-computed BudgetOptimizationDTO from the variant DTO.

Design tokens match ui/app.py: dark navy background, teal accents.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from utils.logger import get_logger

logger = get_logger(__name__)

# ============================================================================
# Design tokens (kept in sync with ui/app.py)
# ============================================================================

_ACCENT = "#00D4B1"
_SURFACE = "#161B22"
_BORDER = "#30363D"
_TEXT = "#E6EDF3"
_TEXT_MUTED = "#8B949E"
_GREEN = "#38A169"
_AMBER = "#D69E2E"
_RED = "#E53E3E"


# ============================================================================
# Public API
# ============================================================================


def render_budget_panel(variant: Any) -> None:
    """Render the Estimated Cost panel for one variant.

    Reads the `budget_optimization` field from the variant (dataclass or dict).
    If the field is absent or None, renders a minimal "no budget data" note.

    Args:
        variant: VariantSummaryDTO (dataclass) or dict loaded from output.json.
                 Must be the full variant object — this function does NO calculation.
    """
    budget_opt = _get(variant, "budget_optimization")
    if budget_opt is None:
        st.caption("💰 Estimated Cost: not available for this variant.")
        return

    original = _get(budget_opt, "original_estimate")
    optimized = _get(budget_opt, "optimized_estimate")
    substitutions = _get(budget_opt, "substitutions") or []
    target = _get(budget_opt, "target_budget_gbp")
    within_budget = _get(budget_opt, "within_budget")
    nkba_delta = _get(budget_opt, "nkba_score_delta") or 0.0
    warnings_list = _get(budget_opt, "warnings") or []

    original_total = _get(original, "total_estimated_cost_gbp") or 0.0
    optimized_total = _get(optimized, "total_estimated_cost_gbp") if optimized else None

    # ── Header ──────────────────────────────────────────────────────────
    st.markdown(
        f'<p style="color:{_ACCENT};font-weight:700;margin:12px 0 4px">💰 Estimated Cost</p>',
        unsafe_allow_html=True,
    )
    st.caption("(i) All costs are estimates based on price tier — not real retail prices.")

    # ── Cost metrics ────────────────────────────────────────────────────
    cols = st.columns(3)
    with cols[0]:
        st.metric(
            "Original Estimated Cost",
            f"${original_total:,.0f}",
        )
    with cols[1]:
        if optimized_total is not None:
            savings = original_total - optimized_total
            st.metric(
                "After Optimisation",
                f"${optimized_total:,.0f}",
                delta=f"-${savings:,.0f}" if savings > 0 else "No change",
                delta_color="inverse" if savings > 0 else "off",
            )
        else:
            st.metric("After Optimisation", "—", help="No substitutions made")

    with cols[2]:
        if target:
            badge_color = _GREEN if within_budget else _RED
            badge_icon = "✅" if within_budget else "⚠️"
            label = "Within Budget" if within_budget else "Over Budget"
            st.markdown(
                f'<span style="color:{badge_color};font-weight:700">'
                f"{badge_icon} {label}"
                f'<br><span style="font-size:0.85rem;font-weight:400">'
                f"Target: ${target:,.0f}"
                f"</span></span>",
                unsafe_allow_html=True,
            )
        else:
            st.metric("Budget Target", "Not set")

    # ── Substitutions table ─────────────────────────────────────────────
    if substitutions:
        st.markdown(
            f'<p style="color:{_TEXT};font-weight:600;margin:10px 0 4px">'
            "Proposed Substitutions</p>",
            unsafe_allow_html=True,
        )

        rows = []
        for sub in substitutions:
            orig_sku = _get(sub, "original_sku_id") or "—"
            sub_sku = _get(sub, "substitute_sku_id") or "—"
            orig_tier = (_get(sub, "original_tier") or "—").capitalize()
            sub_tier = (_get(sub, "substitute_tier") or "—").capitalize()
            orig_cost = _get(sub, "original_cost_gbp") or 0.0
            sub_cost = _get(sub, "substitute_cost_gbp") or 0.0
            delta = _get(sub, "cost_delta_gbp") or 0.0
            score_before = _get(sub, "nkba_score_before") or 0.0
            score_after = _get(sub, "nkba_score_after") or 0.0
            color_ok = _get(sub, "color_preserved")

            rows.append(
                {
                    "Original SKU": orig_sku,
                    "Substitute SKU": sub_sku,
                    "Tier": f"{orig_tier} → {sub_tier}",
                    "Orig. Est. Cost": f"${orig_cost:,.0f}",
                    "Sub. Est. Cost": f"${sub_cost:,.0f}",
                    "Saving (Est.)": f"${-delta:,.0f}" if delta < 0 else "$0",
                    "NKBA Δ": f"{score_after - score_before:+.3f}",
                    "Color ✓": "Yes" if color_ok else "No",
                }
            )

        if rows:
            st.dataframe(rows, hide_index=True, use_container_width=True)

        # NKBA score impact summary
        if nkba_delta != 0.0:
            delta_color = _GREEN if nkba_delta >= 0 else _AMBER
            st.markdown(
                f'<p style="color:{delta_color};font-size:0.9rem">'
                f"NKBA score impact after all substitutions: {nkba_delta:+.3f}</p>",
                unsafe_allow_html=True,
            )
    elif target and not within_budget:
        st.warning(
            "⚠️ No suitable cheaper substitutes found for this variant. "
            "Consider choosing a different variant or adjusting the budget target."
        )

    # ── Optimizer warnings ──────────────────────────────────────────────
    for warn in warnings_list:
        st.caption(f"⚠️ {warn}")

    st.divider()


# ============================================================================
# Private helper
# ============================================================================


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Unified access for dataclass instances and dict results."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)
