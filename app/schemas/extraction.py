# app/schemas/extraction.py
#
# Project 3 — Phase 2: Pydantic v2 schema for clinical structured extraction.
#
# IMPORTANT — two validators with similar names:
#   app/ingestion/extraction_validator.py  →  Project 1, OCR quality scorer. DO NOT TOUCH.
#   app/ingestion/validator.py             →  Project 3, JSON repair + Pydantic wrapper (this phase).
#
# Design decisions:
#   D-06: Hybrid schema — strict enums for entity_type/relation_status, free text for mention/evidence.
#   D-07: Schema scope is drug + ADE + dosage + relation + evidence span. No assertion_status etc.
#   D-35: record_id and validation are NOT model outputs. They are system-injected by
#         app/ingestion/validator.py after generation. Never include them in training targets.
#
# Schema version history:
#   v1 (2026): Initial. entity_type ∈ {medication, adverse_event}. relation_status ∈ {related,
#              not_related, none}. No assertion_status, certainty, temporal_status (not labeled
#              in ade_corpus_v2 — lead-approved scope reduction).

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class SourceSpan(BaseModel):
    """Character-level evidence span in the input text.

    start_char and end_char are offsets into the ORIGINAL unmasked text
    (extraction runs before PHI masking per D-35).
    """

    start_char: int = Field(ge=0, description="Start character offset (inclusive).")
    end_char: int = Field(ge=0, description="End character offset (exclusive).")


class Entity(BaseModel):
    """A single extracted clinical entity — medication or adverse event.

    Fields:
        entity_type       : Strict enum. medication | adverse_event.
        mention           : The exact surface form found in the text. Free text.
        dosage            : Dosage string (e.g. "500 mg BID"). Null if not present or not a medication.
        linked_medication : For adverse_event entities — the drug this ADE is linked to.
                            Null for medication entities. Free text (drug mention string).
        evidence          : Supporting sentence text. Should be a substring of the input chunk.
        source_span       : Character offsets of `mention` in the input text.
    """

    entity_type: Literal["medication", "adverse_event"]
    mention: str = Field(min_length=1, description="Surface form of the entity in the source text.")
    dosage: Optional[str] = None
    linked_medication: Optional[str] = None
    evidence: str = Field(min_length=1, description="Sentence-level supporting evidence text.")
    source_span: SourceSpan


class ValidationFlags(BaseModel):
    """Post-generation validation state — system-injected, never model-generated.

    All flags start True and are flipped to False if the corresponding check fails.
    json_valid is False only when JSON repair also fails (raw output is unparseable).
    schema_valid is False when Pydantic model_validate() raises ValidationError.
    enum_valid is False when entity_type or relation_status contain invalid values.
        (In practice Pydantic v2 Literal already enforces this, but the flag is explicit
        so downstream consumers don't need to inspect the Pydantic error.)
    evidence_present is False when any entity's evidence field is not a substring of
        the input chunk text. The extraction is still returned — not rejected — but flagged.
    """

    json_valid: bool
    schema_valid: bool
    enum_valid: bool
    evidence_present: bool


class ExtractionResult(BaseModel):
    """Full system-level extraction result, after generation + validation.

    Split into two parts (see Design Doc §10.1):

    MODEL-GENERATED (model is trained to produce these):
        schema_version, entities[], relation_status

    SYSTEM-INJECTED (wrapper adds these BEFORE model_validate()):
        record_id, validation, error_reason

    Never put record_id or validation in training targets — doing so would teach the model
    to invent record IDs and claim its own output is always valid.
    """

    record_id: str = Field(description="Chunk ID — injected by validator.py, not by the model.")
    schema_version: Literal["v1"]
    entities: list[Entity]
    relation_status: Literal["related", "not_related", "none"]
    validation: ValidationFlags
    error_reason: Optional[str] = None  # Populated by build_empty_result() on failure; None on success.

    @model_validator(mode="after")
    def check_spans_make_sense(self) -> "ExtractionResult":
        """Reject any entity whose source_span has end_char <= start_char.

        A zero-length or inverted span is always a model error (the model copied wrong offsets).
        We catch this here rather than silently storing broken span data in OpenSearch.
        """
        for entity in self.entities:
            span = entity.source_span
            if span.end_char <= span.start_char:
                raise ValueError(
                    f"Invalid source_span for entity '{entity.mention}': "
                    f"end_char ({span.end_char}) must be > start_char ({span.start_char})."
                )
        return self
