"""
Tests for MedicalDocumentNormalizer.

All tests are pure unit tests — no file I/O, no DB, no OpenSearch.
Tables are the exact rows pdfplumber returns from the Emily Moore PDF.
"""

from app.ingestion.normalizer import MedicalDocumentNormalizer

# ---------------------------------------------------------------------------
# Fixtures
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

# Exact pdfplumber output from the Emily Moore PDF
EMILY_TABLES = [
    [
        ["Patient Information", None, "Date and MRN", None],
        ["Name:", "Emily Moore", "Date:", "2025-04-22"],
        ["Age:", "52", "MRN:", "MRN100003"],
        ["Diagnosis:", "Asthma (ICD: J45)", None, None],
    ],
    [
        ["Medication", "Dosage", "Frequency"],
        ["1. Albuterol inhaler", "2 puffs", "Every 4-6 hours as needed for"],
        ["2. Fluticasone and Salmet", "1 puff", "Twice daily"],
        ["3. Montelukast", "10mg", "1 tablet daily"],
    ],
]


# ---------------------------------------------------------------------------
# Prescription normalisation with pdfplumber tables (primary path)
# ---------------------------------------------------------------------------

class TestNormalizerPrescriptionWithTables:
    def _result(self):
        return MedicalDocumentNormalizer.normalize(
            EMILY_MOORE_RAW, "prescription", EMILY_TABLES
        )

    def test_normalization_applied_true(self):
        assert self._result()["normalization_applied"] is True

    def test_normalized_format_is_markdown(self):
        assert self._result()["normalized_format"] == "markdown"

    def test_albuterol_row_in_output(self):
        text = self._result()["normalized_text"]
        assert "Albuterol inhaler | 2 puffs | Every 4-6 hours as needed" in text

    def test_fluticasone_name_corrected(self):
        text = self._result()["normalized_text"]
        assert "Fluticasone and Salmeterol | 1 puff | Twice daily" in text

    def test_montelukast_row_in_output(self):
        text = self._result()["normalized_text"]
        assert "Montelukast | 10mg | 1 tablet daily" in text

    def test_truncated_frequency_fixed(self):
        # "as needed for" → "as needed" (trailing 'for' removed)
        text = self._result()["normalized_text"]
        assert "as needed for" not in text
        assert "as needed" in text

    def test_structured_fields_patient(self):
        assert self._result()["structured_fields"]["patient"] == "Emily Moore"

    def test_structured_fields_mrn(self):
        assert self._result()["structured_fields"]["mrn"] == "MRN100003"

    def test_structured_fields_date(self):
        assert self._result()["structured_fields"]["date"] == "2025-04-22"

    def test_structured_fields_diagnosis(self):
        assert "Asthma" in self._result()["structured_fields"]["diagnosis"]

    def test_structured_fields_physician(self):
        assert "David Thompson" in self._result()["structured_fields"]["physician"]

    def test_structured_fields_three_medications(self):
        meds = self._result()["structured_fields"]["medications"]
        assert len(meds) == 3

    def test_structured_fields_medication_names(self):
        meds = self._result()["structured_fields"]["medications"]
        names = [m["name"] for m in meds]
        assert any("Albuterol" in n for n in names)
        assert any("Salmeterol" in n for n in names)
        assert any("Montelukast" in n for n in names)

    def test_hospital_in_output(self):
        text = self._result()["normalized_text"]
        assert "Mercy General Hospital" in text

    def test_no_raw_table_header_in_output(self):
        text = self._result()["normalized_text"]
        # The flattened "Medication\nDosage\nFrequency" pattern must not appear
        import re
        assert not re.search(r"Medication\s+Dosage\s+Frequency", text)

    def test_instructions_present(self):
        text = self._result()["normalized_text"]
        assert "## Patient Instructions" in text or "Patient Instructions" in text


# ---------------------------------------------------------------------------
# Prescription normalisation without tables (regex fallback)
# ---------------------------------------------------------------------------

class TestNormalizerPrescriptionNoTables:
    def _result(self):
        return MedicalDocumentNormalizer.normalize(
            EMILY_MOORE_RAW, "prescription", []
        )

    def test_normalization_applied_true(self):
        assert self._result()["normalization_applied"] is True

    def test_medications_extracted(self):
        meds = self._result()["structured_fields"]["medications"]
        assert len(meds) >= 1

    def test_albuterol_present(self):
        meds = self._result()["structured_fields"]["medications"]
        names = [m["name"] for m in meds]
        assert any("Albuterol" in n for n in names)


# ---------------------------------------------------------------------------
# Non-prescription doc types — must pass through unchanged
# ---------------------------------------------------------------------------

class TestNormalizerNonPrescription:
    def test_clinical_note_not_normalized(self):
        text = "Patient presents with chest pain. EKG normal. Discharged."
        result = MedicalDocumentNormalizer.normalize(text, "clinical_note", [])
        assert result["normalization_applied"] is False

    def test_clinical_note_text_unchanged(self):
        text = "Patient presents with chest pain. EKG normal. Discharged."
        result = MedicalDocumentNormalizer.normalize(text, "clinical_note", [])
        assert result["normalized_text"] == text

    def test_clinical_note_format_plain(self):
        text = "Patient presents with chest pain."
        result = MedicalDocumentNormalizer.normalize(text, "clinical_note", [])
        assert result["normalized_format"] == "plain"

    def test_lab_report_not_normalized(self):
        text = "Hemoglobin: 13.5 result normal range 12-16 flag none"
        result = MedicalDocumentNormalizer.normalize(text, "lab_report", [])
        assert result["normalization_applied"] is False

    def test_structured_fields_empty_for_non_prescription(self):
        text = "Patient with normal vitals."
        result = MedicalDocumentNormalizer.normalize(text, "clinical_note", [])
        assert result["structured_fields"] == {}


# ---------------------------------------------------------------------------
# Return dict contract
# ---------------------------------------------------------------------------

class TestNormalizerReturnContract:
    def test_all_required_keys_present(self):
        result = MedicalDocumentNormalizer.normalize(
            EMILY_MOORE_RAW, "prescription", EMILY_TABLES
        )
        assert set(result.keys()) == {
            "normalized_text",
            "normalized_format",
            "structured_fields",
            "normalization_applied",
        }

    def test_normalized_text_is_string(self):
        result = MedicalDocumentNormalizer.normalize(
            EMILY_MOORE_RAW, "prescription", EMILY_TABLES
        )
        assert isinstance(result["normalized_text"], str)

    def test_normalized_text_non_empty(self):
        result = MedicalDocumentNormalizer.normalize(
            EMILY_MOORE_RAW, "prescription", EMILY_TABLES
        )
        assert len(result["normalized_text"].strip()) > 0
