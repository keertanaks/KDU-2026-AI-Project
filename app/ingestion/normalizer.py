"""
Structured Markdown normalizer for medical documents.

Current support: prescription documents.
Other doc types are returned unchanged (normalization_applied=False).

Prescription normalization strategy:
  1. Use pdfplumber table rows when available (primary path for typed PDFs).
  2. Fall back to regex parsing of raw text when no tables are found.
  3. Apply known medication name corrections (PDF-level truncations).
  4. Fix truncated frequency strings ("as needed for " → "as needed").
  5. Extract patient instructions from the raw text body.
  6. Emit structured Markdown with patient header + medication table + instructions.
"""

import re
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Correction maps (PDF-level truncations we can deterministically fix)
# ---------------------------------------------------------------------------

_MED_NAME_FIXES: Dict[str, str] = {
    "Fluticasone and Salmet": "Fluticasone and Salmeterol",
}

_FREQ_TRAILING_FOR = re.compile(r"\bas needed for\s*$", re.IGNORECASE)
_FREQ_TRAILING_NEED = re.compile(r"\bas need\s*$", re.IGNORECASE)

_GREETING_RE = re.compile(r"^(hi|hello|dear)\b", re.IGNORECASE)


def _fix_med_name(name: str) -> str:
    for bad, good in _MED_NAME_FIXES.items():
        if bad.lower() in name.lower():
            name = re.sub(re.escape(bad), good, name, flags=re.IGNORECASE)
    return name.strip()


def _fix_frequency(freq: str) -> str:
    freq = _FREQ_TRAILING_FOR.sub("as needed", freq)
    freq = _FREQ_TRAILING_NEED.sub("as needed", freq)
    return freq.strip()


# ---------------------------------------------------------------------------
# Regex helpers for raw-text fallback parsing
# ---------------------------------------------------------------------------

_FIELD_RE: Dict[str, re.Pattern] = {
    "patient":   re.compile(r"Name\s*:\s*\n?(.+)",        re.IGNORECASE),
    "date":      re.compile(r"Date\s*:\s*\n?(\d{4}-\d{2}-\d{2})", re.IGNORECASE),
    "age":       re.compile(r"Age\s*:\s*\n?(\d+)",         re.IGNORECASE),
    "mrn":       re.compile(r"MRN\s*:\s*\n?(\S+)",         re.IGNORECASE),
    "diagnosis": re.compile(r"Diagnosis\s*:\s*\n?(.+)",    re.IGNORECASE),
    "physician": re.compile(r"Prescribing Physician\s*:\s*(.+)", re.IGNORECASE),
}

_NUMBERED_MED_RE = re.compile(r"^\d+\.\s+(.+)$", re.MULTILINE)
_INSTRUCTIONS_RE = re.compile(
    r"Patient Instructions?\s*:(.*?)(?:Prescribing Physician|Signature\s*:|Page \d)",
    re.DOTALL | re.IGNORECASE,
)
_HOSPITAL_RE = re.compile(r"^(.+(Hospital|Clinic|Medical Center|Health[^\n]*?)(?:\s*\n|$))", re.IGNORECASE)


def _extract_field(text: str, key: str) -> str:
    m = _FIELD_RE[key].search(text)
    return m.group(1).strip() if m else ""


def _extract_hospital(text: str) -> str:
    """Extract facility name and address (e.g., 'Mayo Clinic Northwest, 654 Wellness Circle, ...')."""
    lines = text.split('\n')
    for i, line in enumerate(lines):
        m = _HOSPITAL_RE.search(line)
        if m:
            facility = line.strip()
            # If next line looks like an address, include it
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line and not next_line[0].isupper() and any(c.isdigit() for c in next_line):
                    facility += ", " + next_line
            return facility
    return ""


def _extract_instructions(text: str) -> List[str]:
    m = _INSTRUCTIONS_RE.search(text)
    if not m:
        return []
    body = m.group(1).strip()

    raw_lines = [l.strip() for l in body.splitlines() if l.strip()]

    has_numbered = any(re.match(r"^\d+\.", l) for l in raw_lines)

    if has_numbered:
        # Join wrapped continuation lines onto their numbered parent
        merged: List[str] = []
        for line in raw_lines:
            if _GREETING_RE.match(line) or line.lower().startswith(("take care", "[your")):
                continue
            is_new = bool(re.match(r"^\d+\.", line))
            if is_new or not merged:
                merged.append(re.sub(r"^\d+\.\s*", "", line))
            else:
                merged[-1] = merged[-1].rstrip() + " " + line
        return [l for l in merged if l]

    # Unnumbered block — split on sentence boundaries (period/!/? followed by space+capital)
    filtered = " ".join(
        l for l in raw_lines
        if not _GREETING_RE.match(l) and not l.lower().startswith(("take care", "[your"))
    )
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", filtered)
    return [s.strip() for s in sentences if s.strip()]


# ---------------------------------------------------------------------------
# Table parsing helpers (pdfplumber output)
# ---------------------------------------------------------------------------

def _find_patient_table(tables: list) -> Optional[list]:
    """Return the first table that looks like a patient-info table."""
    for table in tables:
        if not table:
            continue
        flat = " ".join(str(c) for row in table for c in row if c)
        if re.search(r"Name|MRN|Diagnosis", flat, re.IGNORECASE):
            return table
    return None


def _find_medication_table(tables: list) -> Optional[list]:
    """Return the first table whose first row contains Medication/Dosage/Frequency."""
    for table in tables:
        if not table:
            continue
        header = " ".join(str(c) for c in table[0] if c)
        if re.search(r"Medication", header, re.IGNORECASE):
            return table
    return None


def _parse_patient_info_from_table(table: list) -> Dict[str, str]:
    info: Dict[str, str] = {}
    for row in table:
        for i in range(0, len(row) - 1, 2):
            label = str(row[i] or "").strip().rstrip(":")
            value = str(row[i + 1] or "").strip() if i + 1 < len(row) else ""
            if not label or not value or value == "None":
                continue
            key = label.lower()
            if "name" in key:
                info["patient"] = value
            elif "date" in key:
                info["date"] = value
            elif "age" in key:
                info["age"] = value
            elif "mrn" in key:
                info["mrn"] = value
            elif "diagnosis" in key:
                info["diagnosis"] = value
    return info


def _parse_medications_from_table(table: list) -> List[Dict[str, str]]:
    meds: List[Dict[str, str]] = []
    # Skip header row (first row)
    for row in table[1:]:
        if not row or all(c is None for c in row):
            continue
        cells = [str(c or "").strip() for c in row]
        if len(cells) < 3:
            continue
        name = re.sub(r"^\d+\.\s*", "", cells[0]).strip()
        dosage = cells[1]
        frequency = cells[2] if len(cells) > 2 else ""
        if name:
            meds.append({
                "name":      _fix_med_name(name),
                "dosage":    dosage,
                "frequency": _fix_frequency(frequency),
            })
    return meds


# ---------------------------------------------------------------------------
# Fallback: parse medications from raw text lines
# ---------------------------------------------------------------------------

def _parse_medications_from_text(text: str) -> List[Dict[str, str]]:
    """
    Numbered medication items in raw text appear as three consecutive lines:
      1. Medication Name
      Dosage
      Frequency
    This is fragile but is the only option when pdfplumber finds no tables.
    """
    lines = [l.strip() for l in text.splitlines()]
    meds: List[Dict[str, str]] = []
    i = 0
    while i < len(lines):
        m = re.match(r"^\d+\.\s+(.+)$", lines[i])
        if m:
            name = _fix_med_name(m.group(1))
            dosage = lines[i + 1] if i + 1 < len(lines) else ""
            frequency = _fix_frequency(lines[i + 2]) if i + 2 < len(lines) else ""
            meds.append({"name": name, "dosage": dosage, "frequency": frequency})
            i += 3
        else:
            i += 1
    return meds


# ---------------------------------------------------------------------------
# Markdown builder
# ---------------------------------------------------------------------------

def _build_prescription_markdown(
    hospital: str,
    patient_info: Dict[str, str],
    medications: List[Dict[str, str]],
    instructions: List[str],
    physician: str,
) -> str:
    lines: List[str] = ["# Prescription", ""]
    if hospital:
        lines += [f"**{hospital}**", ""]
    for label, key in [
        ("Patient", "patient"),
        ("MRN", "mrn"),
        ("Date", "date"),
        ("Age", "age"),
        ("Diagnosis", "diagnosis"),
    ]:
        if patient_info.get(key):
            lines.append(f"{label}: {patient_info[key]}")
    if physician:
        lines.append(f"Prescribing Physician: {physician}")
    lines.append("")

    if medications:
        lines += ["## Medications", ""]
        lines.append("| Medication | Dosage | Frequency |")
        lines.append("|---|---|---|")
        for med in medications:
            lines.append(f"| {med['name']} | {med['dosage']} | {med['frequency']} |")
        lines.append("")

    if instructions:
        lines += ["## Patient Instructions", ""]
        for instr in instructions:
            lines.append(f"- {instr}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class MedicalDocumentNormalizer:
    """Convert flattened medical document text to structured Markdown."""

    @staticmethod
    def normalize(
        text: str,
        detected_doc_type: str,
        tables: Optional[list] = None,
    ) -> dict:
        """
        Args:
            text              Raw cleaned text from OCR/PyMuPDF.
            detected_doc_type ChunkDocType value string: "prescription", "form", etc.
            tables            pdfplumber table rows (may be None or []).

        Returns dict with keys:
            normalized_text      str
            normalized_format    "markdown" | "plain"
            structured_fields    dict
            normalization_applied bool
        """
        tables = tables or []

        if "prescription" not in detected_doc_type.lower():
            return {
                "normalized_text": text,
                "normalized_format": "plain",
                "structured_fields": {},
                "normalization_applied": False,
            }

        # --- Extract patient info -------------------------------------------
        patient_info: Dict[str, str] = {}
        patient_table = _find_patient_table(tables)
        if patient_table:
            patient_info = _parse_patient_info_from_table(patient_table)

        # Fill missing fields from raw text
        for key in ("patient", "date", "age", "mrn", "diagnosis"):
            if not patient_info.get(key):
                val = _extract_field(text, key)
                if val:
                    patient_info[key] = val

        # --- Extract medications ---------------------------------------------
        med_table = _find_medication_table(tables)
        if med_table:
            medications = _parse_medications_from_table(med_table)
        else:
            medications = _parse_medications_from_text(text)

        # --- Extract supporting text fields ---------------------------------
        hospital = _extract_hospital(text)
        physician = _extract_field(text, "physician")
        instructions = _extract_instructions(text)

        # --- Build Markdown --------------------------------------------------
        normalized_text = _build_prescription_markdown(
            hospital, patient_info, medications, instructions, physician
        )

        structured_fields = {
            "hospital":    hospital,
            "patient":     patient_info.get("patient", ""),
            "mrn":         patient_info.get("mrn", ""),
            "date":        patient_info.get("date", ""),
            "age":         patient_info.get("age", ""),
            "diagnosis":   patient_info.get("diagnosis", ""),
            "physician":   physician,
            "medications": medications,
            "instructions": instructions,
        }

        return {
            "normalized_text":     normalized_text,
            "normalized_format":   "markdown",
            "structured_fields":   structured_fields,
            "normalization_applied": True,
        }
