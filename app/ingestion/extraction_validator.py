"""
Post-extraction quality validator for ingested medical documents.

Scores the raw text coming out of OCR/PyMuPDF and flags known issues so
downstream components can decide whether to attempt normalization.

Prescription-specific checks:
  - incomplete_frequency  : line ends with "as needed for" (text cut off)
  - truncated_medication_name : known medication name fragments ("Salmet")
  - flattened_table_header    : table header collapsed to plain line
  - missing_<field>           : expected field absent from text

Score thresholds (returned as quality_score):
  >= 0.85  → ok, no action required
  0.65–0.85 → index but mark needs_review=True
  < 0.65  → normalization strongly recommended + needs_review=True
"""

import re
from typing import Dict, List, Optional

# --- prescription pattern library -------------------------------------------

_TRUNCATED_FREQ_RE = re.compile(
    r"as needed for\s*$", re.IGNORECASE | re.MULTILINE
)

# Medication name fragments that indicate PDF-level truncation.
# Pattern asserts the known prefix is NOT followed by the expected suffix.
_TRUNCATED_MED_PATTERNS: List[re.Pattern] = [
    re.compile(r"Fluticasone and Salmet\b(?!erol)", re.IGNORECASE),
    re.compile(r"\bSalmet\b(?!erol)", re.IGNORECASE),
]

# Table header printed as three consecutive lines/tokens (structure lost).
_FLAT_HEADER_RE = re.compile(
    r"Medication\s+Dosage\s+Frequency", re.IGNORECASE
)

# Lightweight presence checks for required prescription fields.
# Matching the label is enough — value appears on the next line in raw text
# and on the same line in normalised Markdown.
_FIELD_CHECKS: Dict[str, re.Pattern] = {
    "name":       re.compile(r"(Name\s*:|Patient\s*:)",          re.IGNORECASE),
    "mrn":        re.compile(r"MRN",                              re.IGNORECASE),
    "date":       re.compile(r"Date\s*:",                         re.IGNORECASE),
    "diagnosis":  re.compile(r"Diagnosis\s*:",                    re.IGNORECASE),
    "medication": re.compile(r"(\d+\.\s+\w|\|\s*\w|Medication)",  re.IGNORECASE),
    "dosage":     re.compile(r"(\d+\s*(mg|puff|tablet|capsule|ml)|Dosage)", re.IGNORECASE),
    "frequency":  re.compile(r"(daily|twice|three times|every|as needed|Frequency)", re.IGNORECASE),
    "physician":  re.compile(r"(Physician|Dr\.)",                  re.IGNORECASE),
}

# Signals that make an untyped doc look like a prescription.
_PRESCRIPTION_SIGNALS: List[re.Pattern] = [
    re.compile(r"(tablet|puff|capsule|Prescription\s*\(Rx\)|Prescribed Medications)", re.IGNORECASE),
]


def _is_prescription(text: str, doc_type: Optional[str]) -> bool:
    if doc_type and "prescription" in doc_type.lower():
        return True
    return any(p.search(text) for p in _PRESCRIPTION_SIGNALS)


class ExtractionValidator:
    """Score raw or normalised text for extraction quality."""

    @staticmethod
    def validate(text: str, doc_type: Optional[str] = None) -> dict:
        """
        Returns:
            quality_score        float  0.0–1.0
            needs_review         bool
            issues               list[str]
            recommended_fallback str | None  ("normalize" | "manual_review" | None)
        """
        if not text or not text.strip():
            return {
                "quality_score": 0.0,
                "needs_review": True,
                "issues": ["empty_text"],
                "recommended_fallback": "manual_review",
            }

        issues: List[str] = []
        score = 1.0

        if _is_prescription(text, doc_type):
            # Penalty: truncated frequency
            if _TRUNCATED_FREQ_RE.search(text):
                issues.append("incomplete_frequency")
                score -= 0.15

            # Penalty: truncated medication name
            for pattern in _TRUNCATED_MED_PATTERNS:
                if pattern.search(text):
                    issues.append("truncated_medication_name")
                    score -= 0.10
                    break

            # Penalty: table structure collapsed to flat lines
            if _FLAT_HEADER_RE.search(text):
                issues.append("flattened_table_header")
                score -= 0.10

            # Penalty: missing expected fields
            missing = [
                name for name, pattern in _FIELD_CHECKS.items()
                if not pattern.search(text)
            ]
            for field in missing:
                issues.append(f"missing_{field}")
            score -= 0.05 * len(missing)

        score = max(0.0, round(score, 3))
        needs_review = score < 0.85
        recommended_fallback = "normalize" if needs_review else None
        if "empty_text" in issues:
            recommended_fallback = "manual_review"

        return {
            "quality_score": score,
            "needs_review": needs_review,
            "issues": issues,
            "recommended_fallback": recommended_fallback,
        }
