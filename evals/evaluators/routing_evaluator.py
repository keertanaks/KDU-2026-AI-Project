"""Routing logic evaluator — verify for_agent() and should_use_opus() correctness.

Default mode only (model_selector has no LLM calls).
"""

from __future__ import annotations

import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

import logging

from evals.metrics.collector import EvalMetrics

_log = logging.getLogger(__name__)

ROUTING_LOGIC_THRESHOLD: float = 1.0


@contextmanager
def _clean_env(*keys: str) -> Generator[None, None, None]:
    """Temporarily remove env vars to isolate routing logic tests."""
    saved: dict[str, str] = {}
    for key in keys:
        val = os.environ.pop(key, None)
        if val is not None:
            saved[key] = val
    try:
        yield
    finally:
        os.environ.update(saved)


class RoutingEvaluator:
    """Evaluate model routing logic using utils.model_selector."""

    def run_default(self) -> EvalMetrics:
        """Test for_agent() and should_use_opus() correctness. No LLM calls."""
        start = time.monotonic()
        failures: list[str] = []
        suite_name = "routing"
        eval_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        from utils.model_selector import for_agent, should_use_opus, Models

        results: list[bool] = []

        with _clean_env("OPENROUTER_API_KEY", "TEST_MODE"):
            results.extend(self._test_for_agent(for_agent, Models, failures))
            results.extend(self._test_should_use_opus(should_use_opus, failures))

        with _clean_env("OPENROUTER_API_KEY"):
            results.extend(self._test_test_mode(for_agent, Models, failures))

        routing_logic_pass_rate = sum(results) / len(results) if results else 0.0

        if routing_logic_pass_rate < ROUTING_LOGIC_THRESHOLD:
            failures.append(
                f"routing_logic_pass_rate={routing_logic_pass_rate:.3f} < {ROUTING_LOGIC_THRESHOLD}"
            )

        passed = routing_logic_pass_rate >= ROUTING_LOGIC_THRESHOLD

        return EvalMetrics(
            eval_id=eval_id,
            suite_name=suite_name,
            is_live=False,
            timestamp=timestamp,
            passed=passed,
            metrics={
                "routing_logic_pass_rate": routing_logic_pass_rate,
                "cases_tested": float(len(results)),
            },
            failures=failures,
            latency_ms=(time.monotonic() - start) * 1000,
        )

    @staticmethod
    def _test_for_agent(
        for_agent: Any, Models: Any, failures: list[str]
    ) -> list[bool]:
        """Verify for_agent() returns correct Anthropic model IDs (no OpenRouter, no TEST_MODE)."""
        cases: list[tuple[str, dict[str, Any], str]] = [
            ("prompt_parser default", {}, Models.HAIKU),
            ("catalog_selector default", {}, Models.HAIKU),
            ("layout_strategist default", {}, Models.SONNET),
            # Retry stays on Sonnet (Opus disabled — see model_selector.py)
            ("layout_strategist retry", {"is_retry": True}, Models.SONNET),
        ]
        agents_for_cases = [
            "prompt_parser",
            "catalog_selector",
            "layout_strategist",
            "layout_strategist",
        ]

        results: list[bool] = []
        for (desc, kwargs, expected), agent_name in zip(cases, agents_for_cases):
            try:
                actual = for_agent(agent_name, **kwargs)
                ok = actual == expected
                results.append(ok)
                if not ok:
                    failures.append(
                        f"for_agent({agent_name!r}, {kwargs}): expected {expected!r}, got {actual!r}"
                    )
            except Exception as exc:
                results.append(False)
                failures.append(f"for_agent({agent_name!r}, {kwargs}) raised: {exc}")

        # Unknown agent must raise ValueError
        try:
            for_agent("unknown_agent_xyz")
            results.append(False)
            failures.append("for_agent('unknown_agent_xyz') should raise ValueError but did not")
        except ValueError:
            results.append(True)
        except Exception as exc:
            results.append(False)
            failures.append(f"for_agent('unknown_agent_xyz') raised unexpected {type(exc).__name__}: {exc}")

        return results

    @staticmethod
    def _test_should_use_opus(should_use_opus: Any, failures: list[str]) -> list[bool]:
        """Verify should_use_opus() trigger logic."""
        cases: list[tuple[float, list[str], bool, str]] = [
            (0.70, [], False, "score=0.70, no violations → no retry"),
            (0.50, [], True, "score=0.50 < 0.60 → retry"),
            (0.59, [], True, "score=0.59 < 0.60 → retry"),
            (0.60, [], False, "score=0.60 (boundary, not < 0.60) → no retry"),
            (0.80, ["WORKFLOW-03"], True, "WORKFLOW-03 violated → retry"),
            (0.80, ["NKBA-CL-01"], True, "NKBA-CL-01 violated → retry"),
            (0.80, ["LAYOUT-06"], False, "non-critical violation → no retry"),
            (0.00, [], True, "score=0.0 → retry"),
            (1.00, [], False, "perfect score, no violations → no retry"),
            (0.50, ["WORKFLOW-03"], True, "low score + critical violation → retry"),
        ]

        results: list[bool] = []
        for score, violations, expected, desc in cases:
            try:
                actual = should_use_opus(score, violations)
                ok = actual == expected
                results.append(ok)
                if not ok:
                    failures.append(
                        f"should_use_opus({score}, {violations}): expected {expected}, got {actual} [{desc}]"
                    )
            except Exception as exc:
                results.append(False)
                failures.append(f"should_use_opus({score}, {violations}) raised: {exc} [{desc}]")

        return results

    @staticmethod
    def _test_test_mode(for_agent: Any, Models: Any, failures: list[str]) -> list[bool]:
        """When TEST_MODE=1, layout_strategist should downgrade to Haiku."""
        os.environ["TEST_MODE"] = "1"
        results: list[bool] = []
        try:
            actual = for_agent("layout_strategist")
            ok = actual == Models.HAIKU
            results.append(ok)
            if not ok:
                failures.append(
                    f"TEST_MODE=1: layout_strategist expected {Models.HAIKU!r}, got {actual!r}"
                )
        except Exception as exc:
            results.append(False)
            failures.append(f"TEST_MODE=1: layout_strategist raised: {exc}")
        finally:
            os.environ.pop("TEST_MODE", None)
        return results
