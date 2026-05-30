# tests/test_extractor.py
#
# Project 3 — Phase 6: Unit tests for app/ingestion/extractor.ClinicalExtractor.
#
# Hard constraint (per CLAUDE.md "Never load the real 7B model in unit tests"):
#   - These tests MUST run with NO GPU and NO downloaded model weights.
#   - We mock both .model and .tokenizer entirely. _ensure_loaded() is patched
#     so it's a no-op; .extract() then runs against a fake tokenizer/model pair.
#   - If a CI runner ever sees this file try to download Qwen2.5-7B, that is a
#     regression — fix the mock, do not skip the test.

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.ingestion.extractor import ClinicalExtractor
from app.schemas.extraction import ExtractionResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Clear the module-level singleton before each test so env-var changes take effect."""
    ClinicalExtractor.reset_singleton()
    yield
    ClinicalExtractor.reset_singleton()


def _make_extractor_with_fake_model(generated_json: str) -> ClinicalExtractor:
    """Return a ClinicalExtractor whose .generate() will produce ``generated_json``.

    The fake tokenizer just echoes the input back; the fake model's .generate()
    returns a tensor-like object whose decode round-trips to ``generated_json``.
    Neither requires CUDA nor torch on disk — torch is imported only inside the
    real ._generate() path, which we bypass by monkey-patching that method.
    """
    ext = ClinicalExtractor(model=MagicMock(), tokenizer=MagicMock())
    # Bypass torch entirely by replacing _generate with a stub.
    # _generate signature is (text, record_id="") since remote-mode support landed.
    ext._generate = lambda text, record_id="": generated_json  # type: ignore[assignment]
    # _ensure_loaded is a no-op when model/tokenizer are already set.
    return ext


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_extract_returns_valid_result_when_model_emits_clean_json():
    payload = {
        "schema_version": "v1",
        "entities": [
            {
                "entity_type": "medication",
                "mention": "metformin",
                "dosage": "500 mg",
                "linked_medication": None,
                "evidence": "started on metformin 500 mg",
                "source_span": {"start_char": 11, "end_char": 20},
            }
        ],
        "relation_status": "not_related",
    }
    ext = _make_extractor_with_fake_model(json.dumps(payload))

    text = "Pt was started on metformin 500 mg today."
    result = ext.extract(text, record_id="chunk_001")

    assert isinstance(result, ExtractionResult)
    assert result.record_id == "chunk_001"
    assert result.schema_version == "v1"
    assert len(result.entities) == 1
    assert result.entities[0].entity_type == "medication"
    assert result.entities[0].mention == "metformin"
    assert result.validation.json_valid is True
    assert result.validation.schema_valid is True
    assert result.error_reason is None


def test_extract_populates_relations_when_status_related():
    payload = {
        "schema_version": "v1",
        "entities": [
            {
                "entity_type": "medication",
                "mention": "warfarin",
                "dosage": None,
                "linked_medication": None,
                "evidence": "started warfarin",
                "source_span": {"start_char": 0, "end_char": 8},
            },
            {
                "entity_type": "adverse_event",
                "mention": "bleeding",
                "dosage": None,
                "linked_medication": "warfarin",
                "evidence": "reports bleeding",
                "source_span": {"start_char": 30, "end_char": 38},
            },
        ],
        "relation_status": "related",
    }
    ext = _make_extractor_with_fake_model(json.dumps(payload))

    text = "warfarin started; pt reports bleeding episodes."
    result = ext.extract(text, record_id="chunk_002")

    assert result.relation_status == "related"
    # The .extract() method just returns ExtractionResult; the documents.py
    # caller builds the relations[] list from linked_medication. Verify the
    # adverse_event entity carries linked_medication correctly.
    ades = [e for e in result.entities if e.entity_type == "adverse_event"]
    assert ades[0].linked_medication == "warfarin"


# ---------------------------------------------------------------------------
# Failure paths — extractor must never crash the ingestion pipeline
# ---------------------------------------------------------------------------


def test_extract_returns_empty_result_when_extraction_disabled(monkeypatch):
    monkeypatch.setenv("EXTRACTION_ENABLED", "false")
    ext = ClinicalExtractor()  # re-read env vars

    result = ext.extract("Pt on aspirin.", record_id="chunk_003")

    assert result.error_reason == "extraction_disabled"
    assert result.entities == []
    assert result.validation.json_valid is False
    assert result.validation.schema_valid is False


def test_extract_returns_empty_result_for_empty_input():
    ext = _make_extractor_with_fake_model("{}")

    result = ext.extract("", record_id="chunk_004")

    assert result.error_reason == "empty_input"
    assert result.entities == []


def test_extract_returns_empty_result_when_model_emits_unparseable_text():
    # Model emits something json-repair can't salvage either.
    ext = _make_extractor_with_fake_model("this is definitely not JSON at all")

    result = ext.extract("Pt on lisinopril.", record_id="chunk_005")

    # validate_extraction decides between json_parse_failed and schema_invalid;
    # either way error_reason must be set and entities must be empty.
    assert result.error_reason in {"json_parse_failed", "schema_invalid"}
    assert result.entities == []
    assert result.validation.json_valid is False


def test_extract_returns_empty_result_on_oom():
    """A CUDA OOM (or any RuntimeError) from .generate() must NOT propagate."""
    ext = ClinicalExtractor(model=MagicMock(), tokenizer=MagicMock())

    def _boom(text, record_id=""):
        raise RuntimeError("CUDA out of memory")

    ext._generate = _boom  # type: ignore[assignment]

    result = ext.extract("Pt on metformin.", record_id="chunk_006")

    assert result.error_reason == "extraction_error"
    assert result.entities == []
    assert result.validation.json_valid is False


def test_extract_returns_empty_result_when_model_load_fails(monkeypatch):
    """If _ensure_loaded raises (missing adapter, bad path, no torch), degrade gracefully.

    Must run in LOCAL mode (no EXTRACTION_REMOTE_URL) so the _ensure_loaded code
    path is reached. In remote mode the extractor skips _ensure_loaded entirely.
    """
    monkeypatch.delenv("EXTRACTION_REMOTE_URL", raising=False)
    ext = ClinicalExtractor()  # no model/tokenizer injected

    with patch.object(
        ClinicalExtractor, "_ensure_loaded",
        side_effect=FileNotFoundError("adapter not found"),
    ):
        result = ext.extract("Pt on metformin.", record_id="chunk_007")

    assert result.error_reason == "model_load_failed"
    assert result.entities == []


def test_extract_returns_empty_result_when_schema_invalid():
    # Parseable JSON but missing required fields → schema_invalid.
    bogus = json.dumps({"schema_version": "v1", "entities": "not-a-list"})
    ext = _make_extractor_with_fake_model(bogus)

    result = ext.extract("Pt on metformin.", record_id="chunk_008")

    assert result.error_reason == "schema_invalid"
    assert result.entities == []


# ---------------------------------------------------------------------------
# Singleton + adapter_version
# ---------------------------------------------------------------------------


def test_get_returns_same_instance_across_calls():
    a = ClinicalExtractor.get()
    b = ClinicalExtractor.get()
    assert a is b


def test_adapter_version_when_enabled(monkeypatch):
    monkeypatch.setenv("EXTRACTION_ENABLED", "true")
    monkeypatch.setenv("EXTRACTION_ADAPTER_PATH", "models/adapters/lora_v1")
    # Must run in LOCAL mode — remote mode prefixes with "remote:" (tested separately)
    monkeypatch.delenv("EXTRACTION_REMOTE_URL", raising=False)
    ext = ClinicalExtractor()
    assert ext.adapter_version() == "lora_v1"


def test_adapter_version_when_disabled(monkeypatch):
    monkeypatch.setenv("EXTRACTION_ENABLED", "false")
    ext = ClinicalExtractor()
    assert ext.adapter_version() == "disabled"


# ---------------------------------------------------------------------------
# No real model is ever loaded in this test file — sanity assert
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Remote-mode tests (EXTRACTION_REMOTE_URL)
# ---------------------------------------------------------------------------


def test_remote_mode_posts_to_endpoint_and_parses_response(monkeypatch):
    """When EXTRACTION_REMOTE_URL is set, .extract() should HTTP POST and
    flow the returned raw_output through validate_extraction.
    """
    monkeypatch.setenv("EXTRACTION_REMOTE_URL", "https://fake.hf.space")
    payload = {
        "schema_version": "v1",
        "entities": [
            {
                "entity_type": "medication",
                "mention": "aspirin",
                "dosage": None,
                "linked_medication": None,
                "evidence": "started aspirin",
                "source_span": {"start_char": 0, "end_char": 7},
            }
        ],
        "relation_status": "not_related",
    }
    fake_response = MagicMock()
    fake_response.json.return_value = {"raw_output": json.dumps(payload)}
    fake_response.raise_for_status.return_value = None

    with patch("requests.post", return_value=fake_response) as mock_post:
        ext = ClinicalExtractor()
        result = ext.extract("Pt started aspirin today.", record_id="remote_001")

    # The remote endpoint URL must be constructed as <remote_url>/extract
    args, kwargs = mock_post.call_args
    assert args[0] == "https://fake.hf.space/extract"
    assert kwargs["json"]["text"] == "Pt started aspirin today."
    assert kwargs["json"]["record_id"] == "remote_001"

    assert result.record_id == "remote_001"
    assert len(result.entities) == 1
    assert result.entities[0].mention == "aspirin"
    assert result.validation.schema_valid is True
    assert result.error_reason is None


def test_remote_mode_strips_trailing_slash(monkeypatch):
    """EXTRACTION_REMOTE_URL=https://x.hf.space/ should not produce //extract."""
    monkeypatch.setenv("EXTRACTION_REMOTE_URL", "https://fake.hf.space/")
    ext = ClinicalExtractor()
    assert ext.remote_url == "https://fake.hf.space"


def test_remote_mode_network_error_returns_extraction_error(monkeypatch):
    """HTTP failures must not propagate — extract() should return empty result."""
    monkeypatch.setenv("EXTRACTION_REMOTE_URL", "https://fake.hf.space")
    import requests

    with patch("requests.post", side_effect=requests.ConnectionError("connection refused")):
        ext = ClinicalExtractor()
        result = ext.extract("Pt on metformin.", record_id="remote_002")

    assert result.error_reason == "extraction_error"
    assert result.entities == []


def test_remote_mode_malformed_response_returns_extraction_error(monkeypatch):
    """A remote that returns {'something_else': ...} (no raw_output key) must not crash."""
    monkeypatch.setenv("EXTRACTION_REMOTE_URL", "https://fake.hf.space")
    fake_response = MagicMock()
    fake_response.json.return_value = {"unexpected_shape": "yes"}
    fake_response.raise_for_status.return_value = None

    with patch("requests.post", return_value=fake_response):
        ext = ClinicalExtractor()
        result = ext.extract("Pt on metformin.", record_id="remote_003")

    assert result.error_reason == "extraction_error"
    assert result.entities == []


def test_remote_mode_skips_local_model_load(monkeypatch):
    """In remote mode, _ensure_loaded() must NOT be called — there's no local model to load."""
    monkeypatch.setenv("EXTRACTION_REMOTE_URL", "https://fake.hf.space")
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "raw_output": json.dumps({"schema_version": "v1", "entities": [], "relation_status": "none"})
    }
    fake_response.raise_for_status.return_value = None

    with patch("requests.post", return_value=fake_response), \
         patch.object(ClinicalExtractor, "_ensure_loaded") as mock_load:
        ext = ClinicalExtractor()
        ext.extract("Pt healthy.", record_id="remote_004")

    mock_load.assert_not_called()


def test_adapter_version_in_remote_mode(monkeypatch):
    """adapter_version() should prefix with 'remote:' when running in remote mode."""
    monkeypatch.setenv("EXTRACTION_ENABLED", "true")
    monkeypatch.setenv("EXTRACTION_REMOTE_URL", "https://fake.hf.space")
    monkeypatch.setenv("EXTRACTION_ADAPTER_PATH", "models/adapters/lora_v1")
    ext = ClinicalExtractor()
    assert ext.adapter_version() == "remote:lora_v1"


# ---------------------------------------------------------------------------
# Module hygiene
# ---------------------------------------------------------------------------


def test_no_real_model_is_imported_by_extractor_module():
    """The extractor module must not import torch/transformers at import time.

    Heavy imports are deferred to ._ensure_loaded(). If a future change pulls
    them up to the top of extractor.py, this test will fail.
    """
    import importlib
    import sys

    # Already imported above as a side-effect of these tests. The check that
    # matters is whether the module itself transitively eagerly imports torch
    # at module-load time. We allow torch to be present (it may be installed),
    # but the extractor module must not be the one that pulls it in.
    mod = importlib.import_module("app.ingestion.extractor")
    source = open(mod.__file__).read()  # noqa: SIM115 — short read, test scope
    # The deferred imports live inside method bodies — no top-level "import torch"
    top_level_lines = [
        line for line in source.splitlines()
        if line.startswith("import ") or line.startswith("from ")
    ]
    offenders = [
        line for line in top_level_lines
        if "torch" in line or "transformers" in line or "peft" in line
    ]
    assert offenders == [], (
        f"Heavy ML imports must be deferred to _ensure_loaded(), found at module level: {offenders}"
    )
    # Keep linter happy about unused import
    _ = sys.modules
