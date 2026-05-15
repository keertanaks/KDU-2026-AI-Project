import json
import math

from app.evaluation.ragas_eval import (
    build_report,
    compute_latency_metrics,
    compute_mrr,
    compute_top_k_metrics,
    evaluate_retrieval,
    load_golden_set,
    write_report_json,
    write_report_markdown,
)


def _result(
    row_id,
    answerable=True,
    expected=None,
    retrieved=None,
    hit_rank=None,
    latency_ms=10,
    reason=None,
    doc_type="typed",
):
    return {
        "id": row_id,
        "doc_type": doc_type,
        "answerable": answerable,
        "expected_doc_ids": expected or [],
        "retrieved_doc_ids": retrieved or [],
        "hit_rank": hit_rank,
        "latency_ms": latency_ms,
        "reason": reason,
    }


def test_load_golden_set(tmp_path):
    path = tmp_path / "golden.jsonl"
    path.write_text(
        json.dumps(
            {
                "id": "q001",
                "question": "Which document mentions Metformin?",
                "expected_doc_ids": ["doc-1"],
                "ground_truth": "Expected doc-1.",
                "doc_type": "typed",
                "answerable": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    rows = load_golden_set(path)

    assert len(rows) == 1
    assert rows[0]["id"] == "q001"
    assert rows[0]["expected_doc_ids"] == ["doc-1"]


def test_top_k_metric_calculation():
    results = [
        _result("q1", expected=["doc-a"], retrieved=["doc-a"], hit_rank=1),
        _result("q2", expected=["doc-b"], retrieved=["doc-x", "doc-b"], hit_rank=2),
        _result("q3", expected=["doc-c"], retrieved=["doc-x"], hit_rank=None),
        _result("q4", answerable=False, retrieved=["doc-y"], reason="unanswerable_returned_results"),
    ]

    metrics = compute_top_k_metrics(results)

    assert metrics["top_1_accuracy"] == 1 / 3
    assert metrics["top_3_accuracy"] == 2 / 3
    assert metrics["top_5_accuracy"] == 2 / 3


def test_mrr_calculation():
    results = [
        _result("q1", expected=["doc-a"], retrieved=["doc-a"], hit_rank=1),
        _result("q2", expected=["doc-b"], retrieved=["doc-x", "doc-b"], hit_rank=2),
        _result("q3", expected=["doc-c"], retrieved=["doc-x"], hit_rank=None),
    ]

    assert math.isclose(compute_mrr(results), (1.0 + 0.5 + 0.0) / 3)


def test_latency_percentile_calculation():
    results = [
        _result("q1", latency_ms=10),
        _result("q2", latency_ms=20),
        _result("q3", latency_ms=30),
        _result("q4", latency_ms=40),
    ]

    metrics = compute_latency_metrics(results)

    assert metrics["avg_latency_ms"] == 25
    assert metrics["p95_latency_ms"] == 40


def test_report_generation(tmp_path):
    report = build_report(
        [
            _result("q1", expected=["doc-a"], retrieved=["doc-a"], hit_rank=1),
            _result(
                "q2",
                expected=["doc-b"],
                retrieved=["doc-x"],
                hit_rank=None,
                reason="expected_doc_not_retrieved",
            ),
        ]
    )

    json_path = write_report_json(report, tmp_path / "latest.json")
    md_path = write_report_markdown(report, tmp_path / "latest.md")

    assert json_path.exists()
    assert md_path.exists()
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded["metrics"]["total_questions"] == 2
    assert "expected_doc_not_retrieved" in md_path.read_text(encoding="utf-8")


def test_reports_do_not_contain_raw_retrieved_chunk_text(tmp_path):
    raw_chunk_text = "Patient John Smith presented with chest pain. MRN100001."
    result = _result("q1", expected=["doc-a"], retrieved=["doc-x"], hit_rank=None)
    result["raw_retrieved_chunk_text"] = raw_chunk_text

    report = build_report([result])
    json_path = write_report_json(report, tmp_path / "latest.json")
    md_path = write_report_markdown(report, tmp_path / "latest.md")

    assert raw_chunk_text not in json_path.read_text(encoding="utf-8")
    assert raw_chunk_text not in md_path.read_text(encoding="utf-8")
    assert "MRN100001" not in json_path.read_text(encoding="utf-8")
    assert "MRN100001" not in md_path.read_text(encoding="utf-8")


def test_unanswerable_queries_handled_safely():
    rows = [
        {
            "id": "q-unanswerable",
            "question": "Which record mentions an absent drug?",
            "expected_doc_ids": [],
            "ground_truth": "No indexed document is expected.",
            "doc_type": "unanswerable",
            "answerable": False,
        }
    ]

    report = evaluate_retrieval(
        rows,
        lambda question, row: {"retrieved_doc_ids": [], "latency_ms": 12},
    )

    assert report["metrics"]["unanswerable_questions"] == 1
    assert report["metrics"]["unanswerable_no_result_rate"] == 1.0
    assert report["failed_questions"] == []


def test_unanswerable_with_results_is_marked_failed():
    rows = [
        {
            "id": "q-unanswerable",
            "question": "Which record mentions an absent drug?",
            "expected_doc_ids": [],
            "ground_truth": "No indexed document is expected.",
            "doc_type": "unanswerable",
            "answerable": False,
        }
    ]

    report = evaluate_retrieval(
        rows,
        lambda question, row: {"retrieved_doc_ids": ["doc-a"], "latency_ms": 12},
    )

    assert report["metrics"]["unanswerable_returned_result_count"] == 1
    assert report["failed_questions"][0]["reason"] == "unanswerable_returned_results"
