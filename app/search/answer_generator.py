"""
Phase 3/4 — Grounded answer generation via OpenRouter.

PHI Safety Contract:
  1. Context sent to the LLM always uses reversible numbered placeholders
     (e.g. PERSON_1, DATE_TIME_1) — raw PHI is NEVER forwarded to any provider.
  2. The placeholder-to-original mapping lives only in local request memory and
     is explicitly cleared before this function returns.
  3. Placeholder restoration for treating_clinician happens here, immediately
     before the function returns, and the mapping is then discarded.
  4. The mapping is NEVER logged, cached, stored, or sent anywhere.
"""

import json
import logging
import os
from typing import Dict, List, Tuple

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
    Replaces every PHI span in each chunk's original text with a numbered
    placeholder token, building a single context string for the LLM.

    Returns:
        context  — placeholder-masked multi-chunk context string
        mapping  — {placeholder: original_text}; caller must clear() this after use

    Span offsets from ingestion time are applied in reverse order per chunk so
    earlier spans are not shifted by later replacements.
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
            token = f"{prefix}_{counters[prefix]}"
            original = "".join(chars[start:end])
            mapping[token] = original
            chars[start:end] = list(token)

        parts.append("".join(chars))

    context = "\n\n---\n\n".join(parts)
    return context, mapping


def _restore(text: str, mapping: Dict[str, str]) -> str:
    """Substitute placeholder tokens back to original PHI values."""
    for token, original in mapping.items():
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
                "Answer the question using ONLY the provided context. "
                "Do not infer or add information not present in the context. "
                "If the context is insufficient, state that clearly."
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

            # Restore only for treating clinicians — immediately before returning.
            if role == "treating_clinician":
                answer = _restore(answer, mapping)

            return answer, "success", sources

        except Exception as exc:
            logger.warning("Answer generation failed: %s", exc)
            return "", "failed", sources

        finally:
            # Always clear the in-memory mapping — it must never outlive this call.
            mapping.clear()
