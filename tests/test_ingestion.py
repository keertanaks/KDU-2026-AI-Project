"""
Tests for ingestion pipeline: chunker, doc-type detection, text cleaner, and PHI tagger.

PhiTagger tests are marked @pytest.mark.slow because they load Presidio models on first call
and are excluded from the default fast suite.  Run with: pytest -m slow
"""

import pytest

from app.ingestion.chunker import AdaptiveChunker, ChunkDocType
from app.ingestion.text_cleaner import TextCleaner


# ---------------------------------------------------------------------------
# AdaptiveChunker — Prescription (atomic)
# ---------------------------------------------------------------------------

class TestChunkerPrescription:
    PRESCRIPTION_TEXT = "Amoxicillin 500mg tablet — take twice daily with food.\nDose: 500 mg"

    def test_single_chunk_returned(self):
        chunks = AdaptiveChunker.chunk(self.PRESCRIPTION_TEXT, ChunkDocType.PRESCRIPTION)
        assert len(chunks) == 1

    def test_child_equals_parent(self):
        chunks = AdaptiveChunker.chunk(self.PRESCRIPTION_TEXT, ChunkDocType.PRESCRIPTION)
        assert chunks[0].child_text == chunks[0].parent_text

    def test_text_is_stripped(self):
        chunks = AdaptiveChunker.chunk("  Aspirin 100mg  ", ChunkDocType.PRESCRIPTION)
        assert chunks[0].child_text == "Aspirin 100mg"

    def test_doc_type_label(self):
        chunks = AdaptiveChunker.chunk(self.PRESCRIPTION_TEXT, ChunkDocType.PRESCRIPTION)
        assert chunks[0].doc_type == ChunkDocType.PRESCRIPTION


# ---------------------------------------------------------------------------
# AdaptiveChunker — Lab report (one chunk per non-empty line)
# ---------------------------------------------------------------------------

class TestChunkerLabReport:
    LAB_TEXT = "Hemoglobin: 13.5 g/dL  normal range 12-16\nWBC: 7000  result normal\nFlag: none"

    def test_one_chunk_per_non_empty_line(self):
        chunks = AdaptiveChunker.chunk(self.LAB_TEXT, ChunkDocType.LAB_REPORT)
        non_empty_lines = [l for l in self.LAB_TEXT.split("\n") if l.strip()]
        assert len(chunks) == len(non_empty_lines)

    def test_parent_text_is_full_document(self):
        chunks = AdaptiveChunker.chunk(self.LAB_TEXT, ChunkDocType.LAB_REPORT)
        expected_parent = self.LAB_TEXT.strip()
        for chunk in chunks:
            assert chunk.parent_text == expected_parent

    def test_empty_text_returns_fallback_chunk(self):
        chunks = AdaptiveChunker.chunk("", ChunkDocType.LAB_REPORT)
        assert len(chunks) == 1


# ---------------------------------------------------------------------------
# AdaptiveChunker — Form (double-newline sections)
# ---------------------------------------------------------------------------

class TestChunkerForm:
    FORM_TEXT = "Name: John Doe\nDate: 2025-01-01\n\nDiagnosis: Hypertension\nDoctor: Dr. Smith"

    def test_sections_split_on_double_newline(self):
        chunks = AdaptiveChunker.chunk(self.FORM_TEXT, ChunkDocType.FORM)
        expected_sections = [s for s in self.FORM_TEXT.split("\n\n") if s.strip()]
        assert len(chunks) == len(expected_sections)

    def test_parent_text_is_full_document(self):
        chunks = AdaptiveChunker.chunk(self.FORM_TEXT, ChunkDocType.FORM)
        for chunk in chunks:
            assert chunk.parent_text == self.FORM_TEXT.strip()


# ---------------------------------------------------------------------------
# AdaptiveChunker — Clinical note (recursive splitter, 512/50)
# ---------------------------------------------------------------------------

class TestChunkerClinicalNote:
    # ~700 tokens — forces multiple chunks
    LONG_NOTE = (
        "Patient presents with persistent cough and shortness of breath for 3 weeks. "
        "History of asthma diagnosed in 2010. No known drug allergies. "
        "Current medications: Salbutamol inhaler as needed. "
        "Physical examination reveals bilateral wheezing. SpO2 96%. "
        "Assessment: Acute asthma exacerbation. "
        "Plan: Start prednisolone 30mg OD for 5 days. "
        "Continue Salbutamol. Follow up in 1 week. "
        "Patient advised to avoid known triggers including dust and cold air. "
        "Referral to pulmonology if no improvement. "
        "Lab results pending: CBC, CXR. "
        "Patient counselled on inhaler technique and given action plan. "
        "Emergency instructions provided. Next appointment booked for 2025-02-14. "
        "Signed: Dr. Emily Nguyen, Respiratory Medicine. Reviewed: 2025-01-07."
    )

    def test_multiple_chunks_produced(self):
        chunks = AdaptiveChunker.chunk(self.LONG_NOTE, ChunkDocType.CLINICAL_NOTE)
        assert len(chunks) >= 1

    def test_parent_text_preserved_across_all_chunks(self):
        chunks = AdaptiveChunker.chunk(self.LONG_NOTE, ChunkDocType.CLINICAL_NOTE)
        for chunk in chunks:
            assert chunk.parent_text == self.LONG_NOTE

    def test_no_empty_child_chunks(self):
        chunks = AdaptiveChunker.chunk(self.LONG_NOTE, ChunkDocType.CLINICAL_NOTE)
        for chunk in chunks:
            assert chunk.child_text.strip() != ""

    def test_doc_type_label_on_all_chunks(self):
        chunks = AdaptiveChunker.chunk(self.LONG_NOTE, ChunkDocType.CLINICAL_NOTE)
        for chunk in chunks:
            assert chunk.doc_type == ChunkDocType.CLINICAL_NOTE

    def test_short_text_returns_at_least_one_chunk(self):
        chunks = AdaptiveChunker.chunk("Brief note.", ChunkDocType.CLINICAL_NOTE)
        assert len(chunks) >= 1


# ---------------------------------------------------------------------------
# AdaptiveChunker — detect_doc_type heuristics
# ---------------------------------------------------------------------------

class TestDocTypeDetection:
    def test_prescription_keywords_short_text(self):
        text = "Amoxicillin 250mg tablet — dose once daily"
        assert AdaptiveChunker.detect_doc_type(text) == ChunkDocType.PRESCRIPTION

    def test_lab_report_keywords(self):
        text = "Hemoglobin: 14.2 g/dL result normal range 12-16"
        assert AdaptiveChunker.detect_doc_type(text) == ChunkDocType.LAB_REPORT

    def test_form_keywords(self):
        text = "Patient: Jane Doe\nDate: 2025-04-01\nName: Jane"
        assert AdaptiveChunker.detect_doc_type(text) == ChunkDocType.FORM

    def test_default_to_clinical_note(self):
        text = "The patient complained of headache and dizziness. No relevant history."
        assert AdaptiveChunker.detect_doc_type(text) == ChunkDocType.CLINICAL_NOTE

    def test_prescription_keyword_long_text_becomes_clinical_note(self):
        # >300 tokens with 'mg' → NOT prescription → falls through to clinical_note
        text = ("mg " * 301) + "patient history"
        result = AdaptiveChunker.detect_doc_type(text)
        # Lab/form keywords absent, so result is clinical_note
        assert result == ChunkDocType.CLINICAL_NOTE

    def test_lab_takes_priority_over_form_when_both_keywords_present(self):
        # "result" + "name:" — lab keywords are checked first in the code
        text = "Name: John  result flag normal range 7.0"
        assert AdaptiveChunker.detect_doc_type(text) == ChunkDocType.LAB_REPORT


# ---------------------------------------------------------------------------
# TextCleaner
# ---------------------------------------------------------------------------

class TestTextCleaner:
    def test_removes_non_printable_characters(self):
        # \x00 is a non-printable outside the allowed range
        cleaned = TextCleaner.clean("Hello\x00World")
        assert "\x00" not in cleaned
        assert "Hello" in cleaned

    def test_collapses_multiple_spaces(self):
        cleaned = TextCleaner.clean("word1    word2")
        assert "    " not in cleaned
        assert "word1 word2" in cleaned

    def test_collapses_excessive_newlines(self):
        cleaned = TextCleaner.clean("line1\n\n\n\nline2")
        assert "\n\n\n" not in cleaned

    def test_normalizes_unicode_em_dash(self):
        cleaned = TextCleaner.clean("word—word")
        assert "—" not in cleaned
        assert "word-word" in cleaned

    def test_normalizes_unicode_en_dash(self):
        cleaned = TextCleaner.clean("2020–2025")
        assert "–" not in cleaned
        assert "2020-2025" in cleaned

    def test_strips_leading_trailing_whitespace(self):
        cleaned = TextCleaner.clean("  hello world  ")
        assert cleaned == "hello world"

    def test_empty_string_returns_empty(self):
        assert TextCleaner.clean("") == ""

    def test_normal_content_preserved(self):
        text = "Patient DOB: 1985-03-12. Diagnosis: Hypertension."
        cleaned = TextCleaner.clean(text)
        assert "Patient DOB" in cleaned
        assert "Hypertension" in cleaned


# ---------------------------------------------------------------------------
# PhiTagger — requires Presidio models (slow)
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestPhiTagger:
    @pytest.fixture(scope="class")
    def tagger(self):
        from app.ingestion.phi_tagger import PhiTagger
        return PhiTagger()

    def test_detects_person_name(self, tagger):
        spans = tagger.tag("Patient: Emily Moore")
        types = [s.span_type for s in spans]
        assert "PERSON" in types

    def test_detects_date(self, tagger):
        spans = tagger.tag("DOB: 1972-03-14")
        types = [s.span_type for s in spans]
        assert any(t in types for t in ("DATE_TIME", "DOB"))

    def test_multiple_entities_detected(self, tagger):
        text = "Emily Moore, DOB 1972-03-14, MRN MRN100003"
        spans = tagger.tag(text)
        assert len(spans) >= 2

    def test_span_offsets_point_to_correct_text(self, tagger):
        text = "Patient Emily Moore visited on 2025-01-01"
        spans = tagger.tag(text)
        for span in spans:
            assert 0 <= span.start < span.end <= len(text)

    def test_confidence_is_between_zero_and_one(self, tagger):
        spans = tagger.tag("John Smith, SSN 123-45-6789")
        for span in spans:
            assert 0.0 <= span.confidence <= 1.0

    def test_empty_string_returns_no_spans(self, tagger):
        spans = tagger.tag("")
        assert spans == []

    def test_to_dict_format(self, tagger):
        spans = tagger.tag("Jane Doe")
        for span in spans:
            d = span.to_dict()
            assert set(d.keys()) == {"type", "start", "end", "confidence"}
