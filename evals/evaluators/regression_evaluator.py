"""Regression evaluator — compare current eval metrics against a saved baseline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import logging

from evals.metrics.collector import EvalMetrics

_log = logging.getLogger(__name__)

# Tolerance: 5% change triggers a regression/improvement flag
REGRESSION_TOLERANCE: float = 0.05

# Metric names where LOWER is better
LOWER_IS_BETTER: frozenset[str] = frozenset({
    "latency_ms", "null_position_rate", "pipeline_duration_ms", "mean_latency_ms",
})


@dataclass
class RegressionReport:
    regressions: list[dict[str, Any]]
    improvements: list[dict[str, Any]]
    unchanged: list[str]
    has_regression: bool


class RegressionEvaluator:
    """Compare current eval metrics against a saved baseline."""

    def run(
        self,
        current: list[EvalMetrics],
        baseline: dict[str, EvalMetrics] | None,
    ) -> RegressionReport:
        """Detect regressions and improvements versus baseline.

        Returns empty RegressionReport (has_regression=False) if baseline is None.
        """
        if baseline is None:
            return RegressionReport(
                regressions=[], improvements=[], unchanged=[], has_regression=False
            )

        regressions: list[dict[str, Any]] = []
        improvements: list[dict[str, Any]] = []
        unchanged: list[str] = []

        for current_m in current:
            base_m = baseline.get(current_m.suite_name)
            if base_m is None:
                continue

            for metric_name, current_val in current_m.metrics.items():
                if current_val is None:
                    continue
                baseline_val = (base_m.metrics or {}).get(metric_name)
                if baseline_val is None:
                    continue

                key = f"{current_m.suite_name}.{metric_name}"
                delta = self._compute_regression(
                    metric_name, float(current_val), float(baseline_val)
                )

                if delta == "regression":
                    regressions.append({
                        "suite": current_m.suite_name,
                        "metric": metric_name,
                        "baseline": baseline_val,
                        "current": current_val,
                    })
                elif delta == "improvement":
                    improvements.append({
                        "suite": current_m.suite_name,
                        "metric": metric_name,
                        "baseline": baseline_val,
                        "current": current_val,
                    })
                else:
                    unchanged.append(key)

        return RegressionReport(
            regressions=regressions,
            improvements=improvements,
            unchanged=unchanged,
            has_regression=len(regressions) > 0,
        )

    @staticmethod
    def _compute_regression(
        metric_name: str, current: float, baseline: float
    ) -> str:
        """Return 'regression', 'improvement', or 'unchanged'."""
        if baseline == 0.0:
            return "unchanged"

        ratio = current / baseline
        lower_better = any(kw in metric_name for kw in LOWER_IS_BETTER)

        if lower_better:
            if ratio > 1.0 + REGRESSION_TOLERANCE:
                return "regression"
            if ratio < 1.0 - REGRESSION_TOLERANCE:
                return "improvement"
        else:
            if ratio < 1.0 - REGRESSION_TOLERANCE:
                return "regression"
            if ratio > 1.0 + REGRESSION_TOLERANCE:
                return "improvement"

        return "unchanged"
