"""Agent 1 (PromptParser) evaluator.

Default mode: validates saved fixture outputs against schema and expected values.
Live mode: calls PromptParserAgent with real prompts (requires RUN_LIVE_LLM_EVALS=1).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import logging

from evals.metrics.collector import EvalMetrics

_log = logging.getLogger(__name__)

SCHEMA_PASS_THRESHOLD: float = 1.0
FIELD_CONSISTENCY_THRESHOLD: float = 0.90
MIN_BUDGET_TIER_VALUES: int = 3
MIN_LAYOUT_FAMILY_VALUES: int = 2

VALID_BUDGET_TIERS: frozenset[str] = frozenset({"low", "mid", "high", "premium"})
VALID_LAYOUT_FAMILIES: frozenset[str] = frozenset({"L", "U", "I"})
VALID_CABINET_PREFS: frozenset[str] = frozenset({"base_only", "with_uppers", "with_tall"})
REQUIRED_FIELDS: list[str] = [
    "color_keyword", "color_hex", "layout_family", "style",
    "cabinet_preference", "special_requests", "ignored", "budget_tier",
]


class Agent1Evaluator:
    """Evaluate Agent 1 (PromptParser) output quality."""

    def run_default(
        self, fixture_path: str = "evals/fixtures/agent1_fixtures.json"
    ) -> EvalMetrics:
        """Run CI-safe evaluation against saved fixtures. No LLM calls."""
        start = time.monotonic()
        failures: list[str] = []
        suite_name = "agent1"
        eval_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        fixtures = self._load_json(fixture_path)
        if fixtures is None:
            return self._error_metrics(suite_name, eval_id, timestamp, "Failed to load fixtures")

        schema_results: list[bool] = []
        consistency_results: list[bool] = []
        budget_tiers_seen: set[str] = set()
        layout_families_seen: set[str] = set()

        for fx in fixtures:
            tid = fx.get("test_id", "?")
            saved = fx.get("saved_output", {})
            expected = fx.get("expected", {})

            # Schema check
            schema_ok = self._check_schema(saved, tid, failures)
            schema_results.append(schema_ok)

            # Enum coverage collection
            bt = saved.get("budget_tier")
            if bt in VALID_BUDGET_TIERS:
                budget_tiers_seen.add(bt)
            lf = saved.get("layout_family")
            if lf in VALID_LAYOUT_FAMILIES:
                layout_families_seen.add(lf)

            # Field consistency: saved_output matches expected non-null fields
            consistent = self._check_consistency(saved, expected, tid, failures)
            consistency_results.append(consistent)

        schema_pass_rate = sum(schema_results) / len(schema_results) if schema_results else 0.0
        consistency_rate = (
            sum(consistency_results) / len(consistency_results) if consistency_results else 0.0
        )
        enum_coverage_ok = (
            1.0
            if len(budget_tiers_seen) >= MIN_BUDGET_TIER_VALUES
            and len(layout_families_seen) >= MIN_LAYOUT_FAMILY_VALUES
            else 0.0
        )

        if schema_pass_rate < SCHEMA_PASS_THRESHOLD:
            failures.append(f"schema_pass_rate={schema_pass_rate:.2f} < {SCHEMA_PASS_THRESHOLD}")
        if consistency_rate < FIELD_CONSISTENCY_THRESHOLD:
            failures.append(
                f"field_consistency_rate={consistency_rate:.2f} < {FIELD_CONSISTENCY_THRESHOLD}"
            )

        passed = (
            schema_pass_rate >= SCHEMA_PASS_THRESHOLD
            and consistency_rate >= FIELD_CONSISTENCY_THRESHOLD
        )

        return EvalMetrics(
            eval_id=eval_id,
            suite_name=suite_name,
            is_live=False,
            timestamp=timestamp,
            passed=passed,
            metrics={
                "schema_pass_rate": schema_pass_rate,
                "field_consistency_rate": consistency_rate,
                "enum_coverage_ok": enum_coverage_ok,
            },
            failures=failures,
            latency_ms=(time.monotonic() - start) * 1000,
        )

    def run_live(
        self, dataset_path: str = "evals/datasets/agent1_eval_dataset.json"
    ) -> EvalMetrics:
        """Run live evaluation against PromptParserAgent. Requires RUN_LIVE_LLM_EVALS=1."""
        import os
        if os.getenv("RUN_LIVE_LLM_EVALS") != "1":
            raise RuntimeError("Live evals require RUN_LIVE_LLM_EVALS=1")

        # Import inside run_live to avoid triggering LLM client initialization at module import
        import anthropic as _anthropic  # noqa: F401
        from agents.prompt_parser import PromptParser

        start = time.monotonic()
        suite_name = "agent1_live"
        eval_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        failures: list[str] = []

        dataset = self._load_json(dataset_path)
        if dataset is None:
            return self._error_metrics(suite_name, eval_id, timestamp, "Failed to load dataset")

        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        client = _anthropic.Anthropic(api_key=api_key)
        parser = PromptParser(client)

        correct_fields = 0
        total_fields = 0
        color_correct = 0
        color_total = 0
        layout_correct = 0
        layout_total = 0
        latencies: list[float] = []

        for item in dataset:
            prompt_text: str = item.get("prompt", "")
            expected: dict[str, Any] = item.get("expected", {})
            prefs = {"prompt": prompt_text}
            t0 = time.monotonic()
            try:
                result = parser.parse(prefs)
            except Exception as exc:
                failures.append(f"parse failed for '{prompt_text[:40]}': {exc}")
                continue
            latencies.append((time.monotonic() - t0) * 1000)

            result_dict = {
                "color_keyword": result.color_keyword,
                "layout_family": result.layout_family,
                "style": result.style,
                "budget_tier": result.budget_tier,
                "cabinet_preference": result.cabinet_preference,
            }
            for field_name, exp_val in expected.items():
                if exp_val is None:
                    continue
                total_fields += 1
                if result_dict.get(field_name) == exp_val:
                    correct_fields += 1

            if "color_keyword" in expected and expected["color_keyword"] is not None:
                color_total += 1
                if result.color_keyword == expected["color_keyword"]:
                    color_correct += 1
            if "layout_family" in expected and expected["layout_family"] is not None:
                layout_total += 1
                if result.layout_family == expected["layout_family"]:
                    layout_correct += 1

        field_accuracy = correct_fields / total_fields if total_fields else None
        color_accuracy = color_correct / color_total if color_total else None
        layout_accuracy = layout_correct / layout_total if layout_total else None
        mean_latency = sum(latencies) / len(latencies) if latencies else None

        return EvalMetrics(
            eval_id=eval_id,
            suite_name=suite_name,
            is_live=True,
            timestamp=timestamp,
            passed=len(failures) == 0 and (field_accuracy or 0) >= 0.70,
            metrics={
                "field_accuracy": field_accuracy,
                "color_accuracy": color_accuracy,
                "layout_family_accuracy": layout_accuracy,
                "mean_latency_ms": mean_latency,
                "cache_hit_rate": None,
            },
            failures=failures,
            latency_ms=(time.monotonic() - start) * 1000,
        )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _check_schema(self, saved: dict[str, Any], tid: str, failures: list[str]) -> bool:
        """Return True if required fields are present with valid enum values."""
        ok = True
        for field_name in REQUIRED_FIELDS:
            if field_name not in saved:
                failures.append(f"{tid}: missing field '{field_name}'")
                ok = False

        bt = saved.get("budget_tier")
        if bt is not None and bt not in VALID_BUDGET_TIERS:
            failures.append(f"{tid}: budget_tier '{bt}' not in valid set")
            ok = False

        lf = saved.get("layout_family")
        if lf is not None and lf not in VALID_LAYOUT_FAMILIES:
            failures.append(f"{tid}: layout_family '{lf}' not in valid set")
            ok = False

        cp = saved.get("cabinet_preference")
        if cp is not None and cp not in VALID_CABINET_PREFS:
            failures.append(f"{tid}: cabinet_preference '{cp}' not in valid set")
            ok = False

        for list_field in ("special_requests", "ignored", "must_have", "avoid"):
            val = saved.get(list_field)
            if val is not None and not isinstance(val, list):
                failures.append(f"{tid}: field '{list_field}' should be a list")
                ok = False
        return ok

    def _check_consistency(
        self, saved: dict[str, Any], expected: dict[str, Any], tid: str, failures: list[str]
    ) -> bool:
        """Return True if saved matches all non-null expected fields."""
        for field_name, exp_val in expected.items():
            if exp_val is None:
                continue
            actual = saved.get(field_name)
            if actual != exp_val:
                failures.append(
                    f"{tid}: {field_name} expected={exp_val!r} actual={actual!r}"
                )
                return False
        return True

    @staticmethod
    def _load_json(path: str) -> list[dict[str, Any]] | None:
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _log.error("Failed to load %s: %s", path, exc)
            return None

    @staticmethod
    def _error_metrics(
        suite_name: str, eval_id: str, timestamp: str, msg: str
    ) -> EvalMetrics:
        return EvalMetrics(
            eval_id=eval_id, suite_name=suite_name, is_live=False,
            timestamp=timestamp, passed=False,
            metrics={"schema_pass_rate": 0.0},
            failures=[msg], latency_ms=None,
        )
