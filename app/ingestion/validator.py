# app/ingestion/validator.py
#
# Project 3 — Phase 2: JSON repair + Pydantic validation wrapper.
#
# DO NOT CONFUSE with app/ingestion/extraction_validator.py (Project 1 OCR quality scorer).
# These are completely different files with different purposes.
#
# This module is the validation engine described in Design Doc §15.
# It is called by app/ingestion/extractor.py (Phase 6) after the fine-tuned model generates
# a raw string, and also used directly by the evaluation harness (Phase 5).
#
# Validation pipeline (Design Doc §15.1, layers 2–4):
#   Layer 2: json.loads() → json_repair.loads() fallback
#   Layer 3: ExtractionResult.model_validate() (Pydantic v2)
#   Layer 4: Evidence substring check + hallucination warning
#
# Requires: pip install json-repair

import json
import logging
from typing import Optional

from pydantic import ValidationError

from app.schemas.extraction import (
    Entity,
    ExtractionResult,
    SourceSpan,
    ValidationFlags,
)

logger = logging.getLogger(__name__)


def build_empty_result(record_id: str, reason: str) -> ExtractionResult:
    """Return a fully-structured but empty ExtractionResult indicating a failure.

    Used when JSON parsing fails, schema validation fails, or extraction is disabled.
    All validation flags are set to False. error_reason explains the failure.

    Args:
        record_id : The chunk ID this extraction was attempted for.
        reason    : Short machine-readable failure code. Common values:
                    "json_parse_failed"     — json.loads + json_repair both failed
                    "schema_invalid"        — Pydantic model_validate() raised ValidationError
                    "extraction_disabled"   — EXTRACTION_ENABLED env var is "false"
                    "extraction_error"      — Unexpected exception (OOM, CUDA error, etc.)

    Returns:
        ExtractionResult with empty entities, relation_status="none", all flags False.
    """
    return ExtractionResult(
        record_id=record_id,
        schema_version="v1",
        entities=[],
        relation_status="none",
        validation=ValidationFlags(
            json_valid=False,
            schema_valid=False,
            enum_valid=False,
            evidence_present=False,
        ),
        error_reason=reason,
    )


def validate_extraction(
    raw_text: str,
    record_id: str,
    input_text: str,
) -> ExtractionResult:
    """Validate and repair the raw string output from the fine-tuned model.

    Steps (Design Doc §15.1, Layers 2–4):
      1. Try json.loads(raw_text).
      2. On JSONDecodeError: try json_repair.loads(raw_text).
         If still fails → return build_empty_result(reason="json_parse_failed").
      3. Inject system fields: record_id + validation block.
         Both MUST be injected before model_validate() — ExtractionResult requires them.
      4. ExtractionResult.model_validate(parsed).
         On ValidationError → return build_empty_result(reason="schema_invalid").
      5. Evidence substring check: for each entity, verify evidence ⊆ input_text.
         If not, flip validation.evidence_present = False (flagged, not rejected).
      6. Hallucination check: for each entity, verify mention ⊆ input_text.
         If not, log a warning (hallucination_warnings list for offline analysis).
      7. Return the validated ExtractionResult.

    Args:
        raw_text   : Raw string from the model (may be broken JSON).
        record_id  : Chunk ID to inject as record_id.
        input_text : Original (unmasked) chunk text, used for evidence and mention checks.

    Returns:
        ExtractionResult. Always returns a valid object — never raises.
    """
    # ── Layer 2: JSON parse ───────────────────────────────────────────────────
    parsed: Optional[dict] = None
    json_valid = True

    try:
        parsed = json.loads(raw_text)
    except (json.JSONDecodeError, ValueError):
        json_valid = False
        try:
            import json_repair  # noqa: PLC0415  (late import — optional dependency)
            parsed = json_repair.loads(raw_text)
            if not isinstance(parsed, dict):
                logger.warning(
                    "record_id=%s json_repair returned non-dict type %s — treating as failure",
                    record_id,
                    type(parsed).__name__,
                )
                return build_empty_result(record_id, reason="json_parse_failed")
            logger.info("record_id=%s JSON repaired successfully", record_id)
        except Exception as repair_exc:  # noqa: BLE001
            logger.error(
                "record_id=%s JSON repair failed: %s", record_id, repair_exc
            )
            return build_empty_result(record_id, reason="json_parse_failed")

    if not isinstance(parsed, dict):
        logger.warning(
            "record_id=%s json.loads returned non-dict type %s", record_id, type(parsed).__name__
        )
        return build_empty_result(record_id, reason="json_parse_failed")

    # ── Layer 3: Inject system fields + Pydantic validation ──────────────────
    # BOTH record_id AND validation must be injected here.
    # The model never outputs these — they are system-injected per Design Doc D-35.
    parsed["record_id"] = record_id
    parsed["validation"] = {
        "json_valid": json_valid,
        "schema_valid": True,   # will stay True if model_validate succeeds
        "enum_valid": True,     # Literal enforcement by Pydantic catches bad enum values
        "evidence_present": True,  # updated in Layer 4 below
    }

    try:
        result: ExtractionResult = ExtractionResult.model_validate(parsed)
    except ValidationError as ve:
        logger.warning(
            "record_id=%s Pydantic validation failed: %s", record_id, ve
        )
        return build_empty_result(record_id, reason="schema_invalid")

    # ── Layer 4: Evidence substring check + hallucination detection ──────────
    hallucination_warnings: list[str] = []

    for entity in result.entities:
        # Evidence check: the supporting sentence should be a substring of the input chunk.
        if entity.evidence and entity.evidence not in input_text:
            result.validation.evidence_present = False
            logger.debug(
                "record_id=%s entity '%s' evidence not substring of input",
                record_id,
                entity.mention,
            )

        # Hallucination check: the entity mention should appear in the input text.
        if entity.mention and entity.mention not in input_text:
            hallucination_warnings.append(entity.mention)
            logger.warning(
                "record_id=%s HALLUCINATION WARNING: mention '%s' not found in input text",
                record_id,
                entity.mention,
            )

    if hallucination_warnings:
        logger.warning(
            "record_id=%s %d hallucinated mention(s): %s",
            record_id,
            len(hallucination_warnings),
            hallucination_warnings,
        )

    return result
