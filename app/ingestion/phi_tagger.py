import re
from typing import List

from presidio_analyzer import AnalyzerEngine

# ---------------------------------------------------------------------------
# Post-filter allowlists — spans matching these are dropped after Presidio runs.
# ---------------------------------------------------------------------------

# Drug/medication names commonly misidentified as PERSON or LOCATION by Presidio.
# Include common OCR truncations (e.g. "Salmet" for "Salmeterol").
_MEDICATION_ALLOWLIST = {
    "albuterol",
    "fluticasone",
    "salmeterol",
    "salmet",        # OCR truncation of salmeterol
    "montelukast",
    "gabapentin",
    "tramadol",
    "celecoxib",
    "lisinopril",
    "metformin",
    "atorvastatin",
    "omeprazole",
    "amoxicillin",
    "azithromycin",
    "prednisone",
    "sertraline",
    "escitalopram",
    "pioglitazone",
    "glimepiride",
    "empagliflozin",
}

# Frequency/dosing words commonly misidentified as DATE_TIME by Presidio.
_DATE_FALSE_POSITIVES = {
    "daily",
    "twice daily",
    "twice",
    "three times daily",
    "four times daily",
    "as needed",
    "as needed for",
    "once daily",
    "every day",
    "every night",
    "nightly",
    "weekly",
    "monthly",
    "bedtime",
    "morning",
    "evening",
    "noon",
}

# Dosing interval patterns: "4-6 hours", "every 6 hours", "q8h", etc.
_DOSING_INTERVAL_RE = re.compile(
    r"^(every\s+)?(\d+(-\d+)?)\s*(hours?|hrs?|minutes?|mins?|days?|weeks?)$",
    re.IGNORECASE,
)

# ICD-10 code pattern — single letter followed by 2+ digits, e.g. J45, E11, R52.
# Presidio sometimes tags these as LOCATION.
_ICD_RE = re.compile(r"^[A-Z]\d{2}(\.\d+)?$")


def _is_medication(text: str) -> bool:
    return text.strip().lower() in _MEDICATION_ALLOWLIST


def _is_date_false_positive(text: str) -> bool:
    t = text.strip()
    if t.lower() in _DATE_FALSE_POSITIVES:
        return True
    return bool(_DOSING_INTERVAL_RE.match(t))


def _is_icd_code(text: str) -> bool:
    return bool(_ICD_RE.match(text.strip()))


class PhiSpan:
    def __init__(self, span_type: str, start: int, end: int, confidence: float):
        self.span_type = span_type
        self.start = start
        self.end = end
        self.confidence = confidence

    def to_dict(self) -> dict:
        return {
            "type": self.span_type,
            "start": self.start,
            "end": self.end,
            "confidence": self.confidence,
        }


class PhiTagger:
    def __init__(self):
        self.analyzer = AnalyzerEngine()

    def tag(self, text: str) -> List[PhiSpan]:
        """
        Detect HIPAA identifiers using Presidio, then post-filter known false
        positives before returning spans.

        Post-filter rules (applied in order):
          1. PERSON or LOCATION span whose text is a known medication → drop.
          2. DATE_TIME span whose text is a dosing/frequency word or interval → drop.
          3. LOCATION span whose text matches an ICD-10 code pattern → drop.
        """
        results = self.analyzer.analyze(text=text, language="en")

        spans: List[PhiSpan] = []
        for r in results:
            matched = text[r.start:r.end]

            if r.entity_type in ("PERSON", "LOCATION") and _is_medication(matched):
                continue
            if r.entity_type == "DATE_TIME" and _is_date_false_positive(matched):
                continue
            if r.entity_type == "LOCATION" and _is_icd_code(matched):
                continue

            spans.append(PhiSpan(r.entity_type, r.start, r.end, r.score))

        return spans
