"""Model selection logic — single source of truth for which model to use where."""
from __future__ import annotations


class Models:
    HAIKU  = "claude-haiku-4-5"    # fast/cheap — simple extraction, text gen
    SONNET = "claude-sonnet-4-6"   # default workhorse — spatial reasoning, planning
    OPUS   = "claude-opus-4-7"     # heavy lifting only — reserved for retry escalation


# Maps each named agent to its default model.
# Change here to change globally — nowhere else.
_AGENT_MODELS: dict[str, str] = {
    "prompt_parser":       Models.HAIKU,    # §5.1 — simple extraction
    "catalog_selector":    Models.HAIKU,    # §5.2 — structured MCP queries
    "layout_strategist":   Models.SONNET,   # §5.3 — spatial + creative reasoning
    "rationale_writer":    Models.HAIKU,    # §5.4 — short text generation
}

# Only these agents may escalate to Opus, and only on retry.
_OPUS_ELIGIBLE: frozenset[str] = frozenset({"layout_strategist"})


def for_agent(agent_name: str, *, is_retry: bool = False) -> str:
    """Return the correct model ID for an agent call.

    Opus is used ONLY for layout_strategist retry (score < 0.60 or critical rule violated).
    Everything else uses Haiku or Sonnet per the design doc §4.
    """
    if is_retry and agent_name in _OPUS_ELIGIBLE:
        return Models.OPUS
    model = _AGENT_MODELS.get(agent_name)
    if model is None:
        raise ValueError(
            f"Unknown agent '{agent_name}'. "
            f"Valid names: {sorted(_AGENT_MODELS)}"
        )
    return model


def should_use_opus(score: float, violation_ids: list[str]) -> bool:
    """True when Agent 3 retry should escalate to Opus.

    Retry trigger (design doc §3.1):
      score < 0.60  OR  WORKFLOW-03 violated  OR  NKBA-CL-01 violated
    """
    return (
        score < 0.60
        or "WORKFLOW-03" in violation_ids
        or "NKBA-CL-01" in violation_ids
    )
