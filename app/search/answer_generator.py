"""
Phase 3/4 — Grounded answer generation via OpenRouter.

PHI Safety Contract:
  1. Context sent to the LLM always uses reversible bracketed placeholders
     (e.g. [[PHI_PERSON_1]], [[PHI_DATE_TIME_1]]) — raw PHI is NEVER forwarded.
  2. The placeholder-to-original mapping lives only in local request memory and
     is explicitly cleared before this function returns.
  3. Placeholder restoration for treating_clinician happens here, immediately
     before the function returns, and the mapping is then discarded.
  4. For all other roles the LLM output is redacted: any remaining placeholder
     tokens are replaced with <TYPE_REDACTED> strings before returning.
  5. The mapping is NEVER logged, cached, stored, or sent anywhere.
  6. If LLM corrupts placeholders (early detection), treating_clinician falls back
     to extracted answer from source chunks; non_treating always redacts.
"""

import json
import logging
import os
import re
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)

# Maps Presidio entity types to human-readable placeholder prefixes.
_TYPE_PREFIX: Dict[str, str] = {
    "PERSON": "PERSON",
    "NAME": "PERSON",
    "LOCATION": "LOCATION",
    "ADDRESS": "LOCATION",
    "DATE_TIME": "DATE_TIME",
    "DOB": "DATE_TIME",
    "MRN": "ID",
    "US_SSN": "ID",
    "US_PASSPORT": "ID",
    "MEDICAL_LICENSE": "ID",
    "NRP": "ID",
    "IP_ADDRESS": "ID",
    "PHONE_NUMBER": "PHONE",
    "PHONE": "PHONE",
    "EMAIL_ADDRESS": "EMAIL",
    "URL": "URL",
    "DIAGNOSIS": "DIAGNOSIS",
    "MEDICATION": "MEDICATION",
}

# Ordered list of (pattern, replacement) pairs for redact_placeholders().
# Specific types listed first; catch-all last.
_REDACT_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\[\[PHI_PERSON_\d+\]\]"),    "<PERSON_REDACTED>"),
    (re.compile(r"\[\[PHI_LOCATION_\d+\]\]"),  "<LOCATION_REDACTED>"),
    (re.compile(r"\[\[PHI_DATE_TIME_\d+\]\]"), "<DATE_TIME_REDACTED>"),
    (re.compile(r"\[\[PHI_ID_\d+\]\]"),        "<ID_REDACTED>"),
    (re.compile(r"\[\[PHI_PHONE_\d+\]\]"),     "<PHONE_REDACTED>"),
    (re.compile(r"\[\[PHI_EMAIL_\d+\]\]"),     "<EMAIL_REDACTED>"),
    (re.compile(r"\[\[PHI_URL_\d+\]\]"),       "<URL_REDACTED>"),
    (re.compile(r"\[\[PHI_DIAGNOSIS_\d+\]\]"), "<DIAGNOSIS_REDACTED>"),
    (re.compile(r"\[\[PHI_MEDICATION_\d+\]\]"),"<MEDICATION_REDACTED>"),
    # Catch-all for any prefix type not listed above (case-insensitive).
    (re.compile(r"\[\[PHI_\w+_\d+\]\]", re.IGNORECASE), "<PHI_REDACTED>"),
]


def _prefix(entity_type: str) -> str:
    return _TYPE_PREFIX.get(entity_type, "PHI")


def _deserialize_spans(phi_raw) -> List[Dict]:
    if isinstance(phi_raw, str):
        try:
            spans = json.loads(phi_raw)
        except (json.JSONDecodeError, TypeError):
            return []
    else:
        spans = phi_raw
    return spans if isinstance(spans, list) else []


def _build_placeholder_context(
    reranked_chunks: List[Dict],
) -> Tuple[str, Dict[str, str]]:
    """
    Replaces every PHI span in each chunk's original text with a bracketed
    placeholder token of the form [[PHI_TYPE_N]], building a single context
    string for the LLM.

    Bracket format (e.g. [[PHI_PERSON_1]]) is intentionally distinctive so
    LLMs do not rewrite or merge tokens the way they sometimes do with bare
    identifiers like PERSON_1.

    Returns:
        context  — placeholder-masked multi-chunk context string
        mapping  — {placeholder: original_text}; caller must clear() after use

    Span offsets are applied in reverse order per chunk so earlier spans are
    not shifted by later replacements.
    """
    mapping: Dict[str, str] = {}
    counters: Dict[str, int] = {}
    parts: List[str] = []

    for chunk in reranked_chunks:
        src = chunk.get("_source", {})
        text = src.get("text", "")
        spans = _deserialize_spans(src.get("phi_spans", []))

        sorted_spans = sorted(spans, key=lambda s: s.get("start", 0), reverse=True)
        chars = list(text)

        for span in sorted_spans:
            start = span.get("start", 0)
            end = span.get("end", 0)
            if start >= end or end > len(chars):
                continue
            prefix = _prefix(span.get("type", "PHI"))
            counters[prefix] = counters.get(prefix, 0) + 1
            token = f"[[PHI_{prefix}_{counters[prefix]}]]"
            original = "".join(chars[start:end])
            mapping[token] = original
            chars[start:end] = list(token)

        parts.append("".join(chars))

    context = "\n\n---\n\n".join(parts)
    return context, mapping


def redact_placeholders(text: str) -> str:
    """
    Replace any remaining [[PHI_TYPE_N]] tokens with <TYPE_REDACTED> strings.

    Three-pass approach handles well-formed tokens, LLM token corruption
    (partial brackets, wrong case, single closing bracket), and orphaned
    suffix fragments from split placeholders.
    """
    # Pass 1: named-type patterns + catch-all (well-formed [[PHI_TYPE_N]] tokens)
    # Sort patterns by specificity (longer/more specific first to avoid partial matches)
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    # Pass 2: sweep any remaining [[PHI_ prefix fragments (handles partial tokens
    # where the LLM corrupted or split the closing brackets)
    text = re.sub(r"\[\[PHI_[^\s\[\]]*(?:\]\])?", "<PHI_REDACTED>", text)
    # Pass 3: sweep HI_TYPE_N]] orphaned suffixes produced when [[P was consumed
    # separately by an earlier pass, leaving e.g. HI_LOCATION_2]] in the text.
    text = re.sub(r"(?<![A-Za-z0-9_])HI_[A-Z][A-Z_]*_\d+\]\]?", "<PHI_REDACTED>", text)
    return text


def _contains_phi_fragments(text: str) -> bool:
    """Check if text contains any PHI placeholder fragments or corruption."""
    return bool(re.search(r"\[\[PHI_|(?<![A-Za-z0-9_])PHI_[A-Z_]+_\d+", text))


def _sanitize_remaining_fragments(text: str) -> str:
    """
    Clean up any remaining malformed PHI fragments after attempted restoration.

    Handles cases where LLM corrupted placeholders:
    - "Hanna[[PHI_DATE_TIME_1]]" → "Hanna<DATE_TIME_REDACTED>"
    - "[[PHI_" orphans → "<PHI_REDACTED>"
    """
    # Redact any remaining well-formed placeholders (catch-all)
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    # Clean up fragments
    text = re.sub(r"\[\[PHI_[^\[\]]*", "<PHI_REDACTED>", text)
    text = re.sub(r"(?<![A-Za-z0-9_])PHI_[A-Z_]+_\d+(?!\])", "<PHI_REDACTED>", text)
    return text


def _get_chunk_for_role(chunk: Dict, role: str) -> Dict:
    """
    Prepare chunk text based on role.

    treating_clinician: raw chunk with original PHI
    non_treating_clinician: masked chunk with <TYPE_REDACTED> tokens
    """
    if role == "treating_clinician":
        # Treating clinician sees raw PHI
        return chunk

    # For non_treating: mask the chunk before extraction
    src = chunk.get("_source", {})
    text = src.get("normalized_text", "") or src.get("text", "")
    phi_spans = src.get("phi_spans", [])

    # Mask PHI in the chunk text using ResponseMasker
    from app.search.masker import ResponseMasker
    masked_text = ResponseMasker.mask(text, phi_spans, role)

    # Return chunk with masked text
    masked_chunk = dict(chunk)
    masked_chunk["_source"] = dict(src)
    masked_chunk["_source"]["text"] = masked_text
    masked_chunk["_source"]["normalized_text"] = masked_text

    return masked_chunk


def _apply_final_role_sanitizer(answer: str, role: str) -> str:
    """
    Final sanitizer for role-based output safety.

    Catches any slips in extraction/redaction:
    - For non_treating: remove any raw names, MRNs, partial names that escaped
    - For treating: allow raw PHI (already restored)
    """
    if role == "treating_clinician":
        # Treating clinician can see raw PHI - no sanitization
        return answer

    # For non_treating and other restricted roles: remove any raw PHI patterns
    # Remove partial names before redaction tags (e.g., "Hanna<PERSON_REDACTED>" → "<PERSON_REDACTED>")
    answer = re.sub(r"[A-Za-z][\w'-]*\s*(?=<[A-Z_]+_REDACTED>)", "", answer)
    # Replace MRN patterns (e.g., MRN100016 -> <MRN_REDACTED>)
    answer = re.sub(r"MRN\d+", "<MRN_REDACTED>", answer, flags=re.IGNORECASE)
    # If any placeholders remain, redact them
    answer = redact_placeholders(answer)
    # Clean orphaned fragments
    if _contains_phi_fragments(answer):
        answer = _sanitize_remaining_fragments(answer)

    return answer


def _extract_simple_answer(query: str, chunk: Dict, role: str = "treating_clinician") -> Optional[str]:
    """
    Extract structured answers for common query patterns from normalized chunk.

    Pattern 1: "Which patient was prescribed <medication>?"
    Pattern 2: "What medications was <patient> prescribed?"
    Pattern 3: "Who prescribed <patient>'s medication?"
    Pattern 4: "What is the MRN for <patient>?"

    For non_treating_clinician, the chunk should already be masked.
    Returns extracted answer or None if no pattern matches.
    """
    if not chunk:
        return None

    src = chunk.get("_source", {})
    text = src.get("normalized_text", "") or src.get("text", "")

    if not text:
        return None

    query_lower = query.lower()

    # Pattern 1: "Which patient was prescribed [medication/dose]?"
    if "which patient" in query_lower and ("prescribed" in query_lower or "medication" in query_lower):
        # Try to extract patient name
        patient_match = re.search(r"Patient:\s*([^\n]+)", text)
        if patient_match:
            patient = patient_match.group(1).strip()
            # Extract first medication from table (after separator line)
            med_match = re.search(r"\|---\|---\|---\|\s*\n\|\s*([A-Za-z]+)\s*\|", text)
            if med_match:
                med_name = med_match.group(1)
                return f"The patient prescribed {med_name} is {patient}."

    # Pattern 2: "What medications was [patient] prescribed?"
    if "what medications" in query_lower and "prescribed" in query_lower:
        # Extract medication table
        meds = re.findall(r"\| ([A-Za-z]+) \| ([0-9a-z\s]+) \| ([^\|]+) \|", text)
        if meds:
            med_lines = [f"{name}: {dosage}, {freq.strip()}" for name, dosage, freq in meds]
            return f"Medications prescribed: {'; '.join(med_lines)}."

    # Pattern 3: "Who prescribed [patient]'s medication?"
    if ("who prescribed" in query_lower or "prescribing physician" in query_lower) and "medication" in query_lower:
        physician_match = re.search(r"Prescribing Physician:\s*([^\n]+)", text)
        if physician_match:
            physician = physician_match.group(1).strip()
            return f"The prescribing physician is {physician}."

    # Pattern 4: "What is the MRN for [patient]?"
    if "mrn" in query_lower:
        mrn_match = re.search(r"MRN:\s*([^\n]+)", text)
        if mrn_match:
            mrn = mrn_match.group(1).strip()
            return f"The MRN is {mrn}."

    return None


def _restore(text: str, mapping: Dict[str, str]) -> str:
    """
    Substitute [[PHI_TYPE_N]] tokens back to original PHI values.

    Process tokens longest-first to prevent partial replacements inside words.
    Example: restore [[PHI_PERSON_1]] before [[PHI_PERSON_11]] to avoid
    "Hanna[[PHI_DATE_TIME_1]]" corruption.
    """
    if not mapping:
        return text

    # Sort by token length descending (longest first) to avoid partial replacements
    sorted_items = sorted(mapping.items(), key=lambda x: len(x[0]), reverse=True)

    for token, original in sorted_items:
        # Only replace exact token matches; skip if token not in text
        if token in text:
            text = text.replace(token, original)

    return text


class AnswerGenerator:
    """
    Calls OpenRouter to produce a grounded answer from retrieved context.

    If OPENROUTER_API_KEY is absent or the placeholder value, answer generation
    is silently skipped and status="skipped" is returned so the search pipeline
    degrades gracefully without failing.
    """

    def generate(
        self,
        query: str,
        reranked_chunks: List[Dict],
        role: str,
    ) -> Tuple[str, str, List[str]]:
        """
        Returns (answer, status, sources).

        answer  — generated text (empty string when status != "success")
        status  — "success" | "skipped" | "failed"
        sources — list of doc_ids from the reranked chunks

        PHI handling:
          - treating_clinician  → placeholders restored to original values
          - all other roles     → placeholders replaced with <TYPE_REDACTED>
        """
        sources = [
            c.get("_source", {}).get("doc_id", "")
            for c in reranked_chunks
        ]
        sources = [s for s in sources if s]

        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key or "placeholder" in api_key or api_key.startswith("sk-or-v1-xxx"):
            logger.info("OpenRouter key not configured — answer generation skipped")
            return "", "skipped", sources

        context, mapping = _build_placeholder_context(reranked_chunks)

        try:
            from openai import OpenAI  # noqa: PLC0415

            client = OpenAI(
                api_key=api_key,
                base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            )
            model = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")

            system_msg = (
                "You are a medical records assistant. "
                "Answer the question directly and confidently using the provided context. "
                "Extract and present facts, patient details, diagnoses, and medications exactly as they appear. "
                "Only decline to answer if the context truly contains NO relevant information whatsoever. "
                "IMPORTANT: The context contains placeholders like [[PHI_PERSON_1]], "
                "[[PHI_LOCATION_1]], [[PHI_DATE_TIME_1]] etc. "
                "Copy these placeholders EXACTLY as written — do not modify, "
                "abbreviate, split, or paraphrase them."
            )
            user_msg = f"Context:\n{context}\n\nQuestion: {query}"

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=512,
                temperature=0.1,
            )
            answer = response.choices[0].message.content or ""

            # EARLY corruption detection (before any restoration/redaction)
            has_corruption = _contains_phi_fragments(answer)

            if role == "treating_clinician":
                if has_corruption:
                    # LLM corrupted placeholders → fallback to extracted answer (raw chunk)
                    fallback_answer = _extract_simple_answer(query, reranked_chunks[0] if reranked_chunks else None, role)
                    if fallback_answer:
                        answer = fallback_answer
                        logger.info("Fallback to extracted answer due to placeholder corruption")
                    elif reranked_chunks:
                        # Last resort: use raw chunk text directly
                        answer = reranked_chunks[0].get("_source", {}).get("normalized_text", "")
                        logger.info("Fallback to chunk text due to placeholder corruption")
                else:
                    # No corruption: restore original PHI values
                    answer = _restore(answer, mapping)

            else:
                # For non-treating: use MASKED chunk for fallback extraction
                if has_corruption:
                    masked_chunk = _get_chunk_for_role(reranked_chunks[0], role) if reranked_chunks else None
                    fallback_answer = _extract_simple_answer(query, masked_chunk, role)
                    if fallback_answer:
                        answer = fallback_answer
                        logger.info("Non-treating: fallback to extracted answer (masked chunk) due to placeholder corruption")

                # Always redact for non-treating (whether from LLM or fallback)
                answer = redact_placeholders(answer)
                # Extra validation: clean up any remaining fragments
                if _contains_phi_fragments(answer):
                    answer = _sanitize_remaining_fragments(answer)

            # Final safety sanitizer for role-based output
            answer = _apply_final_role_sanitizer(answer, role)

            return answer, "success", sources

        except Exception as exc:
            logger.warning("Answer generation failed: %s", exc)
            return "", "failed", sources

        finally:
            # Always clear the in-memory mapping — it must never outlive this call.
            mapping.clear()
