"""Run Phase 5A PHI-safe offline retrieval evaluation."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / "config" / ".env")

from app.evaluation.ragas_eval import (  # noqa: E402
    evaluate_retrieval,
    load_golden_set,
    write_report_json,
    write_report_markdown,
)
from app.ingestion.embedder import Embedder  # noqa: E402
from app.search.graph import MIN_RERANK_SCORE  # noqa: E402
from app.search.reranker import Reranker  # noqa: E402
from app.search.retriever import HybridRetriever  # noqa: E402


class LocalRetrievalBenchmark:
    """
    Retrieval-only benchmark using the same embedder, hybrid retriever, and
    reranker as runtime search. It does not call answer generation or external
    evaluator LLMs.
    """

    def __init__(self, acl_labels: List[str] | None = None):
        self.embedder = Embedder()
        self.retriever = HybridRetriever()
        self.reranker = Reranker()
        self.acl_labels = acl_labels or ["admin_only", "dept_cardiology", "research_allowed"]

    def __call__(self, question: str, row: Dict[str, Any]) -> Dict[str, Any]:
        started = time.perf_counter()
        normalized_query = question.strip().lower()
        query_embedding = self.embedder.embed_batch([normalized_query])[0]

        candidates = self.retriever.retrieve(
            query_embedding,
            normalized_query,
            filters={"acl": self.acl_labels},
            k=50,
        )
        reranked = self.reranker.rerank(normalized_query, candidates, top_n=5)
        filtered = [hit for hit in reranked if hit.get("rerank_score", 0) >= MIN_RERANK_SCORE]
        if not filtered:
            filtered = reranked[:1]

        retrieved_doc_ids = [
            hit.get("_source", {}).get("doc_id", "")
            for hit in filtered
        ]
        latency_ms = int((time.perf_counter() - started) * 1000)

        return {
            "retrieved_doc_ids": retrieved_doc_ids,
            "latency_ms": latency_ms,
            "candidate_count": len(candidates),
            "reranked_count": len(filtered),
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run local PHI-safe Phase 5A retrieval evaluation.",
    )
    parser.add_argument(
        "--golden",
        default="evaluation/golden_set.jsonl",
        help="Path to JSONL golden set.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Evaluate only the first N golden rows.",
    )
    parser.add_argument(
        "--output-dir",
        default="evaluation/reports",
        help="Directory for latest.json and latest.md reports.",
    )
    parser.add_argument(
        "--no-answer-generation",
        action="store_true",
        help="Accepted for clarity; Phase 5A never calls answer generation.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    rows = load_golden_set(ROOT / args.golden)
    if args.limit is not None:
        rows = rows[: args.limit]

    benchmark = LocalRetrievalBenchmark()
    report = evaluate_retrieval(rows, benchmark)
    report = {
        **report,
        "run_config": {
            "golden_path": args.golden,
            "limit": args.limit,
            "embedding_provider": os.getenv("EMBEDDING_PROVIDER", "openai"),
            "opensearch_index": benchmark.retriever.index_name,
            "answer_generation": "disabled",
            "external_evaluator_llm": "disabled",
        },
    }

    output_dir = ROOT / args.output_dir
    json_path = write_report_json(report, output_dir / "latest.json")
    md_path = write_report_markdown(report, output_dir / "latest.md")

    metrics = report["metrics"]
    print("Phase 5A retrieval evaluation complete")
    print(f"Golden rows: {metrics['total_questions']}")
    print(f"Top-1 accuracy: {metrics['top_1_accuracy'] * 100:.1f}%")
    print(f"Top-3 accuracy: {metrics['top_3_accuracy'] * 100:.1f}%")
    print(f"Top-5 accuracy: {metrics['top_5_accuracy'] * 100:.1f}%")
    print(f"MRR: {metrics['mrr']:.3f}")
    print(f"Avg latency: {metrics['avg_latency_ms']:.1f} ms")
    print(f"P95 latency: {metrics['p95_latency_ms']:.1f} ms")
    print(f"Failures by doc_type: {metrics['failures_by_doc_type']}")
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {md_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
