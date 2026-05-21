"""Agent 2 (CatalogSelector) evaluator.

Default mode: validates saved fixture outputs against zone/baseline/frontage rules.
Live mode: calls CatalogSelectorAgent (requires RUN_LIVE_LLM_EVALS=1).
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import logging

from evals.metrics.collector import EvalMetrics

_log = logging.getLogger(__name__)

BASELINE_GUARANTEE_THRESHOLD: float = 1.0
ZONE_COVERAGE_THRESHOLD: float = 0.85
MIN_FRONTAGE_MM: float = 4013.0
REQUIRED_ZONES: frozenset[str] = frozenset({"cooking", "cleaning", "cooling", "preparation", "storage"})
REQUIRED_BASELINE: list[str] = ["fridge", "sink", "stove", "hood"]
REQUIRED_NKBA_KEYS: frozenset[str] = frozenset({"min_aisle_mm", "work_triangle_min_mm"})


class Agent2Evaluator:
    """Evaluate Agent 2 (CatalogSelector) output quality."""

    def run_default(
        self, fixture_path: str = "evals/fixtures/agent2_fixtures.json"
    ) -> EvalMetrics:
        """Run CI-safe evaluation against saved fixtures. No LLM calls."""
        start = time.monotonic()
        failures: list[str] = []
        suite_name = "agent2"
        eval_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        fixtures = self._load_json(fixture_path)
        if fixtures is None:
            return self._error_metrics(suite_name, eval_id, timestamp, "Failed to load fixtures")

        zone_results: list[bool] = []
        baseline_results: list[bool] = []
        frontage_results: list[bool] = []
        constraints_results: list[bool] = []

        for fx in fixtures:
            tid = fx.get("test_id", "?")
            saved = fx.get("saved_output", {})

            zone_ok = self._check_zones(saved, tid, failures)
            zone_results.append(zone_ok)

            baseline_ok = self._check_baseline(saved, tid, failures)
            baseline_results.append(baseline_ok)

            frontage_ok = self._check_frontage(saved, tid, failures)
            frontage_results.append(frontage_ok)

            constraints_ok = self._check_nkba_constraints(saved, tid, failures)
            constraints_results.append(constraints_ok)

        zone_coverage_rate = sum(zone_results) / len(zone_results) if zone_results else 0.0
        baseline_guarantee_rate = (
            sum(baseline_results) / len(baseline_results) if baseline_results else 0.0
        )
        frontage_compliance_rate = (
            sum(frontage_results) / len(frontage_results) if frontage_results else 0.0
        )
        constraints_schema_ok = (
            sum(constraints_results) / len(constraints_results) if constraints_results else 0.0
        )

        if baseline_guarantee_rate < BASELINE_GUARANTEE_THRESHOLD:
            failures.append(
                f"baseline_guarantee_rate={baseline_guarantee_rate:.2f} < {BASELINE_GUARANTEE_THRESHOLD}"
            )
        if zone_coverage_rate < ZONE_COVERAGE_THRESHOLD:
            failures.append(
                f"zone_coverage_rate={zone_coverage_rate:.2f} < {ZONE_COVERAGE_THRESHOLD}"
            )

        passed = (
            baseline_guarantee_rate >= BASELINE_GUARANTEE_THRESHOLD
            and zone_coverage_rate >= ZONE_COVERAGE_THRESHOLD
        )

        return EvalMetrics(
            eval_id=eval_id,
            suite_name=suite_name,
            is_live=False,
            timestamp=timestamp,
            passed=passed,
            metrics={
                "zone_coverage_rate": zone_coverage_rate,
                "baseline_guarantee_rate": baseline_guarantee_rate,
                "frontage_compliance_rate": frontage_compliance_rate,
                "constraints_schema_ok": constraints_schema_ok,
            },
            failures=failures,
            latency_ms=(time.monotonic() - start) * 1000,
        )

    def run_live(
        self, dataset_path: str = "evals/datasets/agent2_eval_dataset.json"
    ) -> EvalMetrics:
        """Run live evaluation against CatalogSelectorAgent. Requires RUN_LIVE_LLM_EVALS=1."""
        import os
        if os.getenv("RUN_LIVE_LLM_EVALS") != "1":
            raise RuntimeError("Live evals require RUN_LIVE_LLM_EVALS=1")

        # Import inside run_live to avoid triggering LLM client initialization at module import
        import anthropic as _anthropic
        from agents.catalog_selector import CatalogSelector
        from pipeline.spatial_engine import SpatialEngine
        from dtos.contracts import IntentDTO

        start = time.monotonic()
        suite_name = "agent2_live"
        eval_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        failures: list[str] = []

        dataset = self._load_json(dataset_path)
        if dataset is None:
            return self._error_metrics(suite_name, eval_id, timestamp, "Failed to load dataset")

        import json as _json
        catalog_data = _json.loads(Path("catalog.json").read_text())
        mcp_catalog = {item["id"]: item for item in catalog_data}

        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        client = _anthropic.Anthropic(api_key=api_key)
        selector = CatalogSelector(client, mcp_catalog)
        spatial = SpatialEngine()

        zone_results: list[bool] = []
        baseline_results: list[bool] = []
        frontage_results: list[bool] = []

        for item in dataset:
            tid = item.get("test_id", "?")
            intent_data = item.get("intent_input", {})
            try:
                intent = IntentDTO(**{k: intent_data.get(k) for k in IntentDTO.__dataclass_fields__})
                input_json = {"environment": {"wall": [], "floor": {"points": []}}, "preferences": {}}
                spatial_out = spatial.parse(input_json)
                result = selector.select(intent, spatial_out)
                saved = {
                    "zone_groups": {
                        z: [s.sku_id for s in skus]
                        for z, skus in result.zone_groups.items()
                    },
                    "total_frontage_mm": sum(s.width_mm for skus in result.zone_groups.values() for s in skus),
                    "baseline_items_present": [
                        kw for kw in REQUIRED_BASELINE
                        if any(kw in s.name.lower() for skus in result.zone_groups.values() for s in skus)
                    ],
                    "nkba_constraints": {"min_aisle_mm": 1200, "work_triangle_min_mm": 3962},
                }
                zone_results.append(self._check_zones(saved, tid, failures))
                baseline_results.append(self._check_baseline(saved, tid, failures))
                frontage_results.append(self._check_frontage(saved, tid, failures))
            except Exception as exc:
                failures.append(f"{tid}: {exc}")

        zone_rate = sum(zone_results) / len(zone_results) if zone_results else 0.0
        baseline_rate = sum(baseline_results) / len(baseline_results) if baseline_results else 0.0
        frontage_rate = sum(frontage_results) / len(frontage_results) if frontage_results else 0.0

        return EvalMetrics(
            eval_id=eval_id,
            suite_name=suite_name,
            is_live=True,
            timestamp=timestamp,
            passed=len(failures) == 0 and baseline_rate >= 1.0 and zone_rate >= 0.85,
            metrics={
                "zone_coverage_rate": zone_rate,
                "baseline_guarantee_rate": baseline_rate,
                "frontage_compliance_rate": frontage_rate,
            },
            failures=failures,
            latency_ms=(time.monotonic() - start) * 1000,
        )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _check_zones(self, saved: dict[str, Any], tid: str, failures: list[str]) -> bool:
        zone_groups = saved.get("zone_groups", {})
        missing = [z for z in REQUIRED_ZONES if z not in zone_groups]
        if missing:
            failures.append(f"{tid}: missing zones {missing}")
            return False
        return True

    def _check_baseline(self, saved: dict[str, Any], tid: str, failures: list[str]) -> bool:
        baseline = saved.get("baseline_items_present", [])
        missing = [item for item in REQUIRED_BASELINE if item not in baseline]
        if missing:
            failures.append(f"{tid}: baseline missing {missing}")
            return False
        return True

    def _check_frontage(self, saved: dict[str, Any], tid: str, failures: list[str]) -> bool:
        frontage = saved.get("total_frontage_mm", 0)
        if not isinstance(frontage, (int, float)) or frontage < MIN_FRONTAGE_MM:
            failures.append(f"{tid}: total_frontage_mm={frontage} < {MIN_FRONTAGE_MM}")
            return False
        return True

    def _check_nkba_constraints(
        self, saved: dict[str, Any], tid: str, failures: list[str]
    ) -> bool:
        nkba = saved.get("nkba_constraints", {})
        missing = [k for k in REQUIRED_NKBA_KEYS if k not in nkba]
        if missing:
            failures.append(f"{tid}: nkba_constraints missing {missing}")
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
    def _error_metrics(suite_name: str, eval_id: str, timestamp: str, msg: str) -> EvalMetrics:
        return EvalMetrics(
            eval_id=eval_id, suite_name=suite_name, is_live=False,
            timestamp=timestamp, passed=False,
            metrics={"zone_coverage_rate": 0.0},
            failures=[msg], latency_ms=None,
        )
