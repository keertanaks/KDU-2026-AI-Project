"""Eval reporter — print human-readable summaries and write JSON reports.

print() is allowed in this module per project coding rules.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from evals.metrics.collector import EvalMetrics


class EvalReporter:
    """Format and output eval results."""

    def print_report(
        self,
        results: list[EvalMetrics],
        regression_report: object | None,
    ) -> None:
        """Print a readable table: suite | live? | passed | key metrics | vs baseline."""
        print("\n" + "=" * 80)
        print(f"{'Suite':<25} {'Live':^6} {'Pass':^6} {'Key Metric':<30} {'Status'}")
        print("-" * 80)

        has_regression = getattr(regression_report, "has_regression", False)

        for m in results:
            live_str = "YES" if m.is_live else "no"
            pass_str = "PASS" if m.passed else "FAIL"

            # Pick first non-None metric as the key metric to display
            key_metric_str = "--"
            for metric_name, metric_val in m.metrics.items():
                if metric_val is not None:
                    key_metric_str = f"{metric_name}={metric_val:.3f}"
                    break

            # Regression indicator
            status = ""
            if regression_report is not None:
                regressions = getattr(regression_report, "regressions", [])
                for reg in regressions:
                    if reg.get("suite") == m.suite_name:
                        status = "⚠ REGRESSION"
                        break

            print(f"{m.suite_name:<25} {live_str:^6} {pass_str:^6} {key_metric_str:<30} {status}")

        print("-" * 80)
        total = len(results)
        passed_count = sum(1 for m in results if m.passed)
        print(f"Passed: {passed_count}/{total}")

        if has_regression:
            print("\n⚠  REGRESSIONS DETECTED — see details below:")
            for reg in getattr(regression_report, "regressions", []):
                print(
                    f"  {reg.get('suite', '?')}.{reg.get('metric', '?')}: "
                    f"{reg.get('baseline', '?'):.4f} → {reg.get('current', '?'):.4f}"
                )
        print("=" * 80 + "\n")

    def write_json_report(self, results: list[EvalMetrics], path: str) -> None:
        """Write JSON array of all EvalMetrics to path."""
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            out_path.write_text(
                json.dumps([asdict(m) for m in results], indent=2), encoding="utf-8"
            )
        except OSError as exc:
            print(f"EvalReporter.write_json_report failed: {exc}")
