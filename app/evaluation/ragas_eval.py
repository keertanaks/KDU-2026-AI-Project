"""
PHI-safe offline retrieval evaluation for Phase 5A.

This module intentionally does not call RAGAS LLM metrics. It evaluates local
retrieval quality by comparing retrieved document IDs against a golden set.
Reports contain IDs, metrics, latencies, and failure reasons only; they never
write retrieved chunk text, generated answers, OCR text, prompts, or PHI maps.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence


GoldenRow = Dict[str, Any]
SearchResult = Dict[str, Any]
EvalResult = Dict[str, Any]


def load_golden_set(path: str | Path) -> List[GoldenRow]:
    """Load and minimally validate newline-delimited JSON golden rows."""
    rows: List[GoldenRow] = []
    input_path = Path(path)

    with input_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue

            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number}: {exc}") from exc

            _validate_golden_row(row, line_number)
            rows.append(row)

    return rows


def _validate_golden_row(row: GoldenRow, line_number: int) -> None:
    required = {"id", "question", "expected_doc_ids", "doc_type", "answerable"}
    missing = sorted(required - row.keys())
    if missing:
        raise ValueError(f"Golden row line {line_number} missing fields: {missing}")

    if not isinstance(row["id"], str) or not row["id"].strip():
        raise ValueError(f"Golden row line {line_number} has invalid id")

    if not isinstance(row["question"], str) or not row["question"].strip():
        raise ValueError(f"Golden row line {line_number} has invalid question")

    if not isinstance(row["expected_doc_ids"], list):
        raise ValueError(f"Golden row line {line_number} expected_doc_ids must be a list")

    if not all(isinstance(doc_id, str) for doc_id in row["expected_doc_ids"]):
        raise ValueError(f"Golden row line {line_number} expected_doc_ids must contain strings")

    if not isinstance(row["doc_type"], str) or not row["doc_type"].strip():
        raise ValueError(f"Golden row line {line_number} has invalid doc_type")

    if not isinstance(row["answerable"], bool):
        raise ValueError(f"Golden row line {line_number} answerable must be boolean")

    if row["answerable"] and not row["expected_doc_ids"]:
        raise ValueError(f"Golden row line {line_number} answerable rows need expected_doc_ids")


def evaluate_retrieval(
    golden_rows: Sequence[GoldenRow],
    search_fn: Callable[[str, GoldenRow], SearchResult],
) -> Dict[str, Any]:
    """
    Run the provided local search function over the golden set and compute metrics.

    search_fn receives (question, row) and should return:
        {
            "retrieved_doc_ids": ["doc-a", "doc-b"],
            "latency_ms": 123
        }
    """
    results: List[EvalResult] = []

    for row in golden_rows:
        retrieved_doc_ids: List[str] = []
        latency_ms = 0
        error: Optional[str] = None

        try:
            output = search_fn(row["question"], row)
            retrieved_doc_ids = _dedupe_doc_ids(output.get("retrieved_doc_ids", []))
            latency_ms = int(output.get("latency_ms", 0) or 0)
        except Exception as exc:  # pragma: no cover - exercised by callers/tests via reason
            error = exc.__class__.__name__

        hit_rank = _expected_hit_rank(row["expected_doc_ids"], retrieved_doc_ids)
        reason = _failure_reason(row, retrieved_doc_ids, hit_rank, error)

        results.append(
            {
                "id": row["id"],
                "doc_type": row["doc_type"],
                "answerable": row["answerable"],
                "expected_doc_ids": list(row["expected_doc_ids"]),
                "retrieved_doc_ids": retrieved_doc_ids[:5],
                "latency_ms": latency_ms,
                "hit_rank": hit_rank,
                "reason": reason,
            }
        )

    return build_report(results)


def compute_top_k_metrics(
    results: Sequence[EvalResult],
    k_values: Iterable[int] = (1, 3, 5),
) -> Dict[str, float]:
    """Compute top-k accuracy over answerable rows only."""
    answerable = [result for result in results if result.get("answerable")]
    total = len(answerable)
    metrics: Dict[str, float] = {}

    for k in k_values:
        hits = sum(
            1
            for result in answerable
            if result.get("hit_rank") is not None and int(result["hit_rank"]) <= k
        )
        metrics[f"top_{k}_accuracy"] = hits / total if total else 0.0

    return metrics


def compute_mrr(results: Sequence[EvalResult]) -> float:
    """Compute mean reciprocal rank over answerable rows only."""
    answerable = [result for result in results if result.get("answerable")]
    if not answerable:
        return 0.0

    reciprocal_ranks = [
        1.0 / int(result["hit_rank"])
        if result.get("hit_rank") is not None
        else 0.0
        for result in answerable
    ]
    return mean(reciprocal_ranks)


def compute_latency_metrics(results: Sequence[EvalResult]) -> Dict[str, float]:
    """Compute average and nearest-rank P95 latency."""
    latencies = [max(0, int(result.get("latency_ms", 0) or 0)) for result in results]
    if not latencies:
        return {"avg_latency_ms": 0.0, "p95_latency_ms": 0.0}

    sorted_latencies = sorted(latencies)
    p95_index = max(0, math.ceil(0.95 * len(sorted_latencies)) - 1)
    return {
        "avg_latency_ms": mean(sorted_latencies),
        "p95_latency_ms": float(sorted_latencies[p95_index]),
    }


def group_failures_by_doc_type(results: Sequence[EvalResult]) -> Dict[str, int]:
    """Group failed answerable/unanswerable checks by doc_type."""
    grouped: Dict[str, int] = {}
    for result in results:
        if not result.get("reason"):
            continue
        doc_type = str(result.get("doc_type", "unknown"))
        grouped[doc_type] = grouped.get(doc_type, 0) + 1
    return dict(sorted(grouped.items()))


def write_report_json(report: Dict[str, Any], output_path: str | Path) -> Path:
    """Write a PHI-safe JSON report."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_report_markdown(report: Dict[str, Any], output_path: str | Path) -> Path:
    """Write a PHI-safe Markdown report."""
    metrics = report.get("metrics", {})
    failures = report.get("failed_questions", [])
    lines = [
        "# Phase 5A Retrieval Evaluation",
        "",
        f"Generated at: `{report.get('generated_at', '')}`",
        "",
        "## Metrics",
        "",
        f"- Total questions: {metrics.get('total_questions', 0)}",
        f"- Answerable questions: {metrics.get('answerable_questions', 0)}",
        f"- Unanswerable questions: {metrics.get('unanswerable_questions', 0)}",
        f"- Top-1 accuracy: {_fmt_percent(metrics.get('top_1_accuracy', 0.0))}",
        f"- Top-3 accuracy: {_fmt_percent(metrics.get('top_3_accuracy', 0.0))}",
        f"- Top-5 accuracy: {_fmt_percent(metrics.get('top_5_accuracy', 0.0))}",
        f"- MRR: {metrics.get('mrr', 0.0):.3f}",
        f"- Avg latency: {metrics.get('avg_latency_ms', 0.0):.1f} ms",
        f"- P95 latency: {metrics.get('p95_latency_ms', 0.0):.1f} ms",
        f"- Unanswerable no-result rate: {_fmt_percent(metrics.get('unanswerable_no_result_rate', 0.0))}",
        "",
        "## Failures By Doc Type",
        "",
    ]

    failures_by_type = metrics.get("failures_by_doc_type", {})
    if failures_by_type:
        for doc_type, count in failures_by_type.items():
            lines.append(f"- {doc_type}: {count}")
    else:
        lines.append("- None")

    lines.extend(["", "## Failed Questions", ""])
    if failures:
        lines.extend(
            [
                "| id | doc_type | expected_doc_ids | retrieved_doc_ids | latency_ms | reason |",
                "|---|---|---|---|---:|---|",
            ]
        )
        for failure in failures:
            expected = ", ".join(failure.get("expected_doc_ids", []))
            retrieved = ", ".join(failure.get("retrieved_doc_ids", []))
            lines.append(
                "| {id} | {doc_type} | {expected} | {retrieved} | {latency_ms} | {reason} |".format(
                    id=failure.get("id", ""),
                    doc_type=failure.get("doc_type", ""),
                    expected=expected,
                    retrieved=retrieved,
                    latency_ms=failure.get("latency_ms", 0),
                    reason=failure.get("reason", ""),
                )
            )
    else:
        lines.append("No failed questions.")

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_report(results: Sequence[EvalResult], run_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build the complete PHI-safe report structure from per-question results."""
    top_k = compute_top_k_metrics(results)
    latency = compute_latency_metrics(results)
    answerable_count = sum(1 for result in results if result.get("answerable"))
    unanswerable = [result for result in results if not result.get("answerable")]
    unanswerable_no_result = sum(1 for result in unanswerable if not result.get("retrieved_doc_ids"))

    failed_questions = [
        {
            "id": result["id"],
            "doc_type": result["doc_type"],
            "expected_doc_ids": result["expected_doc_ids"],
            "retrieved_doc_ids": result["retrieved_doc_ids"],
            "latency_ms": result["latency_ms"],
            "reason": result["reason"],
        }
        for result in results
        if result.get("reason")
    ]

    metrics = {
        "total_questions": len(results),
        "answerable_questions": answerable_count,
        "unanswerable_questions": len(unanswerable),
        **top_k,
        "mrr": compute_mrr(results),
        **latency,
        "unanswerable_no_result_rate": (
            unanswerable_no_result / len(unanswerable) if unanswerable else 0.0
        ),
        "unanswerable_returned_result_count": len(unanswerable) - unanswerable_no_result,
        "failures_by_doc_type": group_failures_by_doc_type(results),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_config": run_config or {},
        "metrics": metrics,
        "failed_questions": failed_questions,
    }


def _dedupe_doc_ids(doc_ids: Iterable[Any]) -> List[str]:
    seen = set()
    unique: List[str] = []
    for raw_doc_id in doc_ids:
        doc_id = str(raw_doc_id or "").strip()
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)
        unique.append(doc_id)
    return unique


def _expected_hit_rank(expected_doc_ids: Sequence[str], retrieved_doc_ids: Sequence[str]) -> Optional[int]:
    expected = set(expected_doc_ids)
    for index, doc_id in enumerate(retrieved_doc_ids, start=1):
        if doc_id in expected:
            return index
    return None


def _failure_reason(
    row: GoldenRow,
    retrieved_doc_ids: Sequence[str],
    hit_rank: Optional[int],
    error: Optional[str],
) -> Optional[str]:
    if error:
        return f"search_error:{error}"

    if row["answerable"]:
        if hit_rank is None:
            return "expected_doc_not_retrieved"
        if hit_rank > 5:
            return "expected_doc_not_in_top_5"
        return None

    if retrieved_doc_ids:
        return "unanswerable_returned_results"
    return None


def _fmt_percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "0.0%"
