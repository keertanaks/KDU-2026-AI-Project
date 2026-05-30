# tests/test_integration_extraction.py
#
# Project 3 — Phase 6: Integration tests for the full clinical extraction pipeline.
#
# Scope:
#   validator.validate_extraction()
#     → app/ingestion/validator.py (JSON repair + Pydantic)
#   ClinicalExtractor.extract()
#     → app/ingestion/extractor.py
#   Output shape mapping (medications[], adverse_events[], relations[])
#     → mirrors the _meds()/_ades()/_relations() logic in app/api/documents.py
#
# Hard constraints (per CLAUDE.md):
#   - No real model loaded: all generation is mocked.
#   - No GPU, no model weights downloaded.
#   - No real OpenSearch connection.
#   - Extraction MUST run on original (unmasked) text (D-35).
#
# Unlike the unit tests in test_extractor.py (which test each method in isolation),
# these tests exercise multiple layers together, verifying that the outputs of one
# layer are correctly consumed by the next layer down the pipeline.

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.ingestion.extractor import ClinicalExtractor
from app.ingestion.validator import build_empty_result, validate_extraction
from app.schemas.extraction import ExtractionResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Clear the module-level singleton before each test."""
    ClinicalExtractor.reset_singleton()
    yield
    ClinicalExtractor.reset_singleton()


def _make_extractor_with_fake_model(generated_json: str) -> ClinicalExtractor:
    """Return a ClinicalExtractor whose _generate() produces ``generated_json``."""
    ext = ClinicalExtractor(model=MagicMock(), tokenizer=MagicMock())
    ext._generate = lambda text, record_id="": generated_json  # type: ignore[assignment]
    return ext


# ---------------------------------------------------------------------------
# Mirror of documents.py index-doc shape helpers
# (kept local so tests don't couple to the FastAPI router's private functions)
# ---------------------------------------------------------------------------


def _meds(result: ExtractionResult) -> list[dict]:
    return [
        {
            "mention": e.mention,
            "dosage": e.dosage,
            "evidence": e.evidence,
            "start_char": e.source_span.start_char,
            "end_char": e.source_span.end_char,
        }
        for e in result.entities
        if e.entity_type == "medication"
    ]


def _ades(result: ExtractionResult) -> list[dict]:
    return [
        {
            "mention": e.mention,
            "linked_medication": e.linked_medication,
            "evidence": e.evidence,
            "start_char": e.source_span.start_char,
            "end_char": e.source_span.end_char,
        }
        for e in result.entities
        if e.entity_type == "adverse_event"
    ]


def _relations(result: ExtractionResult) -> list[dict]:
    if result.relation_status != "related":
        return []
    return [
        {
            "drug": e.linked_medication,
            "adverse_event": e.mention,
            "status": "related",
            "evidence": e.evidence,
        }
        for e in result.entities
        if e.entity_type == "adverse_event" and e.linked_medication
    ]


# ---------------------------------------------------------------------------
# Layer integration: validate_extraction (validator.py) tests
# ---------------------------------------------------------------------------


class TestValidateExtraction:
    """Tests that exercise validate_extraction end-to-end (JSON parse → Pydantic → checks)."""

    def test_clean_json_produces_valid_result(self):
        payload = {
            "schema_version": "v1",
            "entities": [
                {
                    "entity_type": "medication",
                    "mention": "metformin",
                    "dosage": "500 mg",
                    "linked_medication": None,
                    "evidence": "started on metformin 500 mg daily",
                    "source_span": {"start_char": 11, "end_char": 20},
                }
            ],
            "relation_status": "not_related",
        }
        input_text = "Pt was started on metformin 500 mg daily."
        result = validate_extraction(
            raw_text=json.dumps(payload),
            record_id="integ_001",
            input_text=input_text,
        )

        assert isinstance(result, ExtractionResult)
        assert result.record_id == "integ_001"
        assert result.validation.json_valid is True
        assert result.validation.schema_valid is True
        assert result.validation.evidence_present is True
        assert len(result.entities) == 1
        assert result.entities[0].mention == "metformin"
        assert result.entities[0].dosage == "500 mg"
        assert result.error_reason is None

    def test_multi_entity_with_relation_produces_correct_output(self):
        """Medication + adverse_event → relation_status='related' flows correctly."""
        text = "Patient was given warfarin and subsequently developed GI bleeding."
        payload = {
            "schema_version": "v1",
            "entities": [
                {
                    "entity_type": "medication",
                    "mention": "warfarin",
                    "dosage": None,
                    "linked_medication": None,
                    "evidence": "Patient was given warfarin",
                    "source_span": {"start_char": 18, "end_char": 26},
                },
                {
                    "entity_type": "adverse_event",
                    "mention": "GI bleeding",
                    "dosage": None,
                    "linked_medication": "warfarin",
                    "evidence": "subsequently developed GI bleeding",
                    "source_span": {"start_char": 53, "end_char": 64},
                },
            ],
            "relation_status": "related",
        }
        result = validate_extraction(
            raw_text=json.dumps(payload),
            record_id="integ_002",
            input_text=text,
        )

        assert result.relation_status == "related"
        assert len(result.entities) == 2
        assert result.validation.evidence_present is True

        meds = _meds(result)
        ades = _ades(result)
        rels = _relations(result)

        assert len(meds) == 1
        assert meds[0]["mention"] == "warfarin"
        assert meds[0]["dosage"] is None

        assert len(ades) == 1
        assert ades[0]["mention"] == "GI bleeding"
        assert ades[0]["linked_medication"] == "warfarin"

        assert len(rels) == 1
        assert rels[0]["drug"] == "warfarin"
        assert rels[0]["adverse_event"] == "GI bleeding"
        assert rels[0]["status"] == "related"

    def test_not_related_status_produces_empty_relations(self):
        """relation_status='not_related' → _relations() returns []."""
        text = "Pt takes aspirin 81 mg daily for cardiac prophylaxis."
        payload = {
            "schema_version": "v1",
            "entities": [
                {
                    "entity_type": "medication",
                    "mention": "aspirin",
                    "dosage": "81 mg",
                    "linked_medication": None,
                    "evidence": "Pt takes aspirin 81 mg daily",
                    "source_span": {"start_char": 9, "end_char": 16},
                }
            ],
            "relation_status": "not_related",
        }
        result = validate_extraction(
            raw_text=json.dumps(payload),
            record_id="integ_003",
            input_text=text,
        )

        assert _relations(result) == []
        assert len(_meds(result)) == 1

    def test_none_relation_status_produces_empty_relations(self):
        """relation_status='none' (no entities) → _relations() returns []."""
        payload = {
            "schema_version": "v1",
            "entities": [],
            "relation_status": "none",
        }
        result = validate_extraction(
            raw_text=json.dumps(payload),
            record_id="integ_004",
            input_text="Patient has no current medications.",
        )

        assert result.relation_status == "none"
        assert _meds(result) == []
        assert _ades(result) == []
        assert _relations(result) == []

    def test_evidence_substring_flag_is_set_when_evidence_not_in_text(self):
        """If evidence is not a substring of input_text, evidence_present = False."""
        text = "Pt is on lisinopril 10 mg."
        payload = {
            "schema_version": "v1",
            "entities": [
                {
                    "entity_type": "medication",
                    "mention": "lisinopril",
                    "dosage": "10 mg",
                    "linked_medication": None,
                    "evidence": "started on lisinopril 20 mg",  # not a substring
                    "source_span": {"start_char": 9, "end_char": 19},
                }
            ],
            "relation_status": "not_related",
        }
        result = validate_extraction(
            raw_text=json.dumps(payload),
            record_id="integ_005",
            input_text=text,
        )

        # Schema is valid; only evidence_present is flagged
        assert result.validation.schema_valid is True
        assert result.validation.evidence_present is False
        assert result.error_reason is None
        # Entities are still returned (not rejected)
        assert len(result.entities) == 1

    def test_unparseable_json_returns_json_parse_failed(self):
        result = validate_extraction(
            raw_text="not json at all !!!",
            record_id="integ_006",
            input_text="Pt on aspirin.",
        )

        assert result.error_reason in {"json_parse_failed", "schema_invalid"}
        assert result.entities == []
        assert result.validation.json_valid is False

    def test_schema_invalid_json_returns_schema_invalid(self):
        """Valid JSON but wrong Pydantic shape → schema_invalid."""
        bad = json.dumps({"schema_version": "v1", "entities": "NOT_A_LIST"})
        result = validate_extraction(
            raw_text=bad,
            record_id="integ_007",
            input_text="Pt on metformin.",
        )

        assert result.error_reason == "schema_invalid"
        assert result.entities == []
        assert result.validation.schema_valid is False

    def test_inverted_span_returns_schema_invalid(self):
        """An entity with end_char <= start_char must be rejected (model validator)."""
        bad = json.dumps({
            "schema_version": "v1",
            "entities": [
                {
                    "entity_type": "medication",
                    "mention": "aspirin",
                    "dosage": None,
                    "linked_medication": None,
                    "evidence": "Pt takes aspirin",
                    "source_span": {"start_char": 20, "end_char": 5},  # inverted!
                }
            ],
            "relation_status": "not_related",
        })
        result = validate_extraction(
            raw_text=bad,
            record_id="integ_008",
            input_text="Pt takes aspirin daily.",
        )

        assert result.error_reason == "schema_invalid"
        assert result.entities == []


# ---------------------------------------------------------------------------
# Full pipeline: extractor.extract() → documents.py index-doc shape
# ---------------------------------------------------------------------------


class TestExtractorToIndexDocShape:
    """End-to-end: extract() → _meds()/_ades()/_relations() mirror of documents.py."""

    def test_single_medication_chunk_produces_correct_index_fields(self):
        payload = {
            "schema_version": "v1",
            "entities": [
                {
                    "entity_type": "medication",
                    "mention": "atorvastatin",
                    "dosage": "20 mg",
                    "linked_medication": None,
                    "evidence": "atorvastatin 20 mg nightly",
                    "source_span": {"start_char": 0, "end_char": 12},
                }
            ],
            "relation_status": "not_related",
        }
        ext = _make_extractor_with_fake_model(json.dumps(payload))
        result = ext.extract("atorvastatin 20 mg nightly for cholesterol.", record_id="chunk_a1")

        meds = _meds(result)
        ades = _ades(result)
        rels = _relations(result)

        assert len(meds) == 1
        assert meds[0]["mention"] == "atorvastatin"
        assert meds[0]["dosage"] == "20 mg"
        assert meds[0]["start_char"] == 0
        assert meds[0]["end_char"] == 12
        assert ades == []
        assert rels == []

    def test_ade_with_linked_medication_produces_relations(self):
        """Verifies D-linked-medication: relation built from ae.linked_medication, not cartesian."""
        text = "amoxicillin caused urticaria in this patient."
        payload = {
            "schema_version": "v1",
            "entities": [
                {
                    "entity_type": "medication",
                    "mention": "amoxicillin",
                    "dosage": None,
                    "linked_medication": None,
                    "evidence": "amoxicillin caused urticaria",
                    "source_span": {"start_char": 0, "end_char": 11},
                },
                {
                    "entity_type": "adverse_event",
                    "mention": "urticaria",
                    "dosage": None,
                    "linked_medication": "amoxicillin",
                    "evidence": "amoxicillin caused urticaria",
                    "source_span": {"start_char": 19, "end_char": 28},
                },
            ],
            "relation_status": "related",
        }
        ext = _make_extractor_with_fake_model(json.dumps(payload))
        result = ext.extract(text, record_id="chunk_a2")

        rels = _relations(result)
        assert len(rels) == 1
        assert rels[0]["drug"] == "amoxicillin"
        assert rels[0]["adverse_event"] == "urticaria"
        assert rels[0]["status"] == "related"

    def test_multiple_ades_only_linked_ones_produce_relations(self):
        """ADE without linked_medication does NOT appear in _relations()."""
        text = "ibuprofen led to nausea; patient also reported fatigue of unknown cause."
        payload = {
            "schema_version": "v1",
            "entities": [
                {
                    "entity_type": "medication",
                    "mention": "ibuprofen",
                    "dosage": None,
                    "linked_medication": None,
                    "evidence": "ibuprofen led to nausea",
                    "source_span": {"start_char": 0, "end_char": 9},
                },
                {
                    "entity_type": "adverse_event",
                    "mention": "nausea",
                    "dosage": None,
                    "linked_medication": "ibuprofen",
                    "evidence": "ibuprofen led to nausea",
                    "source_span": {"start_char": 17, "end_char": 23},
                },
                {
                    "entity_type": "adverse_event",
                    "mention": "fatigue",
                    "dosage": None,
                    "linked_medication": None,  # unlinked ADE
                    "evidence": "patient also reported fatigue of unknown cause",
                    "source_span": {"start_char": 33, "end_char": 40},
                },
            ],
            "relation_status": "related",
        }
        ext = _make_extractor_with_fake_model(json.dumps(payload))
        result = ext.extract(text, record_id="chunk_a3")

        ades = _ades(result)
        rels = _relations(result)

        # Both ADEs appear in ades[]
        assert len(ades) == 2
        ade_mentions = {a["mention"] for a in ades}
        assert ade_mentions == {"nausea", "fatigue"}

        # Only the linked ADE becomes a relation
        assert len(rels) == 1
        assert rels[0]["adverse_event"] == "nausea"

    def test_extraction_on_original_text_preserves_span_offsets(self):
        """D-35: extraction runs on original (unmasked) text; spans must index into it."""
        original_text = "John Smith was prescribed lisinopril 10 mg for hypertension."
        # "lisinopril" starts at index 25 in original_text
        start = original_text.index("lisinopril")
        end = start + len("lisinopril")

        payload = {
            "schema_version": "v1",
            "entities": [
                {
                    "entity_type": "medication",
                    "mention": "lisinopril",
                    "dosage": "10 mg",
                    "linked_medication": None,
                    "evidence": "prescribed lisinopril 10 mg",
                    "source_span": {"start_char": start, "end_char": end},
                }
            ],
            "relation_status": "not_related",
        }
        ext = _make_extractor_with_fake_model(json.dumps(payload))
        result = ext.extract(original_text, record_id="chunk_a4")

        entity = result.entities[0]
        # Span must be valid against original_text
        assert original_text[entity.source_span.start_char:entity.source_span.end_char] == "lisinopril"


# ---------------------------------------------------------------------------
# Multi-chunk pipeline simulation (mirrors the loop in documents.py)
# ---------------------------------------------------------------------------


class TestMultiChunkExtractionLoop:
    """Simulate the per-chunk extraction loop from documents.py."""

    def test_three_chunks_produce_independent_results(self):
        """Each chunk gets its own ExtractionResult with its own record_id."""
        chunks_and_payloads = [
            (
                "Pt on metformin 500 mg.",
                {
                    "schema_version": "v1",
                    "entities": [
                        {
                            "entity_type": "medication",
                            "mention": "metformin",
                            "dosage": "500 mg",
                            "linked_medication": None,
                            "evidence": "Pt on metformin 500 mg",
                            "source_span": {"start_char": 6, "end_char": 15},
                        }
                    ],
                    "relation_status": "not_related",
                },
            ),
            (
                "No adverse events noted.",
                {
                    "schema_version": "v1",
                    "entities": [],
                    "relation_status": "none",
                },
            ),
            (
                "clopidogrel caused bruising.",
                {
                    "schema_version": "v1",
                    "entities": [
                        {
                            "entity_type": "medication",
                            "mention": "clopidogrel",
                            "dosage": None,
                            "linked_medication": None,
                            "evidence": "clopidogrel caused bruising",
                            "source_span": {"start_char": 0, "end_char": 11},
                        },
                        {
                            "entity_type": "adverse_event",
                            "mention": "bruising",
                            "dosage": None,
                            "linked_medication": "clopidogrel",
                            "evidence": "clopidogrel caused bruising",
                            "source_span": {"start_char": 19, "end_char": 27},
                        },
                    ],
                    "relation_status": "related",
                },
            ),
        ]

        results = []
        for i, (text, payload) in enumerate(chunks_and_payloads):
            ext = _make_extractor_with_fake_model(json.dumps(payload))
            chunk_id = f"chunk_{i:03d}"
            result = ext.extract(text, record_id=chunk_id)
            results.append(result)

        # Chunk 0: medication only
        assert results[0].record_id == "chunk_000"
        assert len(_meds(results[0])) == 1
        assert _meds(results[0])[0]["mention"] == "metformin"
        assert _relations(results[0]) == []

        # Chunk 1: empty
        assert results[1].record_id == "chunk_001"
        assert results[1].entities == []
        assert results[1].relation_status == "none"

        # Chunk 2: medication + ADE + relation
        assert results[2].record_id == "chunk_002"
        assert len(_meds(results[2])) == 1
        assert len(_ades(results[2])) == 1
        assert len(_relations(results[2])) == 1

    def test_failed_chunk_does_not_block_subsequent_chunks(self):
        """A RuntimeError on one chunk must degrade to ExtractionResult, not raise."""
        good_payload = json.dumps({
            "schema_version": "v1",
            "entities": [
                {
                    "entity_type": "medication",
                    "mention": "aspirin",
                    "dosage": None,
                    "linked_medication": None,
                    "evidence": "Pt on aspirin",
                    "source_span": {"start_char": 6, "end_char": 13},
                }
            ],
            "relation_status": "not_related",
        })

        # Chunk 0: good
        ext0 = _make_extractor_with_fake_model(good_payload)
        r0 = ext0.extract("Pt on aspirin daily.", record_id="c0")

        # Chunk 1: _generate raises OOM
        ext1 = ClinicalExtractor(model=MagicMock(), tokenizer=MagicMock())
        def _boom(text, record_id=""):
            raise RuntimeError("CUDA out of memory")
        ext1._generate = _boom  # type: ignore[assignment]
        r1 = ext1.extract("Pt on warfarin.", record_id="c1")

        # Chunk 2: good
        ext2 = _make_extractor_with_fake_model(good_payload)
        r2 = ext2.extract("Pt on aspirin daily.", record_id="c2")

        # All three return ExtractionResult — pipeline never crashed
        assert r0.error_reason is None
        assert len(r0.entities) == 1

        assert r1.error_reason == "extraction_error"
        assert r1.entities == []

        assert r2.error_reason is None
        assert len(r2.entities) == 1


# ---------------------------------------------------------------------------
# build_empty_result integration
# ---------------------------------------------------------------------------


class TestBuildEmptyResult:
    """Verify build_empty_result produces correct sentinel values for all reason codes."""

    @pytest.mark.parametrize("reason", [
        "json_parse_failed",
        "schema_invalid",
        "extraction_disabled",
        "extraction_error",
        "model_load_failed",
        "empty_input",
    ])
    def test_empty_result_structure_for_all_reason_codes(self, reason):
        result = build_empty_result(record_id="test_empty", reason=reason)

        assert isinstance(result, ExtractionResult)
        assert result.record_id == "test_empty"
        assert result.error_reason == reason
        assert result.entities == []
        assert result.relation_status == "none"
        assert result.validation.json_valid is False
        assert result.validation.schema_valid is False
        assert result.validation.enum_valid is False
        assert result.validation.evidence_present is False

        # build_empty_result must always produce empty index fields
        assert _meds(result) == []
        assert _ades(result) == []
        assert _relations(result) == []


# ---------------------------------------------------------------------------
# Remote-mode integration
# ---------------------------------------------------------------------------


class TestRemoteModeIntegration:
    """Verify the remote-mode path integrates correctly with validate_extraction."""

    def test_remote_result_flows_through_validator_to_index_shape(self, monkeypatch):
        monkeypatch.setenv("EXTRACTION_REMOTE_URL", "https://fake.hf.space")

        payload = {
            "schema_version": "v1",
            "entities": [
                {
                    "entity_type": "medication",
                    "mention": "metoprolol",
                    "dosage": "50 mg",
                    "linked_medication": None,
                    "evidence": "metoprolol 50 mg twice daily",
                    "source_span": {"start_char": 0, "end_char": 10},
                },
                {
                    "entity_type": "adverse_event",
                    "mention": "bradycardia",
                    "dosage": None,
                    "linked_medication": "metoprolol",
                    "evidence": "developed bradycardia",
                    "source_span": {"start_char": 30, "end_char": 41},
                },
            ],
            "relation_status": "related",
        }
        fake_response = MagicMock()
        fake_response.json.return_value = {"raw_output": json.dumps(payload)}
        fake_response.raise_for_status.return_value = None

        input_text = "metoprolol 50 mg twice daily; developed bradycardia."

        with patch("requests.post", return_value=fake_response):
            ext = ClinicalExtractor()
            result = ext.extract(input_text, record_id="remote_integ_01")

        assert result.error_reason is None
        assert result.validation.schema_valid is True

        meds = _meds(result)
        ades = _ades(result)
        rels = _relations(result)

        assert len(meds) == 1
        assert meds[0]["mention"] == "metoprolol"

        assert len(ades) == 1
        assert ades[0]["mention"] == "bradycardia"
        assert ades[0]["linked_medication"] == "metoprolol"

        assert len(rels) == 1
        assert rels[0]["drug"] == "metoprolol"
        assert rels[0]["adverse_event"] == "bradycardia"

    def test_remote_network_failure_produces_empty_index_fields(self, monkeypatch):
        monkeypatch.setenv("EXTRACTION_REMOTE_URL", "https://fake.hf.space")
        import requests

        with patch("requests.post", side_effect=requests.ConnectionError("refused")):
            ext = ClinicalExtractor()
            result = ext.extract("Pt on warfarin.", record_id="remote_integ_02")

        assert result.error_reason == "extraction_error"
        assert _meds(result) == []
        assert _ades(result) == []
        assert _relations(result) == []

    def test_adapter_version_remote_mode_uses_remote_prefix(self, monkeypatch):
        monkeypatch.setenv("EXTRACTION_REMOTE_URL", "https://fake.hf.space")
        monkeypatch.setenv("EXTRACTION_ADAPTER_PATH", "models/adapters/lora_v1")
        ext = ClinicalExtractor()
        version = ext.adapter_version()
        # This is what gets written to extraction_model_version in OpenSearch
        assert version.startswith("remote:")
        assert "lora_v1" in version
