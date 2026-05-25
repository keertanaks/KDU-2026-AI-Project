"""Routing analytics — log and analyse model selection events.

Records which model was chosen for each agent call, retry reasons, and scores.
Used for post-hoc analysis; does NOT affect live routing decisions.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import logging

_log = logging.getLogger(__name__)

ROUTING_LOG_PATH = "eval_results/routing_log.jsonl"


@dataclass
class RoutingEvent:
    event_id: str
    timestamp: str
    agent_name: str
    model_selected: str
    is_retry: bool
    retry_reason: str | None
    input_tokens: int | None
    output_tokens: int | None
    resulting_score: float | None
    variant_id: str | None


class RoutingAnalytics:
    """Log and analyse routing events."""

    def log_event(self, event: RoutingEvent) -> None:
        """Append event to eval_results/routing_log.jsonl (one JSON object per line)."""
        log_path = Path(ROUTING_LOG_PATH)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(event)) + "\n")
        except OSError as exc:
            _log.error("RoutingAnalytics.log_event failed: %s", exc)

    def load_events(self, from_date: str | None = None) -> list[RoutingEvent]:
        """Load all routing events, optionally filtering by ISO date prefix."""
        log_path = Path(ROUTING_LOG_PATH)
        if not log_path.exists():
            return []
        events: list[RoutingEvent] = []
        try:
            with log_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    data: dict[str, Any] = json.loads(line)
                    if from_date and not data.get("timestamp", "").startswith(from_date):
                        continue
                    events.append(
                        RoutingEvent(**{k: data.get(k) for k in RoutingEvent.__dataclass_fields__})
                    )
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            _log.warning("Failed to load routing log: %s", exc)
        return events

    def summarize(self) -> dict[str, Any]:
        """Compute aggregate statistics from all logged routing events."""
        events = self.load_events()
        if not events:
            return {
                "total_events": 0,
                "model_distribution": {},
                "retry_rate": 0.0,
                "mean_score_by_model": {},
                "opus_improvement_delta": None,
            }

        total = len(events)
        model_counts: dict[str, int] = {}
        retry_count = 0
        scores_by_model: dict[str, list[float]] = {}

        for ev in events:
            model_counts[ev.model_selected] = model_counts.get(ev.model_selected, 0) + 1
            if ev.is_retry:
                retry_count += 1
            if ev.resulting_score is not None:
                scores_by_model.setdefault(ev.model_selected, []).append(ev.resulting_score)

        model_distribution = {m: count / total for m, count in model_counts.items()}
        mean_score_by_model: dict[str, float | None] = {
            m: sum(scores) / len(scores) if scores else None
            for m, scores in scores_by_model.items()
        }

        opus_delta: float | None = None
        sonnet_scores = scores_by_model.get("claude-sonnet-4-6", [])
        opus_scores = scores_by_model.get("claude-opus-4-7", [])
        if sonnet_scores and opus_scores:
            opus_delta = (sum(opus_scores) / len(opus_scores)) - (
                sum(sonnet_scores) / len(sonnet_scores)
            )

        return {
            "total_events": total,
            "model_distribution": model_distribution,
            "retry_rate": retry_count / total,
            "mean_score_by_model": mean_score_by_model,
            "opus_improvement_delta": opus_delta,
        }

    def print_summary(self) -> None:
        """Print routing summary table to stdout (print allowed here per coding rules)."""
        summary = self.summarize()
        print("\n=== Routing Analytics Summary ===")
        print(f"Total events : {summary['total_events']}")
        print(f"Retry rate   : {summary['retry_rate']:.1%}")
        print("\nModel distribution:")
        for model, pct in summary["model_distribution"].items():
            print(f"  {model:<40} {pct:.1%}")
        print("\nMean score by model:")
        for model, score in summary["mean_score_by_model"].items():
            score_str = f"{score:.3f}" if score is not None else "N/A"
            print(f"  {model:<40} {score_str}")
        if summary["opus_improvement_delta"] is not None:
            print(f"\nOpus improvement delta: {summary['opus_improvement_delta']:+.3f}")
        print()
