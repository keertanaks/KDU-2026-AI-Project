"""Agent 3 (LayoutStrategist) evaluator.

Default mode: validates saved fixture outputs for semantic term validity.
Live mode: calls LayoutStrategist (requires RUN_LIVE_LLM_EVALS=1).
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import logging

from evals.metrics.collector import EvalMetrics

_log = logging.getLogger(__name__)

SEMANTIC_VALIDITY_THRESHOLD: float = 0.95
DETECTION_RATE_THRESHOLD: float = 1.0
ZONE_COMPLETENESS_THRESHOLD: float = 0.95

# Local copy of VALID_TERM_PATTERNS — duplicated from agents/layout_strategist.py
# (canonical copy maintained in llmops/guardrails.py) to keep this module CI-safe.
# agents.layout_strategist imports anthropic at module level, which would trigger
# LLM client initialisation and require ANTHROPIC_API_KEY in CI environments.
# Keep in sync when the agent semantic vocabulary changes.
_VALID_TERM_PATTERNS: list[str] = [
    r"at north-west corner",
    r"at north-east corner",
    r"at south-west corner",
    r"at south-east corner",
    r"near \w+ window",
    r"centre of \w+",
    r"left end of \w+",
    r"right end of \w+",
    r"next to [\w\s]+",
    r"above [\w\s]+",
    r"leave gap before [\w\s]+",
]


def _is_valid_term(term: str) -> bool:
    return any(re.fullmatch(p, term.strip(), re.IGNORECASE) for p in _VALID_TERM_PATTERNS)


class Agent3Evaluator:
    """Evaluate Agent 3 (LayoutStrategist) output quality."""

    def run_default(
        self, fixture_path: str = "evals/fixtures/agent3_fixtures.json"
    ) -> EvalMetrics:
        """Run CI-safe evaluation against saved fixtures. No LLM calls."""
        start = time.monotonic()
        failures: list[str] = []
        suite_name = "agent3"
        eval_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        fixtures = self._load_json(fixture_path)
        if fixtures is None:
            return self._error_metrics(suite_name, eval_id, timestamp, "Failed to load fixtures")

        # semantic_term_validity_rate: across hints in EXPECTED-VALID fixtures only
        valid_hint_count = 0
        total_hint_count = 0
        # detection_rate: among expected-invalid fixtures, how many are detected
        total_invalid_fixtures = 0
        detected_invalid_fixtures = 0
        # zone_completeness across ALL fixtures
        zoned_items = 0
        total_items = 0

        for fx in fixtures:
            tid = fx.get("test_id", "?")
            saved = fx.get("saved_output", {})
            expected = fx.get("expected", {})

            item_hints: dict[str, Any] = saved.get("item_hints", {}) if isinstance(saved, dict) else {}
            zone_assignments: dict[str, Any] = saved.get("zone_assignments", {}) if isinstance(saved, dict) else {}
            expected_all_valid: bool = expected.get("all_terms_valid", True) if isinstance(expected, dict) else True

            fixture_has_invalid = False
            for item_name, position in item_hints.items():
                if not isinstance(position, str):
                    continue
                term_valid = _is_valid_term(position)

                if expected_all_valid:
                    total_hint_count += 1
                    if term_valid:
                        valid_hint_count += 1
                    else:
                        failures.append(f"{tid}: unexpected invalid term '{position}' for '{item_name}'")

                if not term_valid:
                    fixture_has_invalid = True

            # Zone completeness (all fixtures)
            for item_name in item_hints:
                total_items += 1
                if item_name in zone_assignments:
                    zoned_items += 1
                else:
                    failures.append(f"{tid}: item '{item_name}' has no zone_assignment")

            # Detection: expected-invalid fixtures must be caught
            if not expected_all_valid:
                total_invalid_fixtures += 1
                if fixture_has_invalid:
                    detected_invalid_fixtures += 1
                else:
                    failures.append(f"{tid}: expected invalid terms but all terms were valid")

        semantic_term_validity_rate = (
            valid_hint_count / total_hint_count if total_hint_count else 0.0
        )
        detection_rate = (
            detected_invalid_fixtures / total_invalid_fixtures
            if total_invalid_fixtures else 1.0
        )
        zone_completeness_rate = zoned_items / total_items if total_items else 0.0

        if semantic_term_validity_rate < SEMANTIC_VALIDITY_THRESHOLD:
            failures.append(
                f"semantic_term_validity_rate={semantic_term_validity_rate:.3f} "
                f"< {SEMANTIC_VALIDITY_THRESHOLD}"
            )
        if detection_rate < DETECTION_RATE_THRESHOLD:
            failures.append(
                f"detection_rate={detection_rate:.3f} < {DETECTION_RATE_THRESHOLD}"
            )

        passed = (
            semantic_term_validity_rate >= SEMANTIC_VALIDITY_THRESHOLD
            and detection_rate >= DETECTION_RATE_THRESHOLD
        )

        return EvalMetrics(
            eval_id=eval_id,
            suite_name=suite_name,
            is_live=False,
            timestamp=timestamp,
            passed=passed,
            metrics={
                "semantic_term_validity_rate": semantic_term_validity_rate,
                "detection_rate": detection_rate,
                "zone_completeness_rate": zone_completeness_rate,
            },
            failures=failures,
            latency_ms=(time.monotonic() - start) * 1000,
        )

    def run_live(
        self, dataset_path: str = "evals/datasets/agent3_eval_dataset.json"
    ) -> EvalMetrics:
        """Run live evaluation against LayoutStrategist. Requires RUN_LIVE_LLM_EVALS=1."""
        import os
        if os.getenv("RUN_LIVE_LLM_EVALS") != "1":
            raise RuntimeError("Live evals require RUN_LIVE_LLM_EVALS=1")

        # Import inside run_live — agents.layout_strategist imports anthropic at module level
        import asyncio
        import anthropic as _anthropic
        from agents.layout_strategist import LayoutStrategist
        from dtos.contracts import IntentDTO, PreprocessingOutput
        from pipeline.spatial_engine import SpatialEngine

        start = time.monotonic()
        suite_name = "agent3_live"
        eval_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        failures: list[str] = []

        dataset = self._load_json(dataset_path)
        if dataset is None:
            return self._error_metrics(suite_name, eval_id, timestamp, "Failed to load dataset")

        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        client = _anthropic.Anthropic(api_key=api_key)
        strategist = LayoutStrategist(client)
        spatial_engine = SpatialEngine()

        total_hints = 0
        valid_hints = 0
        latencies: list[float] = []

        for item in dataset:
            tid = item.get("test_id", "?")
            room_input: dict[str, Any] = item.get("room_input", {})
            prefs: dict[str, Any] = room_input.get("preferences", {})
            try:
                spatial_out = spatial_engine.parse(room_input)
                intent = IntentDTO(
                    color_keyword=prefs.get("color_keyword"),
                    color_hex=None,
                    layout_family=prefs.get("layout_family"),
                    style=prefs.get("style"),
                    cabinet_preference=prefs.get("cabinet_preference"),
                    special_requests=prefs.get("special_requests", []),
                    ignored=prefs.get("ignored", []),
                    budget_tier=prefs.get("budget_tier", "mid"),
                    must_have=prefs.get("must_have", []),
                    avoid=prefs.get("avoid", []),
                )
                preprocessing = PreprocessingOutput(
                    intent=intent,
                    skus={},
                    zone_groups={},
                    zone_min_widths={},
                    nkba_constraints={},
                )
                t0 = time.monotonic()
                variants = asyncio.run(
                    strategist.run(intent, preprocessing, spatial_out, prefs)
                )
                latencies.append((time.monotonic() - t0) * 1000)
                for variant in variants:
                    hints: dict[str, Any] = getattr(variant, "item_hints", {}) or {}
                    for hint_val in hints.values():
                        # item_hints is nested: {"wall": "north_wall", "position": "at north-west corner"}
                        pos_str = (
                            hint_val.get("position", "") if isinstance(hint_val, dict)
                            else str(hint_val)
                        )
                        total_hints += 1
                        if _is_valid_term(pos_str):
                            valid_hints += 1
            except Exception as exc:
                failures.append(f"{tid}: {exc}")

        validity_rate = valid_hints / total_hints if total_hints else None
        mean_latency = sum(latencies) / len(latencies) if latencies else None

        return EvalMetrics(
            eval_id=eval_id,
            suite_name=suite_name,
            is_live=True,
            timestamp=timestamp,
            passed=len(failures) == 0 and (validity_rate or 0.0) >= SEMANTIC_VALIDITY_THRESHOLD,
            metrics={
                "semantic_term_validity_rate": validity_rate,
                "mean_latency_ms": mean_latency,
            },
            failures=failures,
            latency_ms=(time.monotonic() - start) * 1000,
        )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

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
            metrics={"semantic_term_validity_rate": 0.0},
            failures=[msg], latency_ms=None,
        )
