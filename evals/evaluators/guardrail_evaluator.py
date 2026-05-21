"""Guardrail evaluator — test that guardrails correctly flag bad inputs and outputs.

Default mode only (guardrails do not call LLMs).
Measures false_negative_rate: bad inputs that pass guardrails when they shouldn't.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

import logging

from evals.metrics.collector import EvalMetrics
from llmops.guardrails import run_all_guardrails

_log = logging.getLogger(__name__)

FALSE_NEGATIVE_THRESHOLD: float = 0.0


# ---------------------------------------------------------------------------
# Hardcoded test cases
# ---------------------------------------------------------------------------

_GOOD_INPUT: dict[str, Any] = {
    "environment": {
        "wall": [
            {
                "name": "north_wall",
                "anchor": "north",
                "thickness_mm": 100,
                "has_cabinets": True,
                "dimensions": {"length_mm": 3600, "height": 2700},
                "points": [],
            }
        ]
    },
    "preferences": {
        "budget_tier": "mid",
        "prompt": "Modern kitchen with white shaker cabinets",
    },
}

_GOOD_OUTPUT: dict[str, Any] = {
    "layouts": [
        {
            "id": "v1",
            "score": 0.85,
            "family": "L",
            "violations": [],
            "layout": {
                "north_wall": {"is_wall": True, "position_mm": {"x": 0, "y": 0, "z": 0}},
                "SKU-F01": {"is_wall": False, "product_id": "SKU-F01", "position_mm": {"x": 0, "y": 100, "z": 900}},
                "SKU-S01": {"is_wall": False, "product_id": "SKU-S01", "position_mm": {"x": 700, "y": 100, "z": 900}},
                "SKU-A01": {"is_wall": False, "product_id": "SKU-A01", "position_mm": {"x": 1300, "y": 100, "z": 900}},
                "SKU-B01": {"is_wall": False, "product_id": "SKU-B01", "position_mm": {"x": 1900, "y": 100, "z": 900}},
                "SKU-C01": {"is_wall": False, "product_id": "SKU-C01", "position_mm": {"x": 2500, "y": 100, "z": 900}},
            },
        }
    ]
}

_GOOD_HINTS: dict[str, str] = {
    "fridge": "at north-west corner",
    "sink": "centre of north_wall",
    "stove": "right end of east_wall",
    "dishwasher": "next to sink",
    "hood": "above stove",
}

# Each bad case: (input_json, item_hints, output_json, description, expected_fail_key)
# expected_fail_key is one of "input", "semantic", "output" — the guardrail that must fail.
_BAD_CASES: list[tuple[dict[str, Any] | None, dict[str, str] | None, dict[str, Any] | None, str, str]] = [
    # --- input guardrail failures ---
    (
        {"environment": {"wall": []}, "preferences": {"prompt": "test"}},
        None, None,
        "empty_walls", "input",
    ),
    (
        {
            "environment": {"wall": [{"name": "n", "dimensions": {"length_mm": 3000}, "has_cabinets": True}]},
            "preferences": {"budget_tier": "ultra", "prompt": "test"},
        },
        None, None,
        "invalid_budget_tier", "input",
    ),
    (
        {
            "environment": {"wall": [{"name": "n", "dimensions": {"length_mm": 3000}, "has_cabinets": True}]},
            "preferences": {},
        },
        None, None,
        "missing_prompt", "input",
    ),
    # --- output guardrail failures ---
    (
        None, None,
        {"request_id": "x"},
        "no_layouts", "output",
    ),
    (
        None, None,
        {
            "layouts": [{
                "id": "v1", "score": 0.85, "layout": {
                    "SKU-001": {"is_wall": False, "product_id": "SKU-001", "position_mm": {"x": 0, "y": 0}},
                }
            }]
        },
        "item_missing_z", "output",
    ),
    # --- semantic guardrail failures ---
    (
        None,
        {"fridge": "in the middle", "sink": "left end of north_wall"},
        None,
        "invalid_semantic_term", "semantic",
    ),
]


class GuardrailEvaluator:
    """Evaluate guardrail correctness using hardcoded bad/good inputs."""

    def run_default(self) -> EvalMetrics:
        """Run guardrail logic tests. No LLM calls."""
        start = time.monotonic()
        failures: list[str] = []
        suite_name = "guardrails"
        eval_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        false_negatives = 0
        total_bad = len(_BAD_CASES)

        for inp, hints, out, desc, expected_fail_key in _BAD_CASES:
            results = run_all_guardrails(input_json=inp, item_hints=hints, output_json=out)
            result = results.get(expected_fail_key)

            if result is None:
                false_negatives += 1
                failures.append(f"{desc}: guardrail '{expected_fail_key}' did not run")
                continue

            if result.passed:
                false_negatives += 1
                violations_str = ", ".join(v.rule_id for v in result.violations)
                failures.append(
                    f"{desc}: expected guardrail '{expected_fail_key}' to fail "
                    f"(violations={violations_str or 'none'})"
                )

        # Good-case false-positive check (informational — does not affect pass/fail)
        false_positives = 0
        good_cases: list[tuple[dict[str, Any] | None, dict[str, str] | None, dict[str, Any] | None, str]] = [
            (_GOOD_INPUT, None, None, "good_input"),
            (None, None, _GOOD_OUTPUT, "good_output"),
            (None, _GOOD_HINTS, None, "good_hints"),
        ]
        for inp, hints, out, desc in good_cases:
            results = run_all_guardrails(input_json=inp, item_hints=hints, output_json=out)
            for key, result in results.items():
                if not result.passed:
                    false_positives += 1
                    violations_str = ", ".join(v.rule_id for v in result.violations if v.severity == "error")
                    failures.append(f"{desc}: unexpected {key} guardrail failure ({violations_str})")

        false_negative_rate = false_negatives / total_bad if total_bad else 0.0
        false_positive_rate = false_positives / len(good_cases) if good_cases else 0.0

        if false_negative_rate > FALSE_NEGATIVE_THRESHOLD:
            failures.append(
                f"false_negative_rate={false_negative_rate:.3f} > {FALSE_NEGATIVE_THRESHOLD}"
            )

        passed = false_negative_rate <= FALSE_NEGATIVE_THRESHOLD

        return EvalMetrics(
            eval_id=eval_id,
            suite_name=suite_name,
            is_live=False,
            timestamp=timestamp,
            passed=passed,
            metrics={
                "false_negative_rate": false_negative_rate,
                "false_positive_rate": false_positive_rate,
                "bad_cases_tested": float(total_bad),
            },
            failures=failures,
            latency_ms=(time.monotonic() - start) * 1000,
        )
