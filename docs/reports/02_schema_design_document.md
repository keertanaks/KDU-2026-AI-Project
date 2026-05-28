# Report 02 — Schema Design Document

**Project:** Project 3 — Harmony Clinical Structuring Fine-Tuning System  
**Phase:** 2 — Schema and Validation Engine  
**Status:** Complete  
**Design Decision:** D-06 (Hybrid schema), D-07 (Schema scope), D-34 (Schema versioning), D-35 (Extraction order)

---

## 1. Overview

This document specifies the extraction schema used by the fine-tuned Qwen2.5-7B model (version `v1`). It defines every field, its type, whether it is model-generated or system-injected, and the rationale for each design choice.

The schema has two distinct layers:

| Layer | Fields | Who populates it |
|---|---|---|
| **Model output** | `schema_version`, `entities[]`, `relation_status` | The fine-tuned model at generation time |
| **System-injected** | `record_id`, `validation`, `error_reason` | `app/ingestion/validator.py` after generation |

This split is fundamental. The model never sees or outputs `record_id` or `validation` — training it to generate those fields would teach it to invent chunk IDs and claim its own output is always valid.

---

## 2. Full Field Specification

### 2.1 Top-Level Fields

| Field | Type | Enum / Free | Required | Source |
|---|---|---|---|---|
| `record_id` | `string` | free | yes | **System-injected** from chunk_id. Never model-generated. |
| `schema_version` | `string` | **enum** `["v1"]` | yes | Model learns to output `"v1"` (hard-coded in instruction template). |
| `entities` | `list[Entity]` | — | yes (may be empty list) | Model-generated. Empty when no drugs or ADEs are present. |
| `relation_status` | `string` | **enum** `["related", "not_related", "none"]` | yes | Model-generated. |
| `validation` | `ValidationFlags` | — | yes | **System-injected** by `validator.py` after generation. |
| `error_reason` | `string \| null` | free | no | **System-injected**: `null` on success, short code on failure (e.g. `"json_parse_failed"`). |

### 2.2 Entity Fields

Each item in `entities[]` represents one extracted clinical entity (medication or adverse event).

| Field | Type | Enum / Free | Required | Notes |
|---|---|---|---|---|
| `entity_type` | `string` | **enum** `["medication", "adverse_event"]` | yes | Strict enum. No free-text entity type invention. |
| `mention` | `string` | free | yes (min_length=1) | Exact surface form in the source text. |
| `dosage` | `string \| null` | free | no | Dosage string when present (e.g. `"500 mg BID"`). |
| `linked_medication` | `string \| null` | free | no (adverse_event only) | Drug mention this ADE is associated with. Null for medication entities. |
| `evidence` | `string` | free | yes (min_length=1) | Sentence-level supporting text. Validated as substring of input chunk. |
| `source_span` | `SourceSpan` | — | yes | `{start_char: int, end_char: int}` — character offsets into the original unmasked text. |

### 2.3 SourceSpan Fields

| Field | Type | Constraint | Notes |
|---|---|---|---|
| `start_char` | `int` | `≥ 0` | Start offset (inclusive). |
| `end_char` | `int` | `≥ 0` | End offset (exclusive). Must be `> start_char` (enforced by Pydantic model_validator). |

### 2.4 ValidationFlags Fields

All four flags default to `True` when the validator injects them. They are flipped to `False` if the corresponding check fails.

| Flag | Type | Meaning |
|---|---|---|
| `json_valid` | `bool` | `True` if `json.loads()` succeeded. `False` if only `json_repair` succeeded (or both failed). |
| `schema_valid` | `bool` | `True` if `ExtractionResult.model_validate()` succeeded. |
| `enum_valid` | `bool` | `True` if all enum fields (`entity_type`, `relation_status`) contain valid values. Pydantic `Literal` enforces this; the flag makes it explicit for downstream consumers. |
| `evidence_present` | `bool` | `True` if every entity's `evidence` field is a substring of the input chunk. |

---

## 3. Example: Input → Model Output → Full System Output

### Input chunk (original unmasked text):
```
Intravenous azithromycin-induced ototoxicity.
```

### Model output (what the model is trained to generate):
```json
{
  "schema_version": "v1",
  "entities": [
    {
      "entity_type": "medication",
      "mention": "azithromycin",
      "dosage": null,
      "linked_medication": null,
      "evidence": "Intravenous azithromycin-induced ototoxicity.",
      "source_span": {"start_char": 12, "end_char": 24}
    },
    {
      "entity_type": "adverse_event",
      "mention": "ototoxicity",
      "dosage": null,
      "linked_medication": "azithromycin",
      "evidence": "Intravenous azithromycin-induced ototoxicity.",
      "source_span": {"start_char": 33, "end_char": 44}
    }
  ],
  "relation_status": "related"
}
```

### Full system output (after `validator.py` injects `record_id` + `validation`):
```json
{
  "record_id": "chunk_abc123",
  "schema_version": "v1",
  "entities": [
    {
      "entity_type": "medication",
      "mention": "azithromycin",
      "dosage": null,
      "linked_medication": null,
      "evidence": "Intravenous azithromycin-induced ototoxicity.",
      "source_span": {"start_char": 12, "end_char": 24}
    },
    {
      "entity_type": "adverse_event",
      "mention": "ototoxicity",
      "dosage": null,
      "linked_medication": "azithromycin",
      "evidence": "Intravenous azithromycin-induced ototoxicity.",
      "source_span": {"start_char": 33, "end_char": 44}
    }
  ],
  "relation_status": "related",
  "validation": {
    "json_valid": true,
    "schema_valid": true,
    "enum_valid": true,
    "evidence_present": true
  },
  "error_reason": null
}
```

---

## 4. Why Hybrid Schema (D-06)

### 4.1 The three options considered

| Option | Description | Verdict |
|---|---|---|
| **A. Full strict enums** | All fields are enums — entity type, mention, dosage, evidence, relation status. | Rejected. Drug names and dosage strings cannot be enumerated (thousands of possible values). Evidence text is free-form by definition. |
| **B. Full free text** | All fields are free text, including entity_type and relation_status. | Rejected. Without enums, the model can invent entity types ("allergy", "symptom") or relation labels ("possibly_related") that downstream filters cannot handle reliably. |
| **C. Hybrid (chosen)** | Strict enums for categorical fields. Free text for content fields. Structured object for spans. | Selected. See §4.2. |

### 4.2 Which fields are enums and why

| Field | Type | Why enum |
|---|---|---|
| `entity_type` | `Literal["medication", "adverse_event"]` | Binary classification — exactly two classes defined by the dataset. Invented types break downstream filters. |
| `relation_status` | `Literal["related", "not_related", "none"]` | Three-class label directly from training data. Strict control needed for OpenSearch filter queries. |
| `schema_version` | `Literal["v1"]` | Version pinning — future schema changes increment to v2 without breaking v1 consumers. |

### 4.3 Which fields are free text and why

| Field | Why free text |
|---|---|
| `mention` | Thousands of possible drug and ADE names. Cannot enumerate. |
| `dosage` | Clinical dosage strings have infinite variation (`"500 mg"`, `"5 mcg/kg/min"`, `"BID"`, `"QID PRN"`). Free text is the only option. |
| `linked_medication` | A drug mention string — same argument as `mention`. |
| `evidence` | Supporting sentence — always a substring of the input text. Inherently free. |

---

## 5. Why Not the Full PS Schema (D-07)

The Project Specification example schema included:

- `assertion_status` (e.g. `"confirmed"`, `"negated"`, `"possible"`)
- `certainty` (confidence score)
- `medication_action` (e.g. `"start"`, `"stop"`, `"increase"`)
- `temporal_status` (current, historical, hypothetical)

None of these are labeled in `ade_corpus_v2`. Three options were evaluated:

| Option | Decision |
|---|---|
| **Drop them (chosen)** | Honest, fully supervised, smaller schema. Lead-approved. |
| **Silver-label via GPT-4** | Rejected — synthetic labels introduce noise that propagates into training. Lead declined. |
| **Switch to n2c2 2018** | Rejected — DUA registration timeline conflicts with project schedule. Lead declined. |

These fields are explicitly documented as **out of scope for v1**. A v2 schema can add them if a richer labeled dataset becomes available (n2c2 2018, MIMIC with DUA).

---

## 6. Why Source Spans Are on the Original Unmasked Text (D-35)

`source_span.start_char` and `source_span.end_char` are offsets into the **original unmasked text**, not the PHI-masked version. This is enforced architecturally:

- Extraction runs in `app/ingestion/extractor.py` on the original chunk text, **before** `phi_tagger.py` runs.
- PHI masking replaces spans with tokens like `[PERSON]` — this shifts all character offsets after each masked token. Running extraction after masking would produce `source_span` values that are wrong relative to the original document.
- Drug names and ADE mentions are clinical findings, not PHI — Presidio does not tag them. Running the extractor on unmasked text is safe.
- After extraction, Presidio runs on the `mention` and `evidence` fields in the extraction output as a secondary PHI-strip check before the result is stored.

---

## 7. Validation Engine Summary

Full validation pipeline is documented in `docs/reports/10_validation_engine.md`. Summary:

1. **JSON parse** (`json.loads` → `json_repair` fallback)
2. **System field injection** (`record_id`, `validation` block)
3. **Pydantic v2** schema validation (`ExtractionResult.model_validate()`)
4. **Span check** (`end_char > start_char`, enforced by `model_validator`)
5. **Evidence substring check** (per-entity, sets `evidence_present=False` if fails)
6. **Hallucination warning** (per-entity mention check, logged but not rejected)

---

## 8. Implementation

| File | Description |
|---|---|
| `app/schemas/extraction.py` | Pydantic v2 schema: `SourceSpan`, `Entity`, `ValidationFlags`, `ExtractionResult` |
| `app/ingestion/validator.py` | `validate_extraction()` and `build_empty_result()` |
| `tests/test_extraction_schema.py` | 37 unit tests — all passing |

---

## 9. Schema Version

`schema_version = "v1"` is embedded in every model output and in every stored OpenSearch document via `extraction_model_version`. Future schema changes must:

1. Define a new `Literal["v2"]` schema class.
2. Write a migration script for existing `v1` OpenSearch records.
3. Re-ingest affected documents with the new model.
4. Never change the `v1` schema class (backward compatibility).
