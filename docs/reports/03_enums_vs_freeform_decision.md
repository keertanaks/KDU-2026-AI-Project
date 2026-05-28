# Report 03 — Enums vs Free-Form Decision Record

**Project:** Project 3 — Harmony Clinical Structuring Fine-Tuning System  
**Phase:** 2 — Schema and Validation Engine  
**Status:** Complete  
**Design Decision:** D-06 (Hybrid schema)

---

## 1. Decision Summary

**Chosen approach:** Hybrid — strict enums for categorical/control fields, free text for clinical content fields.

This document records the full three-option analysis that led to D-06.

---

## 2. Options Considered

### Option A — Strict Enums for All Fields

Every field is an enum. Entity mentions, dosage strings, and evidence text are each a fixed vocabulary.

**Why it was considered:**
- Maximum model control. The model cannot invent new values.
- Enum accuracy (EVAL-06) trivially reaches 100%.
- Downstream OpenSearch filters are perfectly reliable.

**Why it was rejected:**

| Problem | Explanation |
|---|---|
| Drug mentions cannot be enumerated | There are thousands of approved drug names, plus brand names, generic names, abbreviations, and misspellings. No practical fixed vocabulary. |
| Dosage strings are infinitely varied | `"500 mg"`, `"5 mcg/kg/min"`, `"QID PRN po"`, `"1 tablet BID"`, `"0.25 IU/kg"` — the space is open-ended. |
| Evidence text is inherently free | The supporting sentence comes directly from the clinical note. It cannot be an enum. |
| Training signal lost | If the model only outputs enum tokens, it never learns to locate the correct mention in the text. The extraction task becomes a classification task, which defeats the purpose of span-level annotation. |

**Verdict:** Rejected. Full strict enums are only suitable for the categorical fields, not for content fields.

---

### Option B — Full Free Text for All Fields

Every field is an unconstrained string, including `entity_type` and `relation_status`.

**Why it was considered:**
- Maximum flexibility. The model can express nuance.
- No vocabulary constraints to maintain.
- Simplest schema to define.

**Why it was rejected:**

| Problem | Explanation |
|---|---|
| Model invents entity types | Without enum enforcement, the model may output `"allergy"`, `"symptom"`, `"condition"` instead of `"medication"` or `"adverse_event"`. Downstream filters (`entity_type == "medication"`) break. |
| Model invents relation labels | Free-text relation status leads to outputs like `"possibly related"`, `"unclear"`, `"maybe"` — none of which map to the three-class filter the search layer expects. |
| Enum accuracy metric (EVAL-06) becomes meaningless | Cannot measure compliance with a fixed value set if the set is not defined. |
| OpenSearch keyword filters degrade | Harmony's structured filter layer (`adverse_events.mention = "nausea"`) works only because `entity_type` is a controlled vocabulary. Full free text eliminates this capability. |

**Verdict:** Rejected. Categorical control fields must be enums to support reliable filtering and metric measurement.

---

### Option C — Hybrid (Chosen)

Strict enums for categorical fields. Free text for clinical content fields. Structured object for spans.

**The split:**

| Field | Choice | Rationale |
|---|---|---|
| `entity_type` | **Enum** `["medication", "adverse_event"]` | Binary classification. Invented values break downstream filters. |
| `relation_status` | **Enum** `["related", "not_related", "none"]` | Three-class label. Strict control required for OpenSearch filter queries and EVAL-05d. |
| `schema_version` | **Enum** `["v1"]` | Version pinning for forward compatibility (D-34). |
| `mention` | **Free text** | Drug and ADE names are too varied to enumerate. |
| `dosage` | **Free text** | Dosage strings have infinite variation — free text is the only option. |
| `linked_medication` | **Free text** | Drug mention string — same argument as `mention`. |
| `evidence` | **Free text** | Supporting sentence from clinical text — inherently free. |
| `source_span` | **Structured object** | `{start_char: int, end_char: int}` — character offsets. Constrained to non-negative integers with `end_char > start_char`. |

**Why this hybrid works:**

1. **Enum accuracy (EVAL-06 ≥ 98%) is achievable.** The enums cover only 3 fields, all of which appear dozens of times per training example. The model sees enough examples to learn the correct values reliably.

2. **Free-text span-level extraction is preserved.** `mention` is what the span extraction task is actually about — the model learns to locate and copy the exact surface form from the text. Enumerating it would collapse this into entity classification.

3. **OpenSearch filter reliability is maintained.** `entity_type` and `relation_status` are the fields used for structured filter queries (`medications.mention = metformin`, `relation_status = related`). These being strict enums guarantees that filters behave correctly.

4. **Validation is layered.** Pydantic `Literal` enforces enum fields at schema validation time. The `evidence_present` check handles free-text validity for content fields. Neither layer relies on the other.

---

## 3. Fields Explicitly Out of Scope

The Project Specification example schema included additional fields that were evaluated and excluded from v1:

| Field | Decision | Reason |
|---|---|---|
| `assertion_status` (`confirmed`, `negated`, `possible`) | Out of scope v1 | Not labeled in `ade_corpus_v2`. Silver labeling rejected (noise). n2c2 2018 deferred (DUA timeline). |
| `certainty` (confidence score) | Out of scope v1 | No calibrated confidence signal in training data. |
| `medication_action` (`start`, `stop`, `increase`) | Out of scope v1 | Not labeled in `ade_corpus_v2`. |
| `temporal_status` (`current`, `historical`, `hypothetical`) | Out of scope v1 | Not labeled in `ade_corpus_v2`. |

These exclusions are lead-approved (Kirti, 2026). They are documented as honest scope reduction, not an oversight. A v2 schema can add any of these if a richer labeled dataset becomes available.

---

## 4. How Enum Accuracy Is Measured (EVAL-06)

**Target: ≥ 98% of outputs use valid enum values for `entity_type` and `relation_status`.**

Measurement:
```python
def compute_enum_accuracy(results: list[ExtractionResult]) -> float:
    valid = sum(
        1 for r in results
        if r.relation_status in {"related", "not_related", "none"}
        and all(e.entity_type in {"medication", "adverse_event"} for e in r.entities)
    )
    return valid / len(results)
```

In practice, Pydantic `Literal` enforcement means that any result that passes `model_validate()` already has valid enum values. The metric is most useful for measuring the *repair rate* — how many outputs required `json_repair` before they could pass Pydantic validation, and whether the repair preserved the enum fields correctly.

---

## 5. Implementation

The hybrid schema is implemented in `app/schemas/extraction.py` using Pydantic v2:

```python
class Entity(BaseModel):
    entity_type: Literal["medication", "adverse_event"]   # enum
    mention: str = Field(min_length=1)                    # free text
    dosage: Optional[str] = None                          # free text
    linked_medication: Optional[str] = None               # free text
    evidence: str = Field(min_length=1)                   # free text
    source_span: SourceSpan                               # structured object

class ExtractionResult(BaseModel):
    schema_version: Literal["v1"]                         # enum
    entities: list[Entity]
    relation_status: Literal["related", "not_related", "none"]  # enum
    # ... system-injected fields ...
```

Pydantic v2's `Literal` type raises `ValidationError` immediately if the model outputs an unrecognized value for any enum field. This is caught by `validate_extraction()` in `app/ingestion/validator.py`, which returns `build_empty_result(reason="schema_invalid")` and logs the failure.
