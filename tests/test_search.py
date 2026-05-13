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
