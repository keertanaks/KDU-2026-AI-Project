"""
Tests for ExtractionValidator.

All tests are pure unit tests — no DB, no OpenSearch, no file I/O.
The Emily Moore raw text is inlined exactly as PyMuPDF extracts it.
"""

from app.ingestion.extraction_validator import ExtractionValidator

# ---------------------------------------------------------------------------
# Emily Moore prescription — raw PyMuPDF output (table structure lost)
# ---------------------------------------------------------------------------

EMILY_MOORE_RAW = (
    "Mercy General Hospital\n"
    "123 Health Plaza, Medical City, CA 90210\n"
    "Prescription (Rx)\n"
    "Patient Information\n"
    "Date and MRN\n"
    "Name:\n"
    "Emily Moore\n"
    "Date:\n"
    "2025-04-22\n"
    "Age:\n"
    "52\n"
    "MRN:\n"
    "MRN100003\n"
    "Diagnosis:\n"
    "Asthma (ICD: J45)\n"
    "Prescribed Medications:\n"
    "Medication\n"
    "Dosage\n"
    "Frequency\n"
    "1. Albuterol inhaler\n"
    "2 puffs\n"
    "Every 4-6 hours as needed for \n"
    "2. Fluticasone and Salmet\n"
    "1 puff\n"
    "Twice daily\n"
    "3. Montelukast\n"
    "10mg\n"
    "1 tablet daily\n"
    "Patient Instructions:\n"
    "Hi Emily,\n"
    "1. Remember to take your medication as prescribed by Dr. Thompson.\n"
    "2. Watch out for potential side effects.\n"
    "3. Contact Dr. Thompson if you have concerns.\n"
    "Prescribing Physician: Dr. David Thompson\n"
    "Signature: _________________________\n"
    "Date: 2025-04-22\n"
    "Page 1\n"
)

# A clean normalised Markdown prescription (no known issues)
CLEAN_PRESCRIPTION_MD = (
    "# Prescription\n\n"
    "Patient: John Smith\n"
    "MRN: MRN001\n"
    "Date: 2025-01-01\n"
    "Diagnosis: Hypertension (ICD: I10)\n"
    "Prescribing Physician: Dr. Jane Doe\n\n"
    "## Medications\n\n"
    "| Medication | Dosage | Frequency |\n"
    "|---|---|---|\n"
    "| Lisinopril | 10mg | Once daily |\n"
)


# ---------------------------------------------------------------------------
# Emily Moore raw — prescription-specific issues
# ---------------------------------------------------------------------------

class TestValidatorEmilyMooreRaw:
    def test_needs_review_is_true(self):
        result = ExtractionValidator.validate(EMILY_MOORE_RAW, "prescription")
        assert result["needs_review"] is True

    def test_flags_incomplete_frequency(self):
        result = ExtractionValidator.validate(EMILY_MOORE_RAW, "prescription")
        assert "incomplete_frequency" in result["issues"]

    def test_flags_truncated_medication_name(self):
        result = ExtractionValidator.validate(EMILY_MOORE_RAW, "prescription")
        assert "truncated_medication_name" in result["issues"]

    def test_flags_flattened_table_header(self):
        result = ExtractionValidator.validate(EMILY_MOORE_RAW, "prescription")
        assert "flattened_table_header" in result["issues"]

    def test_quality_score_below_085(self):
        result = ExtractionValidator.validate(EMILY_MOORE_RAW, "prescription")
        assert result["quality_score"] < 0.85

    def test_quality_score_is_float(self):
        result = ExtractionValidator.validate(EMILY_MOORE_RAW, "prescription")
        assert isinstance(result["quality_score"], float)

    def test_recommended_fallback_is_normalize(self):
        result = ExtractionValidator.validate(EMILY_MOORE_RAW, "prescription")
        assert result["recommended_fallback"] == "normalize"

    def test_no_missing_field_issues(self):
        result = ExtractionValidator.validate(EMILY_MOORE_RAW, "prescription")
        missing = [i for i in result["issues"] if i.startswith("missing_")]
        assert missing == [], f"unexpected missing fields: {missing}"


# ---------------------------------------------------------------------------
# Clean normalised Markdown — should pass
# ---------------------------------------------------------------------------

class TestValidatorCleanPrescription:
    def test_quality_score_at_least_085(self):
        result = ExtractionValidator.validate(CLEAN_PRESCRIPTION_MD, "prescription")
        assert result["quality_score"] >= 0.85

    def test_needs_review_false(self):
        result = ExtractionValidator.validate(CLEAN_PRESCRIPTION_MD, "prescription")
        assert result["needs_review"] is False

    def test_no_issues(self):
        result = ExtractionValidator.validate(CLEAN_PRESCRIPTION_MD, "prescription")
        assert result["issues"] == []

    def test_recommended_fallback_is_none(self):
        result = ExtractionValidator.validate(CLEAN_PRESCRIPTION_MD, "prescription")
        assert result["recommended_fallback"] is None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestValidatorEdgeCases:
    def test_empty_text_score_zero(self):
        result = ExtractionValidator.validate("", "prescription")
        assert result["quality_score"] == 0.0

    def test_empty_text_needs_review(self):
        result = ExtractionValidator.validate("", "prescription")
        assert result["needs_review"] is True

    def test_empty_text_issue_is_empty_text(self):
        result = ExtractionValidator.validate("", "prescription")
        assert "empty_text" in result["issues"]

    def test_empty_text_fallback_is_manual_review(self):
        result = ExtractionValidator.validate("", "prescription")
        assert result["recommended_fallback"] == "manual_review"

    def test_non_prescription_no_prescription_issues(self):
        text = "Patient came in with chest pain. EKG normal. Discharged after observation."
        result = ExtractionValidator.validate(text, "clinical_note")
        assert "incomplete_frequency" not in result["issues"]
        assert "flattened_table_header" not in result["issues"]
        assert "truncated_medication_name" not in result["issues"]

    def test_whitespace_only_text_empty(self):
        result = ExtractionValidator.validate("   \n\n  ", "prescription")
        assert result["quality_score"] == 0.0

    def test_doc_type_none_still_runs_on_prescription_signals(self):
        # Text contains "Prescription (Rx)" — validator should still apply checks
        result = ExtractionValidator.validate(EMILY_MOORE_RAW, None)
        assert "incomplete_frequency" in result["issues"]

    def test_result_has_all_required_keys(self):
        result = ExtractionValidator.validate(EMILY_MOORE_RAW, "prescription")
        assert set(result.keys()) == {
            "quality_score", "needs_review", "issues", "recommended_fallback"
        }
