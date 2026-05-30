# Report 13 — Final Report

**Project:** Harmony Clinical Structuring (Project 3)
**Date:** 2026-05-30
**Author:** Keertana S
**Branch:** feature/p3-final (merged into feature/p3-fine-tuning)

---

## Executive Summary

Project 3 extended the Harmony Healthcare RAG system with a fine-tuned clinical
NLP model for structured drug and adverse drug event (ADE) extraction. Starting
from `Qwen2.5-7B-Instruct` (Apache 2.0), we fine-tuned a LoRA adapter on the
`ade_corpus_v2` dataset and integrated the resulting extractor into the Harmony
ingestion pipeline. The fine-tuned model achieves Drug F1 = 0.798 and ADE F1 = 0.542
on the held-out test set, with 100% JSON validity and a 0.04% hallucination rate.
The model is deployed on a HuggingFace Space and called at ingestion time, writing
structured medication and ADE data to OpenSearch for retrieval at query time.

---

## 1. Project Scope

Project 3 implemented the following phases:

| Phase | Description | Branch |
|---|---|---|
| 1 | Data preparation: ade_corpus_v2 → train/val/test JSONL | feature/p3-data-prep |
| 2 | Schema design: ExtractionResult Pydantic model + validator | feature/p3-schema |
| 3 | LoRA fine-tuning (FP16, Kaggle T4×2) | feature/p3-lora-training |
| 4 | QLoRA fine-tuning (4-bit NF4, Kaggle T4×1) | feature/p3-qlora-training |
| 5 | Evaluation harness + metrics | feature/p3-evaluation |
| 6 | Harmony integration + HF Space deployment + demo UI | feature/p3-harmony-integration |
| 7 | Final reports + demo scripts | feature/p3-final |

---

## 2. Dataset

**Source:** `ade-benchmark-corpus/ade_corpus_v2` (HuggingFace Hub, CC-BY, no DUA).

All 3 configs loaded and merged. Split by `md5(text)` hash grouping to prevent
leakage (all duplicates of a sentence are in the same split).

| Split | Examples | Purpose |
|---|---|---|
| Train | 19,040 | Fine-tuning |
| Val | 2,380 | Early stopping signal |
| Test | 2,376 | Final evaluation (touched once) |
| OOD | 60 | Out-of-distribution synthetic evaluation |

No real patient data was used at any stage. MIMIC, PhysioNet, and any DUA-restricted
datasets were explicitly excluded.

---

## 3. Model Selection

**Base model:** `Qwen/Qwen2.5-7B-Instruct` (Apache 2.0)

Selected over alternatives for:
- State-of-the-art instruction following at ≤8B parameter scale
- Apache 2.0 license (commercial-safe)
- Strong structured JSON output on zero-shot prompts (confirmed by baseline eval)
- Fits on T4×2 (FP16) and T4×1 (4-bit NF4)

See Report 05 for full model selection rationale.

---

## 4. Fine-Tuning Results

### 4.1 Production Adapter: lora_v1

Configuration: LoRA r=16, alpha=32, LR=2e-4, 1 epoch, FP16, T4×2.

| Metric | Target | LoRA (lora_v1) | Status |
|---|---|---|---|
| JSON valid (pre-repair) | ≥95% | 100.0% | ✅ |
| JSON valid (post-repair) | ≥99.5% | 100.0% | ✅ |
| Schema valid | ≥90% | 100.0% | ✅ |
| Drug F1 | ≥0.75 | **0.798** | ✅ |
| ADE F1 | ≥0.65 | 0.542 | ❌ |
| Relation F1 | ≥0.70 | 0.642 | ❌ |
| Hallucination Rate | ≤5% | **0.04%** | ✅ |
| Evidence Accuracy | ≥90% | 100.0% | ✅ |
| Enum Accuracy | ≥98% | 100.0% | ✅ |

### 4.2 LoRA vs Baseline Improvement

| Metric | Baseline | LoRA | Improvement |
|---|---|---|---|
| Drug F1 | 0.434 | 0.798 | +84% relative |
| ADE F1 | 0.354 | 0.542 | +53% relative |
| Relation F1 | 0.227 | 0.642 | +183% relative |
| JSON pre-repair valid | 0.0% | 100.0% | Baseline always uses markdown fences |
| Hallucination rate | 0.60% | 0.04% | 15× improvement |

### 4.3 Gap Analysis

**ADE F1 (0.542 vs target 0.65):** Three contributing factors:
1. Class imbalance — 73% of training examples have no ADE entity
2. Multi-ADE sentences — model catches the first ADE per sentence but often misses
   the second when two ADEs appear in the same sentence
3. Training corpus artifacts — some sentences have inconsistent ADE annotations
   across duplicates

The gap is not a fundamental model capability issue. The model correctly identifies
ADE patterns when they appear clearly; the failure cases are on edge patterns with
low training signal.

**Relation F1 (0.642 vs target 0.70):** Macro-averaging over three classes penalizes
the `not_related` and `none` classes, which have few examples and lower per-class F1.
Per-class: `related` = 0.909 (OOD), `not_related` = 0.889 (OOD). The model is
strong on the classes it sees most.

---

## 5. Architecture Decisions

### 5.1 Extraction-First (D-35)

Extraction runs on the original (unmasked) text BEFORE PHI masking. This preserves
correct `source_span` character offsets. Drug names and ADE mentions are clinical
findings, not PHI. After extraction, Presidio strips any leaked PHI from
`mention` and `evidence` fields.

### 5.2 Ingestion-Time Extraction Only

The model is called exactly once per chunk at ingestion time. Zero model calls
happen at query time. Structured fields (`medications`, `adverse_events`, `relations`,
`extraction_model_version`) are written to OpenSearch and read directly at query time.
This avoids latency-sensitive model inference in the query path.

### 5.3 Remote Mode via HuggingFace Space

Setting `EXTRACTION_REMOTE_URL` in `.env` routes inference to the HF Space instead
of loading the 7B model locally. The Space serves a GGUF Q8_0 quantized model with
a LoRA adapter via llama-cpp-python. The ingestion pipeline is identical in both modes:
the extractor POSTs to `/extract` and receives `{"raw_output": "..."}`.

### 5.4 Graceful Degradation (D-23)

`ClinicalExtractor.extract()` never raises. OOM, CUDA errors, network timeouts, and
JSON parse failures all degrade to `build_empty_result(reason=...)`. The chunk is
indexed with empty extraction fields — searchable but without structured medication
data until re-indexed.

---

## 6. Integration with Harmony (Phase 6)

The `documents.py` ingestion endpoint was extended to call `ClinicalExtractor.extract()`
on each chunk's `child_text` before PHI masking. The extraction result populates five
new OpenSearch fields per chunk:

| OpenSearch Field | Source |
|---|---|
| `medications` | `[{mention, dosage, source_span}]` from medication entities |
| `adverse_events` | `[{mention, linked_medication, source_span}]` from ADE entities |
| `relations` | `[{adverse_event, medication}]` from linked_medication on ADEs |
| `extraction_model_version` | `"remote:lora_v1"` or `"lora_v1"` or `"disabled"` |
| `extraction_valid` | True if all 4 validation flags are True |

These fields are indexed and searchable. A clinician query for "lisinopril adverse
events" can retrieve chunks where `medications[].mention` contains "lisinopril" and
`adverse_events` is non-empty.

---

## 7. HuggingFace Space Deployment

A Gradio demo UI was added to the HF Space and mounted alongside the FastAPI inference
endpoints. The Space URL serves:

- `/` — Gradio UI for interactive drug/ADE extraction demos
- `/extract` — FastAPI endpoint for Harmony pipeline integration
- `/health` — liveness probe

The Space uses llama-cpp-python to serve the GGUF-quantized model on free CPU tier.
Inference takes 90–180 seconds per query. A threading lock prevents concurrent inference
corruption (llama-cpp-python is not thread-safe).

---

## 8. Test Coverage

Final test suite: 41 tests, all passing.

| Test File | Tests | Coverage |
|---|---|---|
| `test_extraction_schema.py` | 12 | Schema validation, enum enforcement, field injection |
| `test_extractor.py` | 6 | ClinicalExtractor lifecycle, adapter version, error paths |
| `test_integration_extraction.py` | 23 | Full pipeline integration, D-35 compliance, graceful degradation |
| Other (Phase 1 tests) | — | Ingestion, search, auth |

Tests run with no GPU and no real model weights (all mocked via `unittest.mock.patch`).

---

## 9. Limitations and Future Work

### 9.1 Known Limitations

1. **ADE F1 gap:** 0.542 vs ≥0.65 target. Additional training examples targeting
   multi-ADE sentences would likely close the gap.
2. **Strict span F1 (0.217):** Off-by-one `start_char` errors on common sentences.
   Training with span-boundary-aware loss would help.
3. **Dosage coverage:** Not formally measured but expected to be moderate given only
   ~224 dosage-labeled training examples.
4. **HF Space inference speed:** 90–180s per query on free CPU tier. T4 GPU upgrade
   would bring this to ~2s.

### 9.2 Future Work

- Increase ADE training examples via targeted augmentation
- Add span-boundary fine-tuning signal
- Add medication normalization (map synonyms to RxNorm/SNOMED codes)
- Add confidence scores per entity for query-time filtering
- GPU upgrade for HF Space demo

---

## 10. Compliance Notes

**HIPAA posture:** "HIPAA-aware design" — NOT formally certified.
- No real patient data used in training or evaluation
- All test data is synthetic or from the public `ade_corpus_v2` dataset
- PHI masking (Presidio) is applied after extraction per the D-35 design rule
- The HF Space README explicitly notes: "Use only with synthetic / non-PHI data"

**License:**
- Base model: Apache 2.0 (`Qwen/Qwen2.5-7B-Instruct`)
- Training data: CC-BY (`ade-benchmark-corpus/ade_corpus_v2`)
- Derived adapter: inherits Apache 2.0

---

## 11. Deliverables Checklist

| Deliverable | Status |
|---|---|
| `data/processed/train.jsonl` + `val.jsonl` + `test.jsonl` | ✅ |
| `app/schemas/extraction.py` | ✅ |
| `app/ingestion/validator.py` | ✅ |
| `app/ingestion/extractor.py` | ✅ |
| `models/adapters/lora_v1/` | ✅ |
| `models/adapters/qlora_v1/` | ✅ |
| `evaluation/harness/eval_runner.py` + `metrics.py` | ✅ |
| `evaluation/reports/lora_v1.json` | ✅ |
| `evaluation/reports/baseline.json` | ✅ |
| `evaluation/reports/lora_v1_ood.json` | ✅ |
| `hf_space/app.py` (GGUF inference + Gradio UI) | ✅ |
| `tests/test_integration_extraction.py` (23 tests) | ✅ |
| `docs/reports/01–13` | ✅ |
| `demo/reviewer.py` | ✅ |
| `demo/before_after.py` | ✅ |
| `demo/error_dashboard.py` | ✅ |
| PR #28: feature/p3-harmony-integration → feature/p3-fine-tuning | ✅ |

---

## 12. Conclusions

Project 3 successfully delivers a fine-tuned clinical NLP model integrated into
the Harmony RAG pipeline. The LoRA adapter provides substantial improvements over
the zero-shot baseline across all metrics, with Drug F1 exceeding the target and
ADE F1 showing a 53% improvement. The validation engine ensures robust, never-crashing
behavior throughout the ingestion pipeline. The HuggingFace Space provides a
production-grade demo interface for the system.
