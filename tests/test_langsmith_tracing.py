import importlib
import json
import os

import pytest

from app.observability.langsmith_tracer import (
    LangSmithTracer,
    hash_filename,
    hash_text,
)


class RecordingClient:
    def __init__(self):
        self.calls = []

    def create_run(self, **kwargs):
        self.calls.append(kwargs)


def _payload(client: RecordingClient) -> dict:
    assert len(client.calls) == 1
    return client.calls[0]["inputs"]


def test_search_trace_hashes_query_and_never_sends_raw_query():
    client = RecordingClient()
    tracer = LangSmithTracer(client=client, enabled=True)
    raw_query = "Show Emily Moore MRN100003 asthma notes"

    tracer.trace_search(
        query_text=raw_query,
        role="treating_clinician",
        doc_ids=["doc-source-1"],
        masking_applied="none",
        result_count=1,
        search_latency_ms=25,
        answer_latency_ms=10,
        total_latency_ms=35,
        answer_status="success",
        candidate_count=12,
        reranked_count=3,
        masked_result_count=3,
        acl_label_count=2,
        step_timings_ms={"retrieve": 8, "rerank": 4},
    )

    inputs = _payload(client)
    serialized = json.dumps(inputs, sort_keys=True)
    assert client.calls[0]["run_type"] == "chain"
    assert inputs["query_hash"] == hash_text(raw_query)
    assert "query_text" not in inputs
    assert raw_query not in serialized
    assert "Emily Moore" not in serialized
    assert "MRN100003" not in serialized
    assert inputs["source_doc_ids"] == ["doc-source-1"]


def test_ingest_trace_hashes_filename_and_never_sends_file_or_patient_content():
    client = RecordingClient()
    tracer = LangSmithTracer(client=client, enabled=True)
    filename = "Emily_Moore_MRN100003.pdf"

    tracer.trace_ingest(
        filename=filename,
        doc_id="doc-123",
        doc_type="typed",
        ocr_method="PyMuPDF",
        ocr_success_rate=0.99,
        raw_char_count=1800,
        cleaned_char_count=1725,
        normalization_applied=True,
        quality_score=0.93,
        needs_review=False,
        table_count=2,
        chunk_count=5,
        chunk_char_min=120,
        chunk_char_max=640,
        chunk_char_avg=344.5,
        phi_span_count=4,
        phi_type_counts={"PERSON": 2, "MRN": 1, "DATE_TIME": 1},
        indexed_count=5,
        latency_ms=450,
        step_timings_ms={"ocr_extract": 80, "chunk": 4, "index": 25},
    )

    inputs = _payload(client)
    serialized = json.dumps(inputs, sort_keys=True)
    assert inputs["filename_hash"] == hash_filename(filename)
    assert "filename" not in inputs
    assert filename not in serialized
    assert "Emily" not in serialized
    assert "Moore" not in serialized
    assert "MRN100003" not in serialized
    assert "ocr_text" not in serialized
    assert "chunk_text" not in serialized
    assert inputs["doc_id"] == "doc-123"
    assert inputs["chunk_count"] == 5


def test_error_trace_uses_category_without_exception_message():
    client = RecordingClient()
    tracer = LangSmithTracer(client=client, enabled=True)
    sensitive_message = "Tesseract failed while reading Emily Moore MRN100003"

    tracer.trace_ingest(
        filename="Emily_Moore_MRN100003.pdf",
        doc_id="doc-err",
        doc_type="handwritten",
        ocr_method=None,
        ocr_success_rate=None,
        raw_char_count=None,
        cleaned_char_count=None,
        normalization_applied=None,
        quality_score=None,
        needs_review=None,
        table_count=None,
        chunk_count=None,
        chunk_char_min=None,
        chunk_char_max=None,
        chunk_char_avg=None,
        phi_span_count=None,
        phi_type_counts=None,
        indexed_count=None,
        latency_ms=12,
        error_category="TesseractNotFoundError",
    )

    serialized = json.dumps(_payload(client), sort_keys=True)
    assert "TesseractNotFoundError" in serialized
    assert sensitive_message not in serialized
    assert "Emily Moore" not in serialized
    assert "MRN100003" not in serialized


def test_unsafe_trace_keys_are_rejected_before_submission():
    client = RecordingClient()
    tracer = LangSmithTracer(client=client, enabled=True)

    with pytest.raises(ValueError):
        tracer._create_run("bad_trace", {"raw_text": "Patient Emily Moore"})

    assert client.calls == []


def test_config_forces_automatic_langchain_tracing_off(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")

    import app.config as config

    importlib.reload(config)
    assert os.environ["LANGCHAIN_TRACING_V2"] == "false"
