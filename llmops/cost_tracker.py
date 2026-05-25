"""Cost tracker — compute and accumulate per-call cost breakdowns.

Pricing constants are PLACEHOLDERS. Update from the Anthropic pricing page
before production use. Math correctness is verified by cost_evaluator.py.

TODO: update MODEL_COSTS from current Anthropic pricing page before production use.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import logging

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pricing constants — PLACEHOLDERS, see TODO above
# ---------------------------------------------------------------------------

CACHE_READ_MULTIPLIER: float = 0.10
CACHE_WRITE_MULTIPLIER: float = 1.25

# Cost per 1M tokens in USD (input / output / cache-write / cache-read)
# TODO: update these constants from current Anthropic pricing before production use.
MODEL_COSTS: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {
        "input_per_1m":       0.80,
        "output_per_1m":      4.00,
        "cache_write_per_1m": 1.00,   # input * CACHE_WRITE_MULTIPLIER
        "cache_read_per_1m":  0.08,   # input * CACHE_READ_MULTIPLIER
    },
    "claude-sonnet-4-6": {
        "input_per_1m":       3.00,
        "output_per_1m":      15.00,
        "cache_write_per_1m": 3.75,
        "cache_read_per_1m":  0.30,
    },
    "claude-opus-4-7": {
        "input_per_1m":       15.00,
        "output_per_1m":      75.00,
        "cache_write_per_1m": 18.75,
        "cache_read_per_1m":  1.50,
    },
    # OpenRouter IDs (same underlying models)
    "anthropic/claude-haiku-4.5": {
        "input_per_1m":       0.80,
        "output_per_1m":      4.00,
        "cache_write_per_1m": 1.00,
        "cache_read_per_1m":  0.08,
    },
    "anthropic/claude-sonnet-4.6": {
        "input_per_1m":       3.00,
        "output_per_1m":      15.00,
        "cache_write_per_1m": 3.75,
        "cache_read_per_1m":  0.30,
    },
    "anthropic/claude-opus-4.7": {
        "input_per_1m":       15.00,
        "output_per_1m":      75.00,
        "cache_write_per_1m": 18.75,
        "cache_read_per_1m":  1.50,
    },
}

TOKENS_PER_MILLION: float = 1_000_000.0


@dataclass
class CostBreakdown:
    agent_name: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    raw_cost_usd: float
    actual_cost_usd: float
    cache_savings_usd: float


class CostTracker:
    """Compute per-call cost breakdowns and accumulate session totals."""

    def __init__(self) -> None:
        self._breakdowns: list[CostBreakdown] = []

    def from_usage(
        self,
        agent_name: str,
        model: str,
        usage: dict[str, Any],
    ) -> CostBreakdown:
        """Build a CostBreakdown from a usage dict returned by the Anthropic SDK.

        usage keys:
          - input_tokens
          - output_tokens
          - cache_creation_input_tokens (default 0)
          - cache_read_input_tokens (default 0)
        """
        rates = MODEL_COSTS.get(model)
        if rates is None:
            # Fallback to Sonnet if model not found
            _log.warning("Unknown model '%s' for cost calculation — using Sonnet rates", model)
            rates = MODEL_COSTS["claude-sonnet-4-6"]

        input_tok = int(usage.get("input_tokens", 0))
        output_tok = int(usage.get("output_tokens", 0))
        cache_write_tok = int(usage.get("cache_creation_input_tokens", 0))
        cache_read_tok = int(usage.get("cache_read_input_tokens", 0))

        # Raw cost: as if no caching (all input billed at standard input rate)
        raw_input_tok = input_tok + cache_write_tok + cache_read_tok
        raw_cost = (
            raw_input_tok * rates["input_per_1m"] / TOKENS_PER_MILLION
            + output_tok * rates["output_per_1m"] / TOKENS_PER_MILLION
        )

        # Actual cost: cache writes billed at write rate, reads at read rate
        actual_cost = (
            input_tok * rates["input_per_1m"] / TOKENS_PER_MILLION
            + output_tok * rates["output_per_1m"] / TOKENS_PER_MILLION
            + cache_write_tok * rates["cache_write_per_1m"] / TOKENS_PER_MILLION
            + cache_read_tok * rates["cache_read_per_1m"] / TOKENS_PER_MILLION
        )

        savings = raw_cost - actual_cost

        return CostBreakdown(
            agent_name=agent_name,
            model=model,
            input_tokens=input_tok,
            output_tokens=output_tok,
            cache_write_tokens=cache_write_tok,
            cache_read_tokens=cache_read_tok,
            raw_cost_usd=round(raw_cost, 8),
            actual_cost_usd=round(actual_cost, 8),
            cache_savings_usd=round(savings, 8),
        )

    def accumulate(self, breakdown: CostBreakdown) -> None:
        """Add a breakdown to the running session total."""
        self._breakdowns.append(breakdown)

    def session_total(self) -> dict[str, float | int]:
        """Aggregate all accumulated breakdowns."""
        total_raw = sum(b.raw_cost_usd for b in self._breakdowns)
        total_actual = sum(b.actual_cost_usd for b in self._breakdowns)
        total_savings = sum(b.cache_savings_usd for b in self._breakdowns)
        savings_pct = (total_savings / total_raw * 100.0) if total_raw > 0 else 0.0
        return {
            "total_raw_usd": round(total_raw, 8),
            "total_actual_usd": round(total_actual, 8),
            "total_savings_usd": round(total_savings, 8),
            "savings_pct": round(savings_pct, 4),
            "event_count": len(self._breakdowns),
        }

    def write_session_report(self, output_path: str) -> None:
        """Write JSON session report to output_path."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "summary": self.session_total(),
            "breakdowns": [asdict(b) for b in self._breakdowns],
        }
        try:
            path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        except OSError as exc:
            _log.error("CostTracker.write_session_report failed: %s", exc)
