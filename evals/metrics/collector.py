"""Eval metrics collection — EvalMetrics dataclass and ResultStore."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import logging

_log = logging.getLogger(__name__)

RESULTS_DIR_DEFAULT = "eval_results"
BASELINE_FILENAME = "baseline.json"


@dataclass
class EvalMetrics:
    eval_id: str
    suite_name: str
    is_live: bool
    timestamp: str
    passed: bool
    metrics: dict[str, float | None]
    failures: list[str]
    latency_ms: float | None = None


class ResultStore:
    """Persist EvalMetrics to eval_results/."""

    RESULTS_DIR: str = RESULTS_DIR_DEFAULT

    def __init__(self, results_dir: str = RESULTS_DIR_DEFAULT) -> None:
        self._dir = Path(results_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, metrics: EvalMetrics) -> None:
        """Write eval_results/{suite_name}_{timestamp}.json."""
        safe_ts = metrics.timestamp.replace(":", "-").replace(" ", "_")
        filename = f"{metrics.suite_name}_{safe_ts}.json"
        path = self._dir / filename
        try:
            path.write_text(json.dumps(asdict(metrics), indent=2), encoding="utf-8")
        except OSError as exc:
            _log.error("ResultStore.save failed for %s: %s", filename, exc)

    def load_baseline(self) -> dict[str, EvalMetrics] | None:
        """Load eval_results/baseline.json. Returns None if not found."""
        path = self._dir / BASELINE_FILENAME
        if not path.exists():
            return None
        try:
            raw: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
            result: dict[str, EvalMetrics] = {}
            for item in raw:
                em = EvalMetrics(**{k: item.get(k) for k in EvalMetrics.__dataclass_fields__})
                result[em.suite_name] = em
            return result
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            _log.warning("Failed to load baseline: %s", exc)
            return None

    def save_baseline(self, all_metrics: list[EvalMetrics]) -> None:
        """Write eval_results/baseline.json from a list of EvalMetrics."""
        path = self._dir / BASELINE_FILENAME
        try:
            path.write_text(
                json.dumps([asdict(m) for m in all_metrics], indent=2), encoding="utf-8"
            )
        except OSError as exc:
            _log.error("ResultStore.save_baseline failed: %s", exc)
