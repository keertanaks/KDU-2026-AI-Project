"""Model selection logic — single source of truth for which model to use where.

Set OPENROUTER_API_KEY in .env to route all API calls through OpenRouter instead of
the Anthropic API directly. Costs less; same quality for Sonnet/Haiku.

Set TEST_MODE=1 in .env to downgrade Agent 3 (layout_strategist) from Sonnet → Haiku.
This makes every full pipeline run ~10× cheaper — use during development/testing only.
"""

from __future__ import annotations

import os


class Models:
    HAIKU = "claude-haiku-4-5-20251001"  # fast/cheap — simple extraction, text gen
    SONNET = "claude-sonnet-4-6"  # default workhorse — spatial reasoning, planning
    OPUS = "claude-opus-4-7"  # heavy lifting only — reserved for retry escalation


class OpenRouterModels:
    """OpenRouter model IDs for Anthropic models.

    These match the same model versions as the direct Anthropic IDs above —
    OpenRouter uses dots (4.5 / 4.6 / 4.7) where Anthropic uses dashes.
    Verified against GET /api/v1/models on the active OpenRouter account.
    """

    HAIKU = "anthropic/claude-haiku-4.5"  # same as Models.HAIKU
    SONNET = "anthropic/claude-sonnet-4.6"  # same as Models.SONNET
    OPUS = "anthropic/claude-opus-4.7"  # same as Models.OPUS — retry only


# Maps each named agent to its default model.
# Change here to change globally — nowhere else.
_AGENT_MODELS: dict[str, str] = {
    "prompt_parser": Models.HAIKU,  # §5.1 — simple extraction
    "catalog_selector": Models.HAIKU,  # §5.2 — structured MCP queries
    "layout_strategist": Models.SONNET,  # §5.3 — spatial + creative reasoning
}

_OPENROUTER_AGENT_MODELS: dict[str, str] = {
    "prompt_parser": OpenRouterModels.HAIKU,
    "catalog_selector": OpenRouterModels.HAIKU,
    "layout_strategist": OpenRouterModels.SONNET,
}

# Only these agents may escalate to Opus, and only on retry.
_OPUS_ELIGIBLE: frozenset[str] = frozenset({"layout_strategist"})


def _use_openrouter() -> bool:
    """True when OPENROUTER_API_KEY is present in the environment."""
    return bool(os.getenv("OPENROUTER_API_KEY"))


def _test_mode() -> bool:
    """True when TEST_MODE=1 — downgrades Agent 3 to Haiku to save credits."""
    return os.getenv("TEST_MODE", "0").strip() == "1"


def for_agent(agent_name: str, *, is_retry: bool = False) -> str:
    """Return the correct model ID for an agent call.

    When OPENROUTER_API_KEY is set, returns OpenRouter model IDs.
    Otherwise uses Anthropic model IDs directly.
    Opus is used ONLY for layout_strategist retry (score < 0.60 or critical rule violated).
    """
    if _use_openrouter():
        # TEST_MODE: Agent 3 uses Haiku (no retry escalation) — for cheap dev runs
        if _test_mode() and agent_name == "layout_strategist":
            return OpenRouterModels.HAIKU
        # Retry escalates to Sonnet on OpenRouter (Opus not used — too expensive)
        if is_retry and agent_name in _OPUS_ELIGIBLE:
            return OpenRouterModels.SONNET
        model = _OPENROUTER_AGENT_MODELS.get(agent_name)
        if model is None:
            raise ValueError(
                f"Unknown agent '{agent_name}'. Valid names: {sorted(_OPENROUTER_AGENT_MODELS)}"
            )
        return model

    # TEST_MODE: downgrade Agent 3 to Haiku on direct Anthropic path too
    if _test_mode() and agent_name == "layout_strategist":
        return Models.HAIKU
    # Retry stays on Sonnet — Opus is reserved only if explicitly re-enabled
    if is_retry and agent_name in _OPUS_ELIGIBLE:
        return Models.SONNET
    model = _AGENT_MODELS.get(agent_name)
    if model is None:
        raise ValueError(f"Unknown agent '{agent_name}'. Valid names: {sorted(_AGENT_MODELS)}")
    return model


def should_use_opus(score: float, violation_ids: list[str]) -> bool:
    """True when Agent 3 should be retried (score too low or critical rule violated).

    Retry trigger (design doc §3.1):
      score < 0.60  OR  WORKFLOW-03 violated  OR  NKBA-CL-01 violated

    The retry model is Sonnet (not Opus) — see for_agent(..., is_retry=True).
    Rename pending; function kept as-is to avoid touching all call sites.
    """
    return score < 0.60 or "WORKFLOW-03" in violation_ids or "NKBA-CL-01" in violation_ids
