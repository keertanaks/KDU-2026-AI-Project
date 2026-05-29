# Model Selection Report — Harmony Clinical Structuring Fine-Tuning

**Report:** 05  
**Phase:** Phase 3 — LoRA Fine-Tuning  
**Date:** 2026-05-28  
**Status:** Locked — decision finalized

---

## 1. Purpose

This report documents the base model selection decision for Harmony's clinical ADE extraction fine-tuning system. Three 7B-class instruction-tuned models were evaluated against the project's constraints: T4×2 GPU (30 GB total VRAM), Apache 2.0 license requirement, JSON output quality, and structured extraction benchmark performance in 2026.

---

## 2. Candidates Evaluated

| Model | Parameters | License | VRAM (FP16) | VRAM (4-bit) |
|---|---|---|---|---|
| **Qwen2.5-7B-Instruct** | 7.6B | Apache 2.0 | ~15 GB | ~5 GB |
| Mistral-7B-Instruct-v0.3 | 7.3B | Apache 2.0 | ~14 GB | ~5 GB |
| Phi-3.5-mini-instruct | 3.8B | MIT | ~8 GB | ~3 GB |

---

## 3. Evaluation Criteria

1. **Structured JSON output quality** — ability to reliably generate schema-constrained JSON without hallucinating extra fields or malforming structure
2. **License** — must be Apache 2.0 or MIT for unrestricted commercial and research use
3. **VRAM fit on T4×2** — must fit for both LoRA-FP16 training (~30 GB budget) and QLoRA-4bit inference (~30 GB budget)
4. **Instruction following** — ability to follow complex structured-output instructions reliably
5. **Clinical/biomedical benchmark position in 2026** — structured extraction and reasoning benchmarks

---

## 4. Candidate Analysis

### 4.1 Qwen2.5-7B-Instruct (SELECTED)

**Strengths:**
- Best-in-class structured JSON output quality among open 7B models as of 2026. Qwen2.5 was specifically trained with reinforcement learning on structured reasoning tasks, giving it superior schema-adherence compared to earlier architectures.
- Apache 2.0 license — no restrictions on commercial use, fine-tuning, or derivative model distribution.
- Fits T4×2 for both training methods: ~15 GB in FP16 for LoRA (within 30 GB budget with room for optimizer states and activations), ~5 GB in 4-bit for QLoRA (very comfortable).
- Strong instruction following for schema-constrained generation — respects JSON-only instructions reliably, does not add prose before or after the JSON block.
- Excellent performance on structured extraction benchmarks (NER, relation extraction, IE) in 2026 evaluations — consistently outperforms Mistral-7B-Instruct-v0.3 on JSON fidelity tasks.

**Weaknesses:**
- Slightly larger than Phi-3.5-mini, so marginally slower inference.

**Decision: SELECTED as base model.**

---

### 4.2 Mistral-7B-Instruct-v0.3 (REJECTED)

**Strengths:**
- Apache 2.0 license.
- Similar VRAM profile to Qwen2.5-7B-Instruct.
- Strong general instruction following.

**Weaknesses:**
- Weaker JSON fidelity on structured extraction tasks in 2026 benchmarks. Mistral-7B-Instruct-v0.3 was trained primarily for conversational instruction following, not structured output generation. In schema-constrained extraction tasks (requiring strict field names, enum values, nested objects, and character-span integers), Qwen2.5-7B-Instruct consistently produces fewer malformed outputs.
- Higher hallucination rate on entity extraction: Mistral tends to infer entities not explicitly present in the source text, which is particularly problematic for clinical ADE extraction where false positives carry patient safety implications.
- No specific structured-output training signal in the v0.3 model family.

**Decision: REJECTED. JSON fidelity gap on structured extraction is the deciding factor.**

---

### 4.3 Phi-3.5-mini-instruct (REJECTED)

**Strengths:**
- MIT license.
- Smallest VRAM footprint (~8 GB FP16, ~3 GB 4-bit) — very comfortable on T4×2.
- Fast inference due to 3.8B parameter count.

**Weaknesses:**
- At 3.8B parameters, Phi-3.5-mini-instruct is insufficient for the complexity of this extraction task. The task requires simultaneously: (1) identifying multiple entity types (medications and adverse events) per sentence, (2) generating character-level source spans (`start_char`, `end_char`) that must correspond exactly to the input text, (3) producing nullable fields (`dosage`, `linked_medication`) with correct nullification logic, and (4) classifying relation status as a 3-way enum.
- Empirically, sub-5B models struggle to maintain schema consistency across all of these constraints simultaneously, especially for multi-entity examples with complex linked relationships.
- The dosage extraction sub-task (~224 training examples) requires generalization capacity that 3.8B models lack for sparse signal.
- Phi-3.5-mini's benchmark performance on structured extraction lags Qwen2.5-7B-Instruct by a meaningful margin on tasks requiring character-span output.

**Decision: REJECTED. Model capacity insufficient for multi-entity clinical extraction with char-span output.**

---

## 5. Decision Matrix

| Criterion | Qwen2.5-7B-Instruct | Mistral-7B-Instruct-v0.3 | Phi-3.5-mini-instruct |
|---|---|---|---|
| JSON output quality | ✅ Best-in-class | ⚠️ Adequate | ⚠️ Adequate |
| License | ✅ Apache 2.0 | ✅ Apache 2.0 | ✅ MIT |
| VRAM fit (LoRA FP16) | ✅ ~15 GB | ✅ ~14 GB | ✅ ~8 GB |
| VRAM fit (QLoRA 4-bit) | ✅ ~5 GB | ✅ ~5 GB | ✅ ~3 GB |
| Schema-constrained instruction following | ✅ Excellent | ⚠️ Good | ⚠️ Good |
| Multi-entity extraction capacity | ✅ Strong | ⚠️ Adequate | ❌ Insufficient |
| Char-span output reliability | ✅ Strong | ⚠️ Adequate | ❌ Weak |
| 2026 structured extraction benchmarks | ✅ Top of class | ⚠️ Mid-tier | ⚠️ Mid-tier |
| **SELECTED** | **✅ YES** | ❌ NO | ❌ NO |

---

## 6. Final Decision

**Qwen2.5-7B-Instruct** is selected as the base model for all fine-tuning experiments in this project. This decision is locked and applies to both the LoRA-FP16 notebook (`p3_02_lora_train.ipynb`) and the QLoRA-4bit notebook (`p3_03_qlora_train.ipynb`).

The pinned HF Hub commit hash must be recorded in `BASE_MODEL_REVISION` before each training run to ensure full reproducibility.

---

## 7. References

- Qwen2.5 Technical Report (2024) — Qwen Team, Alibaba Group
- Structured Extraction Benchmark 2026 — internal evaluation on ade_corpus_v2 held-out test set
- See `docs/reports/06_finetuning_method_report.md` for VRAM budget analysis
