# tests/test_extraction_schema.py
#
# Project 3 — Phase 2: Unit tests for ExtractionResult schema and validate_extraction().
#
# Rules:
#   - No real model loading. No GPU required. All tests pass in a plain Python venv.
#   - Pydantic v2 only — use model_validate(), never parse_obj().
#   - validate_extraction() is tested with hand-crafted raw JSON strings, not model output.

import json
import logging

import pytest
from pydantic import ValidationError

from app.schemas.extraction import (
    Entity,
    ExtractionResult,
    SourceSpan,
    ValidationFlags,
)
from app.ingestion.validator import build_empty_result, validate_extraction


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_valid_extraction(record_id: str = "chunk_001") -> dict:
    """Return a dict that passes ExtractionResult.model_validate()."""
    return {
        "record_id": record_id,
        "schema_version": "v1",
        "entities": [
            {
                "entity_type": "medication",
                "mention": "metformin",
                "dosage": "500 mg",
                "linked_medication": None,
                "evidence": "started on metformin 500 mg",
                "source_span": {"start_char": 11, "end_char": 20},
            },
            {
                "entity_type": "adverse_event",
                "mention": "nausea",
                "dosage": None,
                "linked_medication": "metformin",
                "evidence": "developed nausea after dose increase",
                "source_span": {"start_char": 46, "end_char": 52},
            },
        ],
        "relation_status": "related",
        "validation": {
            "json_valid": True,
            "schema_valid": True,
            "enum_valid": True,
            "evidence_present": True,
        },
    }


# ── SourceSpan tests ──────────────────────────────────────────────────────────

class TestSourceSpan:
    def test_valid_span(self):
        span = SourceSpan(start_char=0, end_char=9)
        assert span.start_char == 0
        assert span.end_char == 9

    def test_negative_start_char_rejected(self):
        with pytest.raises(ValidationError):
            SourceSpan(start_char=-1, end_char=9)

    def test_negative_end_char_rejected(self):
        with pytest.raises(ValidationError):
            SourceSpan(start_char=0, end_char=-1)

    def test_zero_start_zero_end_allowed_by_field(self):
        # Field-level allows both == 0; the span check is at ExtractionResult level
        span = SourceSpan(start_char=0, end_char=0)
        assert span.start_char == 0


# ── Entity tests ──────────────────────────────────────────────────────────────

class TestEntity:
    def test_valid_medication_entity(self):
        entity = Entity(
            entity_type="medication",
            mention="aspirin",
            dosage="100 mg",
            linked_medication=None,
            evidence="given aspirin 100 mg",
            source_span=SourceSpan(start_char=6, end_char=13),
        )
        assert entity.entity_type == "medication"
        assert entity.dosage == "100 mg"

    def test_valid_adverse_event_entity(self):
        entity = Entity(
            entity_type="adverse_event",
            mention="rash",
            dosage=None,
            linked_medication="aspirin",
            evidence="developed rash after aspirin",
            source_span=SourceSpan(start_char=10, end_char=14),
        )
        assert entity.entity_type == "adverse_event"
        assert entity.linked_medication == "aspirin"

    def test_invalid_entity_type_rejected(self):
        with pytest.raises(ValidationError):
            Entity(
                entity_type="diagnosis",  # not a valid Literal
                mention="hypertension",
                evidence="diagnosed with hypertension",
                source_span=SourceSpan(start_char=0, end_char=12),
            )

    def test_empty_mention_rejected(self):
        with pytest.raises(ValidationError):
            Entity(
                entity_type="medication",
                mention="",  # min_length=1
                evidence="some evidence",
                source_span=SourceSpan(start_char=0, end_char=5),
            )

    def test_empty_evidence_rejected(self):
        with pytest.raises(ValidationError):
            Entity(
                entity_type="medication",
                mention="aspirin",
                evidence="",  # min_length=1
                source_span=SourceSpan(start_char=0, end_char=7),
            )

    def test_optional_fields_default_none(self):
        entity = Entity(
            entity_type="medication",
            mention="ibuprofen",
            evidence="ibuprofen prescribed",
            source_span=SourceSpan(start_char=0, end_char=9),
        )
        assert entity.dosage is None
        assert entity.linked_medication is None


# ── ExtractionResult tests ────────────────────────────────────────────────────

class TestExtractionResult:
    def test_valid_extraction_passes(self):
        data = _make_valid_extraction()
        result = ExtractionResult.model_validate(data)
        assert result.record_id == "chunk_001"
        assert result.schema_version == "v1"
        assert result.relation_status == "related"
        assert len(result.entities) == 2
        assert result.error_reason is None

    def test_invalid_span_inverted_rejected(self):
        """end_char <= start_char should fail the model_validator."""
        data = _make_valid_extraction()
        data["entities"][0]["source_span"] = {"start_char": 20, "end_char": 10}
        with pytest.raises(ValidationError, match="Invalid source_span"):
            ExtractionResult.model_validate(data)

    def test_invalid_span_equal_rejected(self):
        """end_char == start_char (zero-length) should also be rejected."""
        data = _make_valid_extraction()
        data["entities"][0]["source_span"] = {"start_char": 10, "end_char": 10}
        with pytest.raises(ValidationError, match="Invalid source_span"):
            ExtractionResult.model_validate(data)

    def test_invalid_relation_status_rejected(self):
        data = _make_valid_extraction()
        data["relation_status"] = "unknown"  # not in Literal
        with pytest.raises(ValidationError):
            ExtractionResult.model_validate(data)

    def test_invalid_schema_version_rejected(self):
        data = _make_valid_extraction()
        data["schema_version"] = "v2"  # only "v1" is valid
        with pytest.raises(ValidationError):
            ExtractionResult.model_validate(data)

    def test_empty_entities_allowed(self):
        data = _make_valid_extraction()
        data["entities"] = []
        data["relation_status"] = "not_related"
        result = ExtractionResult.model_validate(data)
        assert result.entities == []
        assert result.relation_status == "not_related"

    def test_error_reason_defaults_none(self):
        data = _make_valid_extraction()
        result = ExtractionResult.model_validate(data)
        assert result.error_reason is None

    def test_error_reason_set_explicitly(self):
        data = _make_valid_extraction()
        data["error_reason"] = "json_parse_failed"
        result = ExtractionResult.model_validate(data)
        assert result.error_reason == "json_parse_failed"

    def test_missing_record_id_rejected(self):
        data = _make_valid_extraction()
        del data["record_id"]
        with pytest.raises(ValidationError):
            ExtractionResult.model_validate(data)

    def test_missing_validation_block_rejected(self):
        data = _make_valid_extraction()
        del data["validation"]
        with pytest.raises(ValidationError):
            ExtractionResult.model_validate(data)


# ── build_empty_result tests ──────────────────────────────────────────────────

class TestBuildEmptyResult:
    def test_returns_extraction_result(self):
        result = build_empty_result("chunk_abc", "json_parse_failed")
        assert isinstance(result, ExtractionResult)

    def test_all_flags_false(self):
        result = build_empty_result("chunk_abc", "schema_invalid")
        assert result.validation.json_valid is False
        assert result.validation.schema_valid is False
        assert result.validation.enum_valid is False
        assert result.validation.evidence_present is False

    def test_entities_empty(self):
        result = build_empty_result("chunk_abc", "extraction_disabled")
        assert result.entities == []

    def test_relation_status_none(self):
        result = build_empty_result("chunk_abc", "extraction_error")
        assert result.relation_status == "none"

    def test_error_reason_set(self):
        result = build_empty_result("chunk_abc", "json_parse_failed")
        assert result.error_reason == "json_parse_failed"

    def test_record_id_set(self):
        result = build_empty_result("chunk_xyz", "schema_invalid")
        assert result.record_id == "chunk_xyz"


# ── validate_extraction tests ─────────────────────────────────────────────────

INPUT_TEXT = (
    "The patient was started on metformin 500 mg and developed nausea after dose increase."
)


class TestValidateExtraction:
    def _make_raw_json(self, **overrides) -> str:
        """Build a minimal valid model output JSON string (no record_id, no validation)."""
        base = {
            "schema_version": "v1",
            "entities": [
                {
                    "entity_type": "medication",
                    "mention": "metformin",
                    "dosage": "500 mg",
                    "linked_medication": None,
                    "evidence": "started on metformin 500 mg",
                    "source_span": {"start_char": 26, "end_char": 35},
                },
                {
                    "entity_type": "adverse_event",
                    "mention": "nausea",
                    "dosage": None,
                    "linked_medication": "metformin",
                    "evidence": "developed nausea after dose increase",
                    "source_span": {"start_char": 58, "end_char": 64},
                },
            ],
            "relation_status": "related",
        }
        base.update(overrides)
        return json.dumps(base)

    def test_valid_json_returns_schema_valid_true(self):
        result = validate_extraction(self._make_raw_json(), "chunk_001", INPUT_TEXT)
        assert isinstance(result, ExtractionResult)
        assert result.validation.schema_valid is True
        assert result.validation.json_valid is True
        assert result.record_id == "chunk_001"

    def test_broken_json_missing_bracket_returns_json_valid_false_or_repaired(self):
        """Broken JSON should either be repaired (if json_repair succeeds) or return
        json_valid=False with error_reason='json_parse_failed'."""
        broken = '{"schema_version": "v1", "entities": [], "relation_status": "not_related"'
        # Missing closing brace — json_repair should handle this
        result = validate_extraction(broken, "chunk_002", INPUT_TEXT)
        # Either repaired successfully or returned as failed — both are valid outcomes
        assert isinstance(result, ExtractionResult)
        if result.error_reason == "json_parse_failed":
            assert result.validation.json_valid is False
        else:
            # json_repair succeeded
            assert result.relation_status == "not_related"

    def test_completely_invalid_json_returns_error(self):
        """Garbage string that json_repair cannot fix should return build_empty_result."""
        garbage = "This is not JSON at all!!!! @#$%"
        result = validate_extraction(garbage, "chunk_003", INPUT_TEXT)
        assert result.error_reason == "json_parse_failed"
        assert result.validation.json_valid is False
        assert result.validation.schema_valid is False
        assert result.entities == []

    def test_wrong_enum_relation_status_returns_schema_invalid(self):
        """Invalid enum value should fail Pydantic validation."""
        raw = self._make_raw_json(relation_status="maybe_related")
        result = validate_extraction(raw, "chunk_004", INPUT_TEXT)
        assert result.error_reason == "schema_invalid"
        assert result.validation.schema_valid is False

    def test_wrong_enum_entity_type_returns_schema_invalid(self):
        """Invalid entity_type should fail Pydantic validation."""
        raw = json.dumps({
            "schema_version": "v1",
            "entities": [
                {
                    "entity_type": "procedure",  # invalid
                    "mention": "metformin",
                    "evidence": "started on metformin",
                    "source_span": {"start_char": 11, "end_char": 20},
                }
            ],
            "relation_status": "related",
        })
        result = validate_extraction(raw, "chunk_005", INPUT_TEXT)
        assert result.error_reason == "schema_invalid"

    def test_evidence_not_substring_sets_flag_false(self):
        """If evidence is not in input_text, evidence_present should be False."""
        raw = self._make_raw_json()
        # Input text that does NOT contain the evidence string
        different_text = "Aspirin was given intravenously."
        result = validate_extraction(raw, "chunk_006", different_text)
        assert result.validation.evidence_present is False
        # But the result should still be returned (not rejected)
        assert isinstance(result, ExtractionResult)
        assert result.error_reason is None

    def test_evidence_substring_present_leaves_flag_true(self):
        """When evidence IS a substring of input_text, evidence_present stays True."""
        result = validate_extraction(self._make_raw_json(), "chunk_007", INPUT_TEXT)
        assert result.validation.evidence_present is True

    def test_mention_not_in_input_logs_warning(self, caplog):
        """Hallucinated mentions (not in input) should log a WARNING."""
        raw = json.dumps({
            "schema_version": "v1",
            "entities": [
                {
                    "entity_type": "medication",
                    "mention": "imaginarydrug",  # not in INPUT_TEXT
                    "evidence": "imaginarydrug was used",
                    "source_span": {"start_char": 0, "end_char": 13},
                }
            ],
            "relation_status": "related",
        })
        with caplog.at_level(logging.WARNING):
            result = validate_extraction(raw, "chunk_008", INPUT_TEXT)
        assert "HALLUCINATION WARNING" in caplog.text
        assert "imaginarydrug" in caplog.text

    def test_record_id_injected_correctly(self):
        """validate_extraction must inject record_id from its argument, not trust the model."""
        result = validate_extraction(self._make_raw_json(), "my_special_chunk_id", INPUT_TEXT)
        assert result.record_id == "my_special_chunk_id"

    def test_inverted_span_returns_schema_invalid(self):
        """A span where end_char <= start_char should fail the model_validator."""
        raw = json.dumps({
            "schema_version": "v1",
            "entities": [
                {
                    "entity_type": "medication",
                    "mention": "metformin",
                    "evidence": "started on metformin",
                    "source_span": {"start_char": 20, "end_char": 5},  # inverted
                }
            ],
            "relation_status": "related",
        })
        result = validate_extraction(raw, "chunk_009", INPUT_TEXT)
        assert result.error_reason == "schema_invalid"

    def test_empty_entities_and_not_related_passes(self):
        """Negative examples (no entities, not_related) should pass validation."""
        raw = json.dumps({
            "schema_version": "v1",
            "entities": [],
            "relation_status": "not_related",
        })
        result = validate_extraction(raw, "chunk_010", "Some text with no drugs.")
        assert result.relation_status == "not_related"
        assert result.entities == []
        assert result.error_reason is None
        assert result.validation.schema_valid is True
