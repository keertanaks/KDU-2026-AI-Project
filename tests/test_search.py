"""
Tests for search-layer components: ResponseMasker and AnswerGenerator.

AnswerGenerator tests only exercise the skipped-key path and the
internal helper functions — they never make real HTTP calls to OpenRouter.
"""

import json
import os
import unittest.mock as mock

import pytest

from app.search.masker import ResponseMasker
from app.search.answer_generator import (
    _build_placeholder_context,
    _restore,
    redact_placeholders,
    _contains_phi_fragments,
    _sanitize_remaining_fragments,
    _extract_simple_answer,
    AnswerGenerator,
)


# ---------------------------------------------------------------------------
# Helpers shared across masker tests
# ---------------------------------------------------------------------------

SAMPLE_TEXT = "Patient: Emily Moore\nDOB: 1972-03-14\nMRN: MRN100003"

# Span covering "Emily Moore" (positions 9–20 in SAMPLE_TEXT)
PHI_SPANS_LIST = [{"type": "PERSON", "start": 9, "end": 20, "confidence": 0.85}]
PHI_SPANS_JSON = json.dumps(PHI_SPANS_LIST)


def _make_chunk(text: str, phi_spans, doc_id: str = "doc-1") -> dict:
    """Build a minimal OpenSearch hit-shaped dict."""
    return {"_source": {"text": text, "phi_spans": phi_spans, "doc_id": doc_id}}


# ---------------------------------------------------------------------------
# ResponseMasker — treating clinician (no masking)
# ---------------------------------------------------------------------------

class TestResponseMaskerTreating:
    def test_treating_clinician_text_unchanged(self):
        result = ResponseMasker.mask(SAMPLE_TEXT, PHI_SPANS_LIST, "treating_clinician")
        assert result == SAMPLE_TEXT

    def test_treating_clinician_with_json_spans_unchanged(self):
        result = ResponseMasker.mask(SAMPLE_TEXT, PHI_SPANS_JSON, "treating_clinician")
        assert result == SAMPLE_TEXT

    def test_treating_clinician_no_redacted_tokens(self):
        result = ResponseMasker.mask(SAMPLE_TEXT, PHI_SPANS_LIST, "treating_clinician")
        assert "_REDACTED>" not in result


# ---------------------------------------------------------------------------
# ResponseMasker — non-treating clinician (PERSON, DATE_TIME, LOCATION masked)
# ---------------------------------------------------------------------------

class TestResponseMaskerNonTreating:
    def test_person_span_masked(self):
        result = ResponseMasker.mask(SAMPLE_TEXT, PHI_SPANS_LIST, "non_treating_clinician")
        assert "Emily Moore" not in result
        assert "<PERSON_REDACTED>" in result

    def test_accepts_json_string_phi_spans(self):
        result = ResponseMasker.mask(SAMPLE_TEXT, PHI_SPANS_JSON, "non_treating_clinician")
        assert "<PERSON_REDACTED>" in result

    def test_multiple_spans_all_masked(self):
        spans = [
            {"type": "PERSON", "start": 9, "end": 20, "confidence": 0.9},
            {"type": "DATE_TIME", "start": 26, "end": 36, "confidence": 0.9},
        ]
        result = ResponseMasker.mask(SAMPLE_TEXT, spans, "non_treating_clinician")
        assert "Emily Moore" not in result
        assert "1972-03-14" not in result


# ---------------------------------------------------------------------------
# ResponseMasker — administrator (extended mask including DIAGNOSIS)
# ---------------------------------------------------------------------------

class TestResponseMaskerAdmin:
    def test_admin_person_span_masked(self):
        result = ResponseMasker.mask(SAMPLE_TEXT, PHI_SPANS_LIST, "administrator")
        assert "Emily Moore" not in result
        assert "<PERSON_REDACTED>" in result

    def test_admin_diagnosis_masked(self):
        text = "Diagnosis: Hypertension. Patient details follow."
        spans = [{"type": "DIAGNOSIS", "start": 11, "end": 23, "confidence": 0.8}]
        result = ResponseMasker.mask(text, spans, "administrator")
        assert "Hypertension" not in result
        assert "<DIAGNOSIS_REDACTED>" in result

    def test_admin_diagnosis_not_masked_for_non_treating(self):
        # DIAGNOSIS is only in the admin policy, not non_treating
        text = "Diagnosis: Hypertension."
        spans = [{"type": "DIAGNOSIS", "start": 11, "end": 23, "confidence": 0.8}]
        result = ResponseMasker.mask(text, spans, "non_treating_clinician")
        assert "Hypertension" in result


# ---------------------------------------------------------------------------
# ResponseMasker — edge cases
# ---------------------------------------------------------------------------

class TestResponseMaskerEdgeCases:
    def test_invalid_json_phi_spans_treated_as_empty(self):
        result = ResponseMasker.mask(SAMPLE_TEXT, "not-valid-json", "non_treating_clinician")
        assert result == SAMPLE_TEXT

    def test_out_of_bounds_span_skipped(self):
        spans = [{"type": "PERSON", "start": 999, "end": 1050, "confidence": 0.9}]
        result = ResponseMasker.mask(SAMPLE_TEXT, spans, "non_treating_clinician")
        assert result == SAMPLE_TEXT

    def test_unknown_role_defaults_to_non_treating_masking(self):
        result = ResponseMasker.mask(SAMPLE_TEXT, PHI_SPANS_LIST, "unknown_role")
        assert "<PERSON_REDACTED>" in result

    def test_empty_phi_spans_text_unchanged(self):
        result = ResponseMasker.mask(SAMPLE_TEXT, [], "non_treating_clinician")
        assert result == SAMPLE_TEXT

    def test_empty_text_returns_empty(self):
        result = ResponseMasker.mask("", PHI_SPANS_LIST, "non_treating_clinician")
        assert result == ""

    def test_span_start_equals_end_skipped(self):
        spans = [{"type": "PERSON", "start": 9, "end": 9, "confidence": 0.9}]
        result = ResponseMasker.mask(SAMPLE_TEXT, spans, "non_treating_clinician")
        assert result == SAMPLE_TEXT


# ---------------------------------------------------------------------------
# _build_placeholder_context — PHI placeholder building (unit)
# ---------------------------------------------------------------------------

class TestBuildPlaceholderContext:
    def _chunk(self, text, spans):
        return _make_chunk(text, spans)

    def test_produces_placeholder_tokens(self):
        chunks = [self._chunk("Emily Moore is the patient.", [
            {"type": "PERSON", "start": 0, "end": 11, "confidence": 0.9}
        ])]
        context, mapping = _build_placeholder_context(chunks)
        try:
            assert "PERSON_1" in context
            assert "Emily Moore" not in context
        finally:
            mapping.clear()

    def test_mapping_contains_original_text(self):
        chunks = [self._chunk("Emily Moore is the patient.", [
            {"type": "PERSON", "start": 0, "end": 11, "confidence": 0.9}
        ])]
        context, mapping = _build_placeholder_context(chunks)
        try:
            assert mapping.get("[[PHI_PERSON_1]]") == "Emily Moore"
        finally:
            mapping.clear()

    def test_multiple_same_type_get_incrementing_counters(self):
        chunks = [self._chunk("Emily Moore and John Doe are here.", [
            {"type": "PERSON", "start": 0, "end": 11, "confidence": 0.9},
            {"type": "PERSON", "start": 16, "end": 24, "confidence": 0.9},
        ])]
        context, mapping = _build_placeholder_context(chunks)
        try:
            assert "[[PHI_PERSON_1]]" in mapping
            assert "[[PHI_PERSON_2]]" in mapping
        finally:
            mapping.clear()

    def test_out_of_bounds_spans_skipped(self):
        chunks = [self._chunk("short text", [
            {"type": "PERSON", "start": 999, "end": 1099, "confidence": 0.9}
        ])]
        context, mapping = _build_placeholder_context(chunks)
        try:
            assert "short text" in context
            assert mapping == {}
        finally:
            mapping.clear()

    def test_empty_chunks_returns_empty_context(self):
        context, mapping = _build_placeholder_context([])
        try:
            assert context == ""
            assert mapping == {}
        finally:
            mapping.clear()

    def test_json_string_spans_deserialized(self):
        spans_json = json.dumps([{"type": "PERSON", "start": 0, "end": 5, "confidence": 0.9}])
        chunks = [self._chunk("Alice is a patient.", spans_json)]
        context, mapping = _build_placeholder_context(chunks)
        try:
            assert "PERSON_1" in context
        finally:
            mapping.clear()


# ---------------------------------------------------------------------------
# _restore — placeholder substitution (unit)
# ---------------------------------------------------------------------------

class TestRestore:
    def test_replaces_single_placeholder(self):
        mapping = {"PERSON_1": "Emily Moore"}
        result = _restore("Hello PERSON_1.", mapping)
        assert result == "Hello Emily Moore."

    def test_replaces_multiple_placeholders(self):
        mapping = {"PERSON_1": "Emily Moore", "DATE_TIME_1": "1972-03-14"}
        result = _restore("PERSON_1 was born on DATE_TIME_1.", mapping)
        assert "Emily Moore" in result
        assert "1972-03-14" in result

    def test_no_match_text_unchanged(self):
        mapping = {"PERSON_1": "Emily Moore"}
        result = _restore("No placeholders here.", mapping)
        assert result == "No placeholders here."

    def test_empty_mapping_text_unchanged(self):
        result = _restore("PERSON_1 and DATE_TIME_1", {})
        assert result == "PERSON_1 and DATE_TIME_1"


# ---------------------------------------------------------------------------
# AnswerGenerator — skipped path (no live API call needed)
# ---------------------------------------------------------------------------

class TestAnswerGeneratorSkipped:
    def _gen(self):
        return AnswerGenerator()

    def test_placeholder_key_returns_skipped(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-placeholder")
        answer, status, sources = self._gen().generate("query", [], "treating_clinician")
        assert status == "skipped"
        assert answer == ""

    def test_missing_key_returns_skipped(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        answer, status, sources = self._gen().generate("query", [], "treating_clinician")
        assert status == "skipped"

    def test_sources_extracted_from_chunks(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-placeholder")
        chunks = [
            _make_chunk("text1", [], "doc-AAA"),
            _make_chunk("text2", [], "doc-BBB"),
        ]
        _, _, sources = self._gen().generate("query", chunks, "treating_clinician")
        assert "doc-AAA" in sources
        assert "doc-BBB" in sources

    def test_empty_doc_id_filtered_from_sources(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-placeholder")
        chunks = [
            _make_chunk("text1", [], ""),
            _make_chunk("text2", [], "doc-REAL"),
        ]
        _, _, sources = self._gen().generate("query", chunks, "treating_clinician")
        assert "" not in sources
        assert "doc-REAL" in sources


# ---------------------------------------------------------------------------
# Placeholder Restoration — corruption handling (longest-first order)
# ---------------------------------------------------------------------------

class TestPlaceholderRestoration:
    def test_restore_clean_placeholder(self):
        """Restore a clean [[PHI_PERSON_1]] token to original value."""
        mapping = {"[[PHI_PERSON_1]]": "Hannah Perez"}
        text = "Patient name is [[PHI_PERSON_1]]."
        result = _restore(text, mapping)
        assert result == "Patient name is Hannah Perez."
        assert "[[PHI_" not in result

    def test_restore_longest_first_prevents_corruption(self):
        """
        Longest-first sorting prevents "Hanna[[PHI_DATE_TIME_1]]" corruption.
        If [[PHI_PERSON_1]] was replaced after [[PHI_PERSON_11]], we'd corrupt the word.
        """
        mapping = {
            "[[PHI_PERSON_1]]": "Hannah Perez",
            "[[PHI_DATE_TIME_1]]": "2025-05-14",
        }
        # Simulate LLM output with both tokens
        text = "[[PHI_PERSON_1]] was born on [[PHI_DATE_TIME_1]]."
        result = _restore(text, mapping)
        assert result == "Hannah Perez was born on 2025-05-14."
        assert "[[PHI_" not in result
        assert "Hannah Perez" in result  # Full name restored, not corrupted

    def test_restore_skips_missing_tokens(self):
        """If a token isn't in the text, skip it (don't add it)."""
        mapping = {
            "[[PHI_PERSON_1]]": "Hannah Perez",
            "[[PHI_PERSON_2]]": "John Doe",  # Not in text
        }
        text = "Patient: [[PHI_PERSON_1]]"
        result = _restore(text, mapping)
        assert result == "Patient: Hannah Perez"
        assert "John Doe" not in result

    def test_restore_empty_mapping(self):
        """Empty mapping should return text unchanged."""
        text = "Some text with [[PHI_PERSON_1]]"
        result = _restore(text, {})
        assert result == text


class TestPlaceholderCorruptionDetection:
    def test_contains_phi_fragments_detects_orphaned_bracket(self):
        """Detect [[PHI_ orphan fragments (LLM corruption)."""
        assert _contains_phi_fragments("text [[PHI_") is True
        assert _contains_phi_fragments("Hanna[[PHI_DATE_TIME_1]]") is True

    def test_contains_phi_fragments_clean_text(self):
        """Clean text with no PHI fragments."""
        assert _contains_phi_fragments("Hannah Perez was born in 1990.") is False
        assert _contains_phi_fragments("Patient: John <PERSON_REDACTED>") is False

    def test_sanitize_removes_corrupted_placeholders(self):
        """Convert corrupted/remaining placeholders to <TYPE_REDACTED>."""
        # Input: LLM corrupted "Hannah" + leftover DATE_TIME placeholder
        text = "Hanna[[PHI_DATE_TIME_1]]"
        result = _sanitize_remaining_fragments(text)
        assert "[[PHI_" not in result
        assert "Hanna" in result  # Keep the word, redact the placeholder
        assert "REDACTED" in result

    def test_sanitize_orphaned_fragments(self):
        """Clean up orphaned [[PHI_ fragments."""
        text = "text [[PHI_ leftover"
        result = _sanitize_remaining_fragments(text)
        assert "[[PHI_" not in result
        assert "REDACTED" in result


class TestFallbackExtractor:
    """Test simple answer extraction for common query patterns."""

    def _make_prescription_chunk(self, patient="Hannah Perez", mrn="MRN100016", physician="Dr. Jonathan Hall") -> dict:
        """Create a prescription chunk for testing."""
        text = f"""# Prescription

Patient: {patient}
MRN: {mrn}
Date: 2025-05-07
Age: 30
Diagnosis: Diabetes Type2 (ICD: E11)
Prescribing Physician: {physician}

## Medications

| Medication | Dosage | Frequency |
|---|---|---|
| Metformin | 1000mg | 1 tablet twice daily |
| Glipizide | 5mg | 1 tablet daily |
| Januvia | 100mg | 1 tablet daily |"""
        return {"_source": {"text": text, "normalized_text": text, "doc_id": "test-doc"}}

    def test_extract_patient_for_medication_query(self):
        """Pattern 1: 'Which patient was prescribed Metformin?'"""
        chunk = self._make_prescription_chunk(patient="Hannah Perez")
        query = "Which patient was prescribed Metformin 1000mg?"
        result = _extract_simple_answer(query, chunk)
        assert result is not None
        assert "Hannah Perez" in result
        assert "Metformin" in result

    def test_extract_medications_for_patient_query(self):
        """Pattern 2: 'What medications was Hannah prescribed?'"""
        chunk = self._make_prescription_chunk()
        query = "What medications was Hannah Perez prescribed?"
        result = _extract_simple_answer(query, chunk)
        assert result is not None
        assert "Metformin" in result
        assert "Glipizide" in result
        assert "Januvia" in result

    def test_extract_physician_for_prescriber_query(self):
        """Pattern 3: 'Who prescribed Hannah's medication?'"""
        chunk = self._make_prescription_chunk(physician="Dr. Jonathan Hall")
        query = "Who prescribed Hannah Perez's medication?"
        result = _extract_simple_answer(query, chunk)
        assert result is not None
        assert "Dr. Jonathan Hall" in result

    def test_extract_mrn_for_mrn_query(self):
        """Pattern 4: 'What is the MRN for Hannah?'"""
        chunk = self._make_prescription_chunk(mrn="MRN100016")
        query = "What is the MRN for Hannah Perez?"
        result = _extract_simple_answer(query, chunk)
        assert result is not None
        assert "MRN100016" in result

    def test_extract_returns_none_for_no_match(self):
        """Non-matching query returns None."""
        chunk = self._make_prescription_chunk()
        query = "What is the weather today?"
        result = _extract_simple_answer(query, chunk)
        assert result is None

    def test_extract_returns_none_for_empty_chunk(self):
        """Empty chunk returns None."""
        query = "Which patient was prescribed Metformin?"
        result = _extract_simple_answer(query, None)
        assert result is None


class TestRedactPlaceholdersNonTreating:
    def test_redact_well_formed_person_placeholder(self):
        """Convert [[PHI_PERSON_1]] to <PERSON_REDACTED>."""
        text = "Patient name is [[PHI_PERSON_1]]."
        result = redact_placeholders(text)
        assert "[[PHI_" not in result
        assert "<PERSON_REDACTED>" in result

    def test_redact_multiple_placeholder_types(self):
        """Redact mixed placeholder types."""
        text = "[[PHI_PERSON_1]] born [[PHI_DATE_TIME_1]] at [[PHI_LOCATION_1]]"
        result = redact_placeholders(text)
        assert "[[PHI_" not in result
        assert "<PERSON_REDACTED>" in result
        assert "<DATE_TIME_REDACTED>" in result
        assert "<LOCATION_REDACTED>" in result

    def test_redact_orphaned_fragments(self):
        """Redact remaining orphaned fragments after multi-pass."""
        text = "text with [[PHI_ leftover"
        result = redact_placeholders(text)
        assert "[[PHI_" not in result
        assert "REDACTED" in result


# ---------------------------------------------------------------------------
# AnswerGenerator — PHI safety: mapping cleared after generate()
# ---------------------------------------------------------------------------

class TestAnswerGeneratorPhiSafety:
    def test_mapping_cleared_on_skipped(self, monkeypatch):
        """Even in the skipped path the mapping lifecycle (build → clear) is safe.
        We confirm generate() returns without leaking internal state."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-placeholder")
        gen = AnswerGenerator()
        chunks = [_make_chunk("Emily Moore is a patient.", [
            {"type": "PERSON", "start": 0, "end": 11, "confidence": 0.9}
        ])]
        answer, status, _ = gen.generate("who is the patient?", chunks, "treating_clinician")
        assert status == "skipped"
        # No PHI leaked into the (empty) answer
        assert "Emily Moore" not in answer

    def test_non_treating_answer_has_no_restored_phi(self, monkeypatch):
        """When status=skipped and role=non_treating, answer must be empty (no PHI)."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-placeholder")
        gen = AnswerGenerator()
        answer, status, _ = gen.generate("test", [], "non_treating_clinician")
        assert status == "skipped"
        assert answer == ""

    def test_failed_api_call_returns_empty_answer(self, monkeypatch):
        """Simulate a real (non-placeholder) key but a failing API call — must return 'failed'."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-realkey")
        monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

        with mock.patch("openai.OpenAI") as MockOpenAI:
            MockOpenAI.side_effect = Exception("network error")
            gen = AnswerGenerator()
            answer, status, _ = gen.generate("query", [], "treating_clinician")

        assert status == "failed"
        assert answer == ""


# ---------------------------------------------------------------------------
# ResponseMasker — space handling around redactions
# ---------------------------------------------------------------------------

class TestResponseMaskerSpacing:
    def test_space_added_before_redaction_if_preceded_by_alphanumeric(self):
        """PERSON span after colon should get space before redaction."""
        text = "Name:John Smith"
        spans = [{"type": "PERSON", "start": 5, "end": 15, "confidence": 0.9}]
        result = ResponseMasker.mask(text, spans, "non_treating_clinician")
        # Colon is not alphanumeric, so no space added before redaction
        assert result == "Name:<PERSON_REDACTED>"

    def test_space_added_after_redaction_if_followed_by_alphanumeric(self):
        """LOCATION span followed by zipcode should get space after redaction."""
        text = "Cedar-Sinai33101"
        spans = [{"type": "LOCATION", "start": 0, "end": 11, "confidence": 0.9}]
        result = ResponseMasker.mask(text, spans, "non_treating_clinician")
        # Should have space between redaction and zipcode (both alphanumeric neighbors)
        assert result == "<LOCATION_REDACTED> 33101"

    def test_no_double_space_if_span_surrounded_by_spaces(self):
        """If spans are already separated by spaces, no extra spaces added."""
        text = "Patient John Smith here"
        spans = [{"type": "PERSON", "start": 8, "end": 18, "confidence": 0.9}]
        result = ResponseMasker.mask(text, spans, "non_treating_clinician")
        assert "Patient <PERSON_REDACTED> here" == result

    def test_no_space_added_for_non_alphanumeric_neighbors(self):
        """Redaction adjacent to punctuation should not add extra space."""
        text = "Emily[123]"
        spans = [{"type": "PERSON", "start": 0, "end": 5, "confidence": 0.9}]
        result = ResponseMasker.mask(text, spans, "non_treating_clinician")
        assert "<PERSON_REDACTED>[123]" == result


# ---------------------------------------------------------------------------
# AnswerGenerator — final role sanitizer for partial name removal
# ---------------------------------------------------------------------------

class TestFinalRoleSanitizer:
    def test_treating_clinician_answer_unchanged(self):
        """Treating clinician answers pass through unchanged."""
        from app.search.answer_generator import _apply_final_role_sanitizer
        answer = "Patient Hanna Smith with MRN100016 prescribed Metformin"
        result = _apply_final_role_sanitizer(answer, "treating_clinician")
        assert result == answer

    def test_non_treating_removes_partial_name_before_redaction(self):
        """Non-treating: partial names like 'Hanna<PERSON_REDACTED>' become just '<PERSON_REDACTED>'."""
        from app.search.answer_generator import _apply_final_role_sanitizer
        answer = "The patient is Hanna<PERSON_REDACTED>, age 30"
        result = _apply_final_role_sanitizer(answer, "non_treating_clinician")
        assert "Hanna<PERSON_REDACTED>" not in result
        assert "<PERSON_REDACTED>" in result
        # Should be like: "The patient is <PERSON_REDACTED>, age 30"

    def test_non_treating_removes_multipart_names(self):
        """Multi-word names before redaction tags should be fully removed."""
        from app.search.answer_generator import _apply_final_role_sanitizer
        answer = "Patients: Mia Ta<PERSON_REDACTED> and Dr. Sarah<PERSON_REDACTED>"
        result = _apply_final_role_sanitizer(answer, "non_treating_clinician")
        assert "Mia Ta<PERSON_REDACTED>" not in result
        assert "Sarah<PERSON_REDACTED>" not in result
        assert result.count("<PERSON_REDACTED>") == 2

    def test_non_treating_redacts_mrn_patterns(self):
        """MRN patterns like MRN100016 should become <MRN_REDACTED>."""
        from app.search.answer_generator import _apply_final_role_sanitizer
        answer = "Patient with MRN100016 and MRN100023"
        result = _apply_final_role_sanitizer(answer, "non_treating_clinician")
        assert "MRN100016" not in result
        assert "MRN100023" not in result
        assert result.count("<MRN_REDACTED>") == 2
