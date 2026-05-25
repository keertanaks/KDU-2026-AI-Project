"""Cost tracker evaluator — verify CostTracker arithmetic is correct.

Default mode only (pure math, no LLM calls).
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

import logging

from evals.metrics.collector import EvalMetrics
from llmops.cost_tracker import CostTracker, MODEL_COSTS, TOKENS_PER_MILLION

_log = logging.getLogger(__name__)

MATH_CORRECTNESS_THRESHOLD: float = 1.0
# Floating-point comparison tolerance
_FLOAT_TOLERANCE: float = 1e-9


def _approx_eq(a: float, b: float) -> bool:
    return abs(a - b) < _FLOAT_TOLERANCE


class CostEvaluator:
    """Evaluate CostTracker math correctness."""

    def run_default(self) -> EvalMetrics:
        """Verify cost calculation arithmetic. No LLM calls."""
        start = time.monotonic()
        failures: list[str] = []
        suite_name = "cost"
        eval_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        results: list[bool] = []
        results.extend(self._test_no_cache(failures))
        results.extend(self._test_with_cache(failures))
        results.extend(self._test_accumulate_session(failures))
        results.extend(self._test_unknown_model_fallback(failures))
        results.extend(self._test_savings_pct(failures))

        math_correctness_rate = sum(results) / len(results) if results else 0.0

        if math_correctness_rate < MATH_CORRECTNESS_THRESHOLD:
            failures.append(
                f"math_correctness_rate={math_correctness_rate:.3f} < {MATH_CORRECTNESS_THRESHOLD}"
            )

        passed = math_correctness_rate >= MATH_CORRECTNESS_THRESHOLD

        return EvalMetrics(
            eval_id=eval_id,
            suite_name=suite_name,
            is_live=False,
            timestamp=timestamp,
            passed=passed,
            metrics={
                "math_correctness_rate": math_correctness_rate,
                "cases_tested": float(len(results)),
            },
            failures=failures,
            latency_ms=(time.monotonic() - start) * 1000,
        )

    @staticmethod
    def _test_no_cache(failures: list[str]) -> list[bool]:
        """No cache tokens — raw_cost == actual_cost, savings == 0."""
        tracker = CostTracker()
        model = "claude-haiku-4-5-20251001"
        rates = MODEL_COSTS[model]
        usage = {"input_tokens": 1000, "output_tokens": 500}

        bd = tracker.from_usage("prompt_parser", model, usage)

        expected_raw = (1000 * rates["input_per_1m"] + 500 * rates["output_per_1m"]) / TOKENS_PER_MILLION
        expected_actual = expected_raw
        expected_savings = 0.0

        results: list[bool] = []

        ok_raw = _approx_eq(bd.raw_cost_usd, round(expected_raw, 8))
        results.append(ok_raw)
        if not ok_raw:
            failures.append(
                f"no_cache raw_cost: expected {round(expected_raw, 8)}, got {bd.raw_cost_usd}"
            )

        ok_actual = _approx_eq(bd.actual_cost_usd, round(expected_actual, 8))
        results.append(ok_actual)
        if not ok_actual:
            failures.append(
                f"no_cache actual_cost: expected {round(expected_actual, 8)}, got {bd.actual_cost_usd}"
            )

        ok_savings = _approx_eq(bd.cache_savings_usd, round(expected_savings, 8))
        results.append(ok_savings)
        if not ok_savings:
            failures.append(
                f"no_cache savings: expected 0.0, got {bd.cache_savings_usd}"
            )

        return results

    @staticmethod
    def _test_with_cache(failures: list[str]) -> list[bool]:
        """Cache read tokens reduce actual cost vs raw cost."""
        tracker = CostTracker()
        model = "claude-sonnet-4-6"
        rates = MODEL_COSTS[model]
        usage = {
            "input_tokens": 500,
            "output_tokens": 200,
            "cache_creation_input_tokens": 2000,
            "cache_read_input_tokens": 3000,
        }

        bd = tracker.from_usage("layout_strategist", model, usage)

        raw_input = 500 + 2000 + 3000
        expected_raw = (
            raw_input * rates["input_per_1m"] + 200 * rates["output_per_1m"]
        ) / TOKENS_PER_MILLION
        expected_actual = (
            500 * rates["input_per_1m"]
            + 200 * rates["output_per_1m"]
            + 2000 * rates["cache_write_per_1m"]
            + 3000 * rates["cache_read_per_1m"]
        ) / TOKENS_PER_MILLION
        expected_savings = expected_raw - expected_actual

        results: list[bool] = []

        ok_raw = _approx_eq(bd.raw_cost_usd, round(expected_raw, 8))
        results.append(ok_raw)
        if not ok_raw:
            failures.append(
                f"with_cache raw_cost: expected {round(expected_raw, 8)}, got {bd.raw_cost_usd}"
            )

        ok_actual = _approx_eq(bd.actual_cost_usd, round(expected_actual, 8))
        results.append(ok_actual)
        if not ok_actual:
            failures.append(
                f"with_cache actual_cost: expected {round(expected_actual, 8)}, got {bd.actual_cost_usd}"
            )

        ok_savings = _approx_eq(bd.cache_savings_usd, round(expected_savings, 8))
        results.append(ok_savings)
        if not ok_savings:
            failures.append(
                f"with_cache savings: expected {round(expected_savings, 8)}, got {bd.cache_savings_usd}"
            )

        # Savings must be positive when cache read > 0
        ok_positive = bd.cache_savings_usd > 0
        results.append(ok_positive)
        if not ok_positive:
            failures.append("with_cache: savings should be positive with cache_read tokens")

        return results

    @staticmethod
    def _test_accumulate_session(failures: list[str]) -> list[bool]:
        """accumulate() + session_total() sums multiple breakdowns correctly."""
        tracker = CostTracker()
        model_h = "claude-haiku-4-5-20251001"
        model_s = "claude-sonnet-4-6"

        bd1 = tracker.from_usage("agent1", model_h, {"input_tokens": 200, "output_tokens": 100})
        bd2 = tracker.from_usage("agent2", model_h, {"input_tokens": 300, "output_tokens": 150})
        bd3 = tracker.from_usage("agent3", model_s, {"input_tokens": 1000, "output_tokens": 400})

        tracker.accumulate(bd1)
        tracker.accumulate(bd2)
        tracker.accumulate(bd3)

        totals = tracker.session_total()
        results: list[bool] = []

        expected_raw = bd1.raw_cost_usd + bd2.raw_cost_usd + bd3.raw_cost_usd
        expected_actual = bd1.actual_cost_usd + bd2.actual_cost_usd + bd3.actual_cost_usd
        expected_savings = bd1.cache_savings_usd + bd2.cache_savings_usd + bd3.cache_savings_usd

        ok_raw = _approx_eq(totals["total_raw_usd"], round(expected_raw, 8))
        results.append(ok_raw)
        if not ok_raw:
            failures.append(f"session total_raw_usd: expected {round(expected_raw, 8)}, got {totals['total_raw_usd']}")

        ok_actual = _approx_eq(totals["total_actual_usd"], round(expected_actual, 8))
        results.append(ok_actual)
        if not ok_actual:
            failures.append(f"session total_actual_usd: expected {round(expected_actual, 8)}, got {totals['total_actual_usd']}")

        ok_count = totals["event_count"] == 3
        results.append(ok_count)
        if not ok_count:
            failures.append(f"session event_count: expected 3, got {totals['event_count']}")

        return results

    @staticmethod
    def _test_unknown_model_fallback(failures: list[str]) -> list[bool]:
        """Unknown model falls back to Sonnet rates without raising."""
        tracker = CostTracker()
        results: list[bool] = []
        try:
            bd = tracker.from_usage("some_agent", "completely-unknown-model-xyz", {"input_tokens": 100, "output_tokens": 50})
            # Should return valid CostBreakdown (non-negative costs)
            ok = bd.raw_cost_usd >= 0 and bd.actual_cost_usd >= 0
            results.append(ok)
            if not ok:
                failures.append("unknown_model: fallback returned negative cost")
        except Exception as exc:
            results.append(False)
            failures.append(f"unknown_model: should not raise, got {exc}")
        return results

    @staticmethod
    def _test_savings_pct(failures: list[str]) -> list[bool]:
        """savings_pct = (savings / raw) * 100."""
        tracker = CostTracker()
        model = "claude-opus-4-7"
        rates = MODEL_COSTS[model]
        usage = {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 5000,
        }

        bd = tracker.from_usage("agent3", model, usage)
        tracker.accumulate(bd)
        totals = tracker.session_total()

        raw = totals["total_raw_usd"]
        savings = totals["total_savings_usd"]
        expected_pct = round((savings / raw * 100.0) if raw > 0 else 0.0, 4)

        ok = _approx_eq(totals["savings_pct"], expected_pct)
        if not ok:
            failures.append(
                f"savings_pct: expected {expected_pct}, got {totals['savings_pct']}"
            )
        return [ok]
