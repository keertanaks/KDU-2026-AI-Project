"""End-to-end pipeline evaluator.

Default mode: validates saved fixture output against schema, score, and placement rules.
Live mode: runs the full KitchenGraph pipeline (requires RUN_LIVE_LLM_EVALS=1).
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

VARIANTS_ABOVE_THRESHOLD: float = 0.67
SCORE_THRESHOLD: float = 0.70
MIN_PLACEMENT_COUNT: int = 5
OUTPUT_SCHEMA_THRESHOLD: float = 1.0

REQUIRED_LAYOUT_FIELDS: frozenset[str] = frozenset({"id", "family", "score", "violations", "layout"})


class E2EEvaluator:
    """Evaluate full pipeline output quality."""

    def run_default(
        self, fixture_path: str = "evals/fixtures/e2e_fixture_output.json"
    ) -> EvalMetrics:
        """Run CI-safe evaluation against saved e2e fixture. No LLM calls."""
        start = time.monotonic()
        failures: list[str] = []
        suite_name = "e2e"
        eval_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        data = self._load_fixture(fixture_path)
        if data is None:
            return self._error_metrics(suite_name, eval_id, timestamp, "Failed to load fixture")

        layouts: list[dict[str, Any]] = data.get("layouts", []) if isinstance(data, dict) else []
        if not layouts:
            return self._error_metrics(suite_name, eval_id, timestamp, "No layouts in fixture")

        schema_results: list[bool] = []
        above_threshold: list[bool] = []
        nkba_present: list[bool] = []
        placement_ok: list[bool] = []
        null_position_items = 0
        total_placed_items = 0

        for variant in layouts:
            if not isinstance(variant, dict):
                continue
            v_id = variant.get("id", "<unknown>")

            # Schema check
            missing_fields = [f for f in REQUIRED_LAYOUT_FIELDS if f not in variant]
            schema_ok = len(missing_fields) == 0
            schema_results.append(schema_ok)
            if not schema_ok:
                failures.append(f"{v_id}: missing layout fields {missing_fields}")

            # Score threshold
            score = variant.get("score")
            if isinstance(score, (int, float)):
                above_threshold.append(score >= SCORE_THRESHOLD)
                if score < SCORE_THRESHOLD:
                    failures.append(f"{v_id}: score={score:.3f} < {SCORE_THRESHOLD}")
            else:
                above_threshold.append(False)
                failures.append(f"{v_id}: score missing or invalid")

            # NKBA compliance field
            nkba_present.append("nkba_compliance_pct" in variant)

            # Placement count
            placement_count = variant.get("placement_count")
            if placement_count is not None:
                placement_ok.append(int(placement_count) >= MIN_PLACEMENT_COUNT)
                if int(placement_count) < MIN_PLACEMENT_COUNT:
                    failures.append(f"{v_id}: placement_count={placement_count} < {MIN_PLACEMENT_COUNT}")
            else:
                placement_ok.append(False)
                failures.append(f"{v_id}: placement_count field missing")

            # Null position check
            layout_items: dict[str, Any] = variant.get("layout", {}) if isinstance(variant.get("layout"), dict) else {}
            for item_key, item_data in layout_items.items():
                if not isinstance(item_data, dict):
                    continue
                if item_data.get("is_wall") or item_data.get("is_floor") or item_data.get("is_door") or item_data.get("is_window"):
                    continue
                total_placed_items += 1
                pos = item_data.get("position_mm")
                if pos is None or not isinstance(pos, dict) or not all(k in pos for k in ("x", "y", "z")):
                    null_position_items += 1
                    failures.append(f"{v_id}.{item_key}: null or incomplete position_mm")

        output_schema_ok = sum(schema_results) / len(schema_results) if schema_results else 0.0
        variants_above_threshold = sum(above_threshold) / len(above_threshold) if above_threshold else 0.0
        nkba_field_present_rate = sum(nkba_present) / len(nkba_present) if nkba_present else 0.0
        placement_count_ok_rate = sum(placement_ok) / len(placement_ok) if placement_ok else 0.0
        null_position_rate = null_position_items / total_placed_items if total_placed_items else 0.0

        if output_schema_ok < OUTPUT_SCHEMA_THRESHOLD:
            failures.append(f"output_schema_ok={output_schema_ok:.2f} < {OUTPUT_SCHEMA_THRESHOLD}")
        if variants_above_threshold < VARIANTS_ABOVE_THRESHOLD:
            failures.append(f"variants_above_threshold={variants_above_threshold:.2f} < {VARIANTS_ABOVE_THRESHOLD}")

        passed = (
            output_schema_ok >= OUTPUT_SCHEMA_THRESHOLD
            and variants_above_threshold >= VARIANTS_ABOVE_THRESHOLD
        )

        return EvalMetrics(
            eval_id=eval_id,
            suite_name=suite_name,
            is_live=False,
            timestamp=timestamp,
            passed=passed,
            metrics={
                "output_schema_ok": output_schema_ok,
                "variants_above_threshold": variants_above_threshold,
                "nkba_field_present_rate": nkba_field_present_rate,
                "placement_count_ok_rate": placement_count_ok_rate,
                "null_position_rate": null_position_rate,
            },
            failures=failures,
            latency_ms=(time.monotonic() - start) * 1000,
        )

    def run_live(self) -> EvalMetrics:
        """Run live evaluation against KitchenGraph. Requires RUN_LIVE_LLM_EVALS=1."""
        import os
        if os.getenv("RUN_LIVE_LLM_EVALS") != "1":
            raise RuntimeError("Live evals require RUN_LIVE_LLM_EVALS=1")

        # Import inside run_live to avoid initialising LangGraph / Anthropic client at import time
        import anthropic as _anthropic
        from graph.kitchen_graph import KitchenGraph

        start = time.monotonic()
        suite_name = "e2e_live"
        eval_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        failures: list[str] = []

        test_inputs = self._load_test_inputs()
        if not test_inputs:
            return self._error_metrics(suite_name, eval_id, timestamp, "No test input files found")

        import asyncio

        client = _anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        graph = KitchenGraph(client)
        schema_results: list[bool] = []
        above_threshold_counts: list[float] = []
        null_position_rates: list[float] = []

        for input_name, input_json in test_inputs:
            try:
                final = asyncio.run(graph.run(input_json))
                layouts = getattr(final, "layouts", []) or []
                schema_ok_count = 0
                above_count = 0
                null_items = 0
                total_items = 0
                for variant in layouts:
                    v_dict = variant if isinstance(variant, dict) else (
                        vars(variant) if hasattr(variant, "__dict__") else {}
                    )
                    missing = [f for f in REQUIRED_LAYOUT_FIELDS if f not in v_dict]
                    if not missing:
                        schema_ok_count += 1
                    if (v_dict.get("score") or 0) >= SCORE_THRESHOLD:
                        above_count += 1
                    for item_val in (v_dict.get("layout") or {}).values():
                        if not isinstance(item_val, dict) or item_val.get("is_wall"):
                            continue
                        total_items += 1
                        pos = item_val.get("position_mm") or {}
                        if not all(k in pos for k in ("x", "y", "z")):
                            null_items += 1
                schema_results.append(schema_ok_count == len(layouts) and len(layouts) > 0)
                above_threshold_counts.append(above_count / len(layouts) if layouts else 0.0)
                null_position_rates.append(null_items / total_items if total_items else 0.0)
            except Exception as exc:
                failures.append(f"{input_name}: {exc}")

        output_schema_ok = sum(schema_results) / len(schema_results) if schema_results else 0.0
        variants_above = sum(above_threshold_counts) / len(above_threshold_counts) if above_threshold_counts else 0.0
        null_rate = sum(null_position_rates) / len(null_position_rates) if null_position_rates else 0.0

        return EvalMetrics(
            eval_id=eval_id,
            suite_name=suite_name,
            is_live=True,
            timestamp=timestamp,
            passed=len(failures) == 0 and output_schema_ok >= 1.0 and variants_above >= VARIANTS_ABOVE_THRESHOLD,
            metrics={
                "output_schema_ok": output_schema_ok,
                "variants_above_threshold": variants_above,
                "null_position_rate": null_rate,
                "pipeline_duration_ms": (time.monotonic() - start) * 1000,
            },
            failures=failures,
            latency_ms=(time.monotonic() - start) * 1000,
        )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _load_fixture(path: str) -> dict[str, Any] | None:
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _log.error("Failed to load %s: %s", path, exc)
            return None

    @staticmethod
    def _load_test_inputs() -> list[tuple[str, dict[str, Any]]]:
        inputs: list[tuple[str, dict[str, Any]]] = []
        for fname in ("input1.json", "input2.json", "input3.json"):
            p = Path(fname)
            if p.exists():
                try:
                    inputs.append((fname, json.loads(p.read_text(encoding="utf-8"))))
                except (OSError, json.JSONDecodeError):
                    pass
        return inputs

    @staticmethod
    def _error_metrics(suite_name: str, eval_id: str, timestamp: str, msg: str) -> EvalMetrics:
        return EvalMetrics(
            eval_id=eval_id, suite_name=suite_name, is_live=False,
            timestamp=timestamp, passed=False,
            metrics={"output_schema_ok": 0.0},
            failures=[msg], latency_ms=None,
        )
