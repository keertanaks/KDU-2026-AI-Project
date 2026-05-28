# Design Document

# Project 3: Harmony Clinical Structuring Fine-Tuning System

**Project**
Evaluation-First Fine-Tuning for Structured Information Extraction from Healthcare Records (Customer-Replica Extension of Harmony)

**Type**
Production Design Document — LLM Fine-Tuning + Clinical NLP + Structured Extraction

**Version**
1.0 · Draft for Implementation

**Scope**
Fine-tune a 7B decoder LLM (Qwen2.5-7B-Instruct) on `ade_corpus_v2` for structured drug/adverse-event/dosage extraction. Compare LoRA vs QLoRA. Integrate the trained adapter into the existing Harmony ingestion pipeline as an enrichment step. All training on Kaggle (T4×2, free tier). All inference local. No external LLM API calls in the inference path.

**Complexity** ⭐⭐⭐⭐

---

## 1. Executive Summary

Project 3 extends the Harmony semantic-search system with a fine-tuned clinical structuring layer. Where Harmony today retrieves and ranks documents based on free-text similarity, Project 3 adds a structured extraction step at ingestion time: each chunk of clinical text is parsed by a fine-tuned 7B decoder model into a JSON object that lists the drugs, dosages, adverse events, and drug-AE relations found in the text, each backed by a character-level evidence span.

The structured fields are written to OpenSearch alongside the existing chunk text and embedding. This unlocks three new capabilities for Harmony: (1) structured filter search ("show me documents mentioning metformin with nausea"), (2) evidence-backed result explanation in the UI, and (3) downstream reviewer workflows where a clinician sees the extracted summary instead of raw note text.

The project's primary deliverable is the fine-tuning engineering process itself — base-model selection, fine-tuning method (LoRA vs QLoRA), data format, hyperparameter strategy, evaluation harness, validation engine, and cost/environment comparison. Every modeling decision is recorded with alternatives considered and explicit rationale. The Harmony integration is the secondary deliverable.

This document is the single source of truth for every design decision made before the first training run.

---

## 2. Background and Context

The earlier Harmony project (Project 1) shipped a HIPAA-aware RAG system across mixed-format healthcare records — typed PDFs, scanned PDFs, OCR, hybrid retrieval (BM25 + HNSW kNN over OpenAI 1536-d embeddings on OpenSearch nmslib), cross-encoder reranking, role-based PHI masking via Presidio, append-only Postgres audit log, and per-document ACL enforcement. It ships at ~1000-document scale with synthetic data only and 103 passing production tests.

Harmony's ingestion pipeline (`app/api/documents.py` → `app/ingestion/`) currently writes the following per-chunk fields to OpenSearch (`app/ingestion/indexer.py`): `chunk_id, doc_id, text, embedding (1536-d), doc_type, date, phi_spans, acl`. There are no structured clinical fields. Search queries like "patients with adverse drug reactions" rely entirely on dense similarity and BM25 over the raw note text — there is no filterable structured representation of what is actually in each note.

Project 3 closes this gap. Instead of replacing the retrieval layer, it enriches the existing index with structured per-chunk metadata extracted by a fine-tuned local model. The extraction happens once per chunk at ingestion time and is reused for every subsequent query, including queries the system has never seen before. No external API calls. No PHI leaves the local environment. The fine-tuned adapter (~150-300 MB) is the only new artifact.

---

## 3. Problem Statement

Build an evaluation-first fine-tuning system that extracts structured clinical information from unstructured healthcare records and integrates the trained model into the Harmony workflow.

The fine-tuned model takes a clinical sentence or short note section as input and returns a schema-valid JSON object with: extracted entities (drugs, adverse events), each entity's mention text, each entity's character offsets in the input, the dosage when present, the drug-AE relation status, and the evidence text supporting each extraction. Outputs that fail JSON parsing, schema validation, enum validation, or evidence-substring validation must be detected and either repaired or rejected by a validation engine.

The primary engineering work is the fine-tuning process — selecting and justifying the base model, choosing and justifying the fine-tuning method (LoRA vs QLoRA, no full fine-tuning), defining the training data format (chat-format with assistant-only loss masking), running a small hyperparameter sweep (learning rate × LoRA rank), and producing a reproducible cost/environment comparison. The secondary engineering work is the Harmony integration — extending `indexer.py` with structured fields, wiring the extraction call into the `documents.py` ingestion flow, and demonstrating before/after retrieval improvement on the existing Harmony golden set.

---

## 4. Goals and Non-Goals

### 4.1 In Scope

- Fixed clinical structured-extraction dataset (`ade-benchmark-corpus/ade_corpus_v2`, all three configs).
- Fine-tuned model for structured JSON extraction from clinical text.
- Hybrid schema (enums for `entity_type`, free text for `mention`, `dosage`, `evidence`, char-offset `source_span`).
- LoRA vs QLoRA comparison on the same base model (Qwen2.5-7B-Instruct). Both trained from clean checkpoints.
- Documented justification for skipping full fine-tuning (memory and infrastructure infeasibility on Kaggle free tier).
- Chat-format training data with loss masking on the assistant turn only.
- Hyperparameter sweep: 3 LR runs + 3 LoRA-rank runs + 1 final training run = 7 runs per method.
- Evaluation harness covering JSON validity, schema validity, span F1 (strict + lenient), per-entity-type F1, enum accuracy, evidence-substring accuracy, hallucination rate, P50/P95 latency, and GPU-hours cost.
- Validation engine: Pydantic v2 schema + custom evidence-substring validator + enum validator + JSON repair fallback.
- 50–100 hand-crafted synthetic OOD eval examples to test generalization beyond PubMed sentence style.
- Ingestion-time integration into Harmony with new OpenSearch fields (`medications[]`, `adverse_events[]`, `relations[]`, `extraction_model_version`).
- Cost/environment comparison report (LoRA-FP16 vs QLoRA-4bit, training + inference).
- Bonus deliverables: P2 (constrained decoding), P5 (OpenSearch enrichment with before/after retrieval), P7 (error-analysis dashboard).

### 4.2 Out of Scope

- Fine-tuning for ICD code prediction (explicitly forbidden by the PS).
- Autonomous diagnosis or clinical decision support.
- Automated billing submission.
- Replacing certified medical coders.
- Production EHR deployment.
- Full HIPAA certification audit (BAA agreements, formal risk assessment, third-party audit).
- Sending clinical notes to hosted LLM APIs at any stage of training or inference.
- Full fine-tuning of the 7B base model (infeasible on Kaggle T4 — documented in §10.4).
- n2c2 2018 dataset (DUA registration timeline conflicts with project schedule — lead-approved decision to use `ade_corpus_v2` instead).
- Active learning loop (PS bonus P3 — deferred, not in scope for v1).
- LLM-based query rewriting at search time (PS bonus P4 — replaced by lightweight regex/keyword filter that reads ingestion-time extractions).

### 4.3 Success Criteria

The project succeeds when all of the following are true:

- Fine-tuned LoRA and QLoRA adapters are committed to the repository (or HF Hub) with config and tokenizer.
- W&B run links exist for every training run referenced in the Hyperparameter Report.
- The evaluation harness reports the eight EVAL metrics for: baseline (zero-shot Qwen2.5-7B), LoRA adapter, QLoRA adapter — on both the held-out test split and the synthetic OOD set.
- A working demo (Streamlit) shows Harmony retrieval before vs after structured-field enrichment on the existing golden set.
- Every modeling decision in §6, §8–§13 is supported by either a logged run, a committed artifact, or a written rationale in this document.
- A final report stitches the per-section deliverables together with results, failure analysis, and recommendations.

---

## 5. User Stories

### 5.1 Model-Engineering Stories

- **As an AI lead**, I can open the Model Selection Report and see why Qwen2.5-7B was chosen over Mistral-7B and Phi-3.5-mini for structured JSON extraction.
- **As an AI lead**, I can open the Fine-Tuning Method Report and see the memory, cost, and quality trade-offs between LoRA, QLoRA, and full fine-tuning, with the latter documented as infeasible on the available hardware.
- **As an evaluator**, I can open the Hyperparameter Report and see the LR sweep, rank sweep, and final config, with W&B run links for every value.
- **As an evaluator**, I can open the Evaluation Report and reproduce every metric by running the eval harness against the committed adapter checkpoints.

### 5.2 Clinical Workflow Stories

- **As a doctor**, when I open a clinical record in Harmony, I see a structured panel listing the medications mentioned, their dosages where stated, and any adverse events linked to those medications, each with the supporting sentence highlighted.
- **As a records administrator**, I can search Harmony with structured filters like `medication.mention=metformin AND adverse_event.mention=nausea` and the system returns matching documents pre-filtered by the ingestion-time extraction.
- **As a compliance reviewer**, I can audit which structured fields were generated by the fine-tuned model, which evidence spans supported them, and which extractions failed schema or evidence validation.
- **As a search user**, I get better retrieval results because the system can use structured metadata (drug name as keyword, adverse-event mention as filter) alongside dense-vector similarity.

---

## 6. Decisions Made (Decision Log)

Every decision below was made before any code was written, with alternatives considered, and is the authoritative source for the corresponding deliverable report. The Decision IDs are referenced throughout this document.

| ID | Decision Area | Decision | Why |
|---|---|---|---|
| D-01 | Dataset | `ade-benchmark-corpus/ade_corpus_v2` (all three configs: classification, drug_ade_relation, drug_dosage_relation) | Public, no DUA. Three gold-labeled configs combined give drug + dosage + ADE + relation + evidence spans. Lead-approved. n2c2 deferred due to DUA timeline. |
| D-02 | Train/Val/Test Split | 80 / 10 / 10, **grouped by unique text hash first**, then stratified by relation label within each fold | Three-way split required for hyperparameter sweep. Grouped by text hash to prevent data leakage: the same sentence can appear in multiple rows (one per drug-ADE pair), so a row-level split would put duplicates of a training sentence into the test set. |
| D-03 | Base Model | Qwen2.5-7B-Instruct | Best-in-class open model for structured JSON output in 2026. Apache 2.0 license. Fits T4×2 for QLoRA comfortably and LoRA-FP16 tightly. |
| D-04 | Fine-Tuning Method | LoRA (FP16) and QLoRA (4-bit NF4) — both run as separate Kaggle notebooks | Apples-to-apples comparison on the same base model. Direct test of "does 4-bit quantization hurt extraction F1?" |
| D-05 | Full Fine-Tuning | Not performed | Infeasible on T4×2 (30 GB VRAM) — full FT of 7B needs ~80 GB. Documented as architectural finding, not skipped work. |
| D-06 | Schema Type | Hybrid (strict enums for `entity_type` and `relation_status`; free-text for `mention`, `dosage`, `evidence`; structured object for `source_span`) | Recommended by PS §5. Enums prevent label invention; free-text fields preserve clinical flexibility. |
| D-07 | Schema Scope | Drug + Adverse Event + Dosage + Relation + Evidence Span — narrower than PS example but fully supervised | Lead-approved (Kirti). PS example assumed n2c2; we use what `ade_corpus_v2` gold-labels. No silver labels in v1. |
| D-08 | Data Format | Chat format using Qwen2.5's chat template, with `DataCollatorForCompletionOnlyLM` to mask user-turn tokens (label = -100) | Loss only on assistant JSON output. Inference uses identical chat template, no train/inference skew. |
| D-09 | Objective / Loss | Token-level cross-entropy on assistant tokens only | Standard for instruction tuning. PEFT-supported via TRL `SFTTrainer`. |
| D-10 | Hyperparameter Strategy | 7 runs total per method: 3 short LR sweep (1e-4, 2e-4, 5e-4) → 3 short rank sweep (8, 16, 32) at chosen LR → 1 final long run | Cheap, real numbers, fits Kaggle session limits. No magic numbers in the final report. |
| D-11 | LoRA Target Modules | All linear layers: `q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj` | Empirically better than QV-only on extraction tasks. ~2× adapter parameters but still <1% of base model. |
| D-12 | LoRA Alpha | `alpha = 2 × rank` (effective LR scaling = 2.0) | QLoRA-paper convention. |
| D-13 | Max Sequence Length | 256 tokens | `ade_corpus_v2` sentences are short (mean ~30, p95 ~80 tokens). 1024 wastes memory. To be re-confirmed during dataset EDA. |
| D-14 | Effective Batch Size | Micro-batch 4, grad-accum 4 → effective 16 | Fits T4×2 for both LoRA-FP16 and QLoRA. |
| D-15 | Optimizer | **LoRA notebook:** `adamw_torch`. **QLoRA notebook:** `paged_adamw_8bit` (bitsandbytes) | `paged_adamw_8bit` pages optimizer states to CPU to save GPU memory — designed for QLoRA where base is 4-bit. For LoRA-FP16 on T4×2 with gradient checkpointing, standard `adamw_torch` is more stable and avoids CPU-GPU paging overhead. |
| D-16 | Scheduler | Cosine with `warmup_ratio = 0.03`, `min_lr = peak_lr × 0.1` | Standard for SFT. Warmup ratio adapts to total steps automatically. |
| D-17 | Weight Decay | 0.0 on LoRA params | Decaying LoRA weights toward zero defeats their purpose. |
| D-18 | Gradient Checkpointing | Enabled | Required for LoRA-FP16 to fit memory. ~20% slower, ~30% less memory. |
| D-19 | Inference Decoding | Greedy: `temperature=0.0`, `do_sample=False`, `repetition_penalty=1.05`, `max_new_tokens=512` | Reproducible, deterministic, faster than sampling. Extraction is not a creative task. |
| D-20 | Retry/Repair Behavior | Three-tier: (1) parse → (2) `json_repair` library on parse failure → (3) Pydantic validation → (4) on schema fail, log and return empty `{entities: [], validation: {...}}` | Pipeline never crashes. All failures are logged for offline analysis. |
| D-21 | Validation Engine | Pydantic v2 with custom `evidence_must_be_substring` validator | Consistent with Harmony's existing `app/schemas/` Pydantic usage. v2 Rust core is fast at runtime. |
| D-22 | Experiment Tracking | Weights & Biases (W&B) | One-line setup on Kaggle, free for academic accounts, better sweep-comparison UI than MLflow. LangSmith (Harmony's tool) is for inference tracing, not training. |
| D-23 | Harmony Integration | Ingestion-time only. No model call at query time. | One extraction per document, reused across all queries. Latency: 0 at query time. Cost: 0 external API. |
| D-24 | Query-Time Structured Search | Lightweight regex/keyword layer in `search/retriever.py` reads ingestion-time extractions to build OpenSearch filters | No model call, low latency. Reuses what was already extracted. |
| D-25 | Reviewer Workflow | Streamlit UI panel reads `medications[]`/`adverse_events[]` from OpenSearch and displays the structured summary alongside retrieved chunks | Reading stored data only — no extra inference cost. Covers PS reviewer-workflow use case. |
| D-26 | Search Result Explanation | Evidence spans extracted at ingestion are surfaced in the search results UI to show *why* a document matched | Free reuse of stored extraction. Covers PS search-explanation use case. |
| D-27 | HIPAA Posture | "HIPAA-aware design suitable for controlled deployment" — not "HIPAA compliant" | No PHI in training data. No external APIs at inference. Inherits Harmony's PHI masking, ACL, audit log. Formal HIPAA certification is out of scope per PS §9. |
| D-28 | Model Artifact Storage | Adapter checkpoints (`adapter_config.json` + `adapter_model.safetensors`) under `models/adapters/{lora_v1,qlora_v1}/`. Base model downloaded once via `huggingface-cli` to `models/qwen2.5-7b/`. | Adapter alone is 150–300 MB (downloadable from Kaggle). Base model 15 GB downloaded once locally, not re-downloaded per inference. |
| D-29 | Guardrails | Six-layer defense: constrained decoding → Pydantic schema → enum check → evidence-substring check → confidence threshold → audit log | Layered defense in depth. Each layer catches a different failure mode. |
| D-30 | Synthetic OOD Eval | 50–100 hand-crafted clinical-style sentences via Claude/GPT-4, committed as `evaluation/synthetic_ade_eval.jsonl`, never seen in training | Tests generalization beyond PubMed case-report style. Cheap, high signal. |
| D-31 | Baseline Comparison | Three-way: (a) zero-shot Qwen2.5-7B-Instruct, (b) LoRA fine-tuned, (c) QLoRA fine-tuned — all evaluated on the same test set and OOD set | Proves fine-tuning improves over the base model. Required for the "original vs fine-tuned" comparison report. |
| D-32 | Bonus Items | P2 (constrained decoding), P5 (OpenSearch enrichment + before/after retrieval), P7 (error-analysis dashboard). Skip P1 (FFT — infeasible), P3 (active learning — too much scope), P4 (full LLM query rewriter — replaced by lightweight regex). P6 (schema ablation) is optional. | High ROI, low effort. P2 directly improves EVAL-02 and EVAL-03. P5 proves workflow impact. P7 is the error story for the final report. |
| D-33 | Branch Strategy | One umbrella branch `feature/p3-fine-tuning` off main. Feature sub-branches (`p3-data-prep`, `p3-schema`, `p3-lora`, `p3-qlora`, `p3-evaluation`, `p3-integration`, `p3-demo`) each PR into the umbrella branch incrementally. Final single PR `feature/p3-fine-tuning → main`. | Incremental review (lead can comment on each piece) + clean single PR at the end (lead-requested). |
| D-34 | Schema Version | `schema_version: "v1"` embedded in every extraction output and in adapter config | Forward-compatibility. Future schema changes increment to v2 without invalidating v1 extractions. |
| D-35 | Extraction Order vs PHI Masking | Run extraction on **original text before PHI masking**. After extraction, apply Presidio to the `mention` and `evidence` fields in the extraction output to strip any PHI that leaked in. | PHI masking shifts character offsets — running extraction after masking makes all `source_span` values wrong relative to the original document. Drug names and ADE mentions are NOT PHI (they are clinical findings, not identity information), so running extraction on unmasked text is safe. The final stored extraction fields are then PHI-checked before indexing. |

---

## 7. System Architecture

### 7.1 High-Level Architecture (Two Planes)

Project 3 introduces a new **extraction plane** that runs alongside Harmony's existing ingestion and search planes. The planes share OpenSearch, the audit log, and the auth layer. They do not share GPU resources — extraction is CPU-feasible at small scale and GPU-accelerated when available.

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                                  CLIENT TIER                                          │
│  React Frontend (Vite, Tailwind) ── Search UI ── Upload UI ── Reviewer Panel (NEW)    │
└────────────────────────────────────────┬─────────────────────────────────────────────┘
                                         │ HTTPS / Session Auth
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                          API TIER  (FastAPI, Python 3.11)                            │
│   /api/documents (upload) ── /api/search ── /api/audit ── /api/extraction (NEW)      │
└────────────────────────────────────────┬─────────────────────────────────────────────┘
                                         │
                ┌────────────────────────┼────────────────────────────┐
                ▼                        ▼                            ▼
┌──────────────────────────┐  ┌─────────────────────────┐  ┌────────────────────────┐
│   INGESTION PLANE        │  │     SEARCH PLANE        │  │  EXTRACTION PLANE      │
│   (existing Harmony)     │  │     (existing Harmony)  │  │  (Project 3 — NEW)     │
│                          │  │                         │  │                        │
│  Classifier → OCR        │  │  Normalize → Embed      │  │  Tokenize → Generate   │
│   → TextCleaner          │  │   → Hybrid Retrieve     │  │   (Qwen2.5-7B base     │
│   → Chunker              │  │   → Rerank (BGE)        │  │    + LoRA/QLoRA        │
│   → PhiTagger            │  │   → Mask (role-based)   │  │    adapter)            │
│   → Embedder ──────┐     │  │   → Respond             │  │   → Pydantic Validate  │
│                    │     │  │                         │  │   → Evidence Check     │
│                    │     │  │   Reads structured      │  │   → JSON Repair        │
│   → Extractor (NEW)│     │  │   fields written by     │  │   → Audit              │
│         │          │     │  │   the Extraction Plane  │  │                        │
│         ▼          │     │  │                         │  │  Loaded once at API    │
│   → Validator (NEW)│     │  │                         │  │  startup (lazy init).  │
│         │          │     │  │                         │  │  Local GPU/CPU only.   │
│         ▼          │     │  │                         │  │  No external APIs.     │
│   → Indexer ──────►│     │  │                         │  │                        │
└──────────┬─────────┘─────┘  └──────────────┬──────────┘  └────────────┬───────────┘
           │                                 │                          │
           ▼                                 ▼                          ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                         DATA / STORAGE TIER                                          │
│                                                                                       │
│  OpenSearch (k-NN nmslib)        S3 (SSE-KMS)     Postgres (append-only audit)       │
│  ─ chunk_id, doc_id, text        ─ source PDFs    ─ query_hash, user, doc_ids,       │
│  ─ embedding (1536-d)                              ─ extraction_model_version (NEW), │
│  ─ doc_type, date, phi_spans                        latency, ts                      │
│  ─ acl                                                                                │
│  ─ medications[] (NEW)                                                                │
│  ─ adverse_events[] (NEW)                                                             │
│  ─ relations[] (NEW) — drug↔ADE pairs for joint queries                               │
│  ─ extraction_model_version (NEW)                                                     │
│                                                                                       │
│  Local Filesystem: models/qwen2.5-7b/  +  models/adapters/{lora_v1, qlora_v1}/       │
└──────────────────────────────────────────────────────────────────────────────────────┘
                                         ▲
                                         │
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                    OFFLINE TRAINING ENVIRONMENT (Kaggle, separate)                    │
│                                                                                       │
│   ade_corpus_v2 (HF Hub) ─► Data Prep Notebook ─► train.jsonl, val.jsonl, test.jsonl │
│                                                                                       │
│   train.jsonl ─► LoRA  Notebook (Kaggle Account 1, T4×2)  ─► adapter_model.safetensors│
│   train.jsonl ─► QLoRA Notebook (Kaggle Account 2, T4×2)  ─► adapter_model.safetensors│
│                                                                                       │
│   W&B logs ─► sweep runs, final runs, latency, memory ─► Hyperparameter Report       │
│                                                                                       │
│   Adapters downloaded as zips → committed to models/adapters/ in main repo           │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

### 7.2 Ingestion-Time Extraction Flow (Detailed)

```
Upload → Classify → OCR/PyMuPDF → TextCleaner → Chunker
                                                   │
                                          (original text, no PHI masking yet)
                                                   │
                              ┌────────────────────┤
                              ▼                    ▼
                   ┌──────────────────┐   ┌──────────────────┐
                   │  Extractor (NEW) │   │  PhiTagger       │
                   │  Qwen2.5-7B      │   │  (Presidio)      │
                   │  + LoRA adapter  │   │  masks PHI for   │
                   │                  │   │  stored text and │
                   │  runs on ORIGINAL│   │  embedder        │
                   │  text — offsets  │   └────────┬─────────┘
                   │  are correct     │            │ (masked text)
                   └────────┬─────────┘            ▼
                            │             ┌──────────────────┐
                            │             │  Embedder        │
                            │             └────────┬─────────┘
                            ▼                      │
                   ┌──────────────────┐            │
                   │ Validator (NEW)  │            │
                   │ 1. json.loads()  │            │
                   │ 2. json_repair() │            │
                   │ 3. Pydantic v2   │            │
                   │ 4. Evidence chk  │            │
                   │ 5. PHI-strip     │ ← Presidio on mention/evidence
                   │    output fields │   fields only (NOT the spans)
                   └────────┬─────────┘            │
                            │                      │
                            └──────────┬───────────┘
                                       ▼
                              ┌──────────────────┐
                              │  Indexer         │
                              │  writes:         │
                              │  text (masked),  │
                              │  embedding,      │
                              │  medications[],  │
                              │  adverse_events[]│
                              │  relations[]     │
                              │  → OpenSearch    │
                              └──────────────────┘
```

**Why extraction runs on original text (D-35):** PHI masking replaces spans with tokens like `[PERSON]` — this shifts all character offsets after each masked span. Running extraction after masking produces `source_span` values that are wrong relative to the original document text. Drug names and ADE mentions are clinical findings, not PHI (Presidio does not tag drug names as PHI), so the extractor seeing unmasked text is safe. After extraction, Presidio runs on the output fields (`mention`, `evidence`) as a secondary PHI-strip check before the result is stored.

### 7.3 Why a Separate Plane

- **Failure isolation.** If the extraction model crashes, OOMs, or returns malformed JSON, the ingestion plane still completes (chunk + embedding + PHI tags written, extraction fields written as empty with `validation.json_valid: false`). The document is still searchable by dense vector and BM25 — just without structured filters.
- **Lazy loading.** The model is loaded on first call via Harmony's existing `_get_*()` singleton pattern (see `app/api/documents.py` lines 50–80). Startup cost is paid once, not per request.
- **No GPU coupling.** If no local GPU is available, the model runs on CPU at ~5–10× slower throughput, but the pipeline still works.

---

## 8. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| **Dataset** | `ade-benchmark-corpus/ade_corpus_v2` (HF Hub, all 3 configs) | Public, no DUA, gold-labeled drug + ADE + dosage + spans. |
| **Base Model** | Qwen2.5-7B-Instruct (HF Hub) | Best open 7B for JSON, Apache 2.0, strong instruction-following. |
| **Fine-Tuning Framework** | HuggingFace `transformers` + `peft` + `trl` (SFTTrainer) + `bitsandbytes` | Industry standard, well-documented LoRA/QLoRA support. |
| **Tokenizer** | Qwen2.5 native tokenizer | Comes with the base model. Same tokenizer used for train and inference. |
| **Quantization (QLoRA only)** | bitsandbytes 4-bit NF4 with double-quant | Standard QLoRA paper config. |
| **Validation** | Pydantic v2 + `json_repair` | Matches Harmony's `app/schemas/` convention. Rust core is fast. |
| **Experiment Tracking** | Weights & Biases | One-line Kaggle setup. Free academic. Best sweep UI. |
| **Training Hardware** | Kaggle T4×2 (30 GB total VRAM, free tier) | Free, sufficient for QLoRA-7B and tight-but-feasible for LoRA-FP16-7B. |
| **Inference Hardware** | Local GPU (RTX 3060+ for LoRA-merged, RTX 4060+ for QLoRA-loaded) or CPU fallback | No cloud, no APIs. HIPAA-friendly. |
| **Search Integration** | OpenSearch (existing Harmony index, schema extended) | No new infrastructure. |
| **API** | FastAPI (existing Harmony API, new endpoint `/api/extraction` for debugging) | Existing stack. |
| **UI** | Streamlit for the reviewer dashboard + error-analysis dashboard | Faster to ship than extending the React frontend; Project 1 used Streamlit for similar internal tools. |
| **Constrained Decoding (Bonus P2)** | `lm-format-enforcer` | Lighter than `outlines`, integrates cleanly with HF generate(). |

---

## 9. Dataset Design

### 9.1 Dataset: `ade-benchmark-corpus/ade_corpus_v2`

| Config | Fields | Examples | Use in Training |
|---|---|---|---|
| `Ade_corpus_v2_classification` | `text`, `label ∈ {0, 1}` | ~23,000 | Negative examples (when `label=0`): target output has empty `entities` and `relation_status="none"`. |
| `Ade_corpus_v2_drug_ade_relation` | `text`, `drug`, `effect`, `indexes.drug.{start,end}_char`, `indexes.effect.{start,end}_char` | ~6,800 | Primary positive examples: drug + ADE + relation=related + spans. |
| `Ade_corpus_v2_drug_dosage_relation` | `text`, `drug`, `dosage`, `indexes.drug.{start,end}_char`, `indexes.dosage.{start,end}_char` | ~280 | Dosage examples: drug + dosage + spans (relation field set to `none` unless an ADE also appears). |

**Combination strategy.** Each row across the three configs becomes one training example with the target JSON populated from whatever fields that row provides. We use all three configs together — the model learns to output empty/partial schemas when fields are missing, which exactly matches real inference behavior.

**Total training examples.** ~30,000 across all three configs after de-duplication on `text`.

**Dataset risks (and mitigations):**

- **Style mismatch:** `ade_corpus_v2` sentences are PubMed case reports, not real clinical-note style. Mitigation: 50–100 hand-crafted synthetic OOD examples in `evaluation/synthetic_ade_eval.jsonl` test generalization.
- **Sentence-level, not document-level:** Each example is one sentence. Mitigation: at ingestion time, Harmony's chunker already splits documents into short chunks (`app/ingestion/chunker.py`). The model sees one chunk at a time, which matches training conditions.
- **Schema narrower than PS example:** No frequency, route, action, assertion_status. Mitigation: lead-approved (Kirti, recorded above the message thread). Documented as honest scope reduction, not silver-labeling.
- **Class imbalance:** ~6,800 drug-ADE positives but ~16,000 classification negatives. Mitigation: stratified split (D-02), F1 metric (not accuracy), per-class F1 reporting in EVAL-05.
- **Dosage examples very small (~280 rows):** After 80/10/10 split, only ~224 training examples for dosage. The model may not learn dosage extraction reliably. Mitigation: treat dosage as a **best-effort** field. EVAL-05c target is lowered to ≥ 0.40 (not 0.60). Document as a known limitation of `ade_corpus_v2` in the final report.
- **Duplicate sentences across rows:** One sentence can produce multiple rows (one per drug-ADE pair). Mitigation: split grouped by unique text hash (D-02) to prevent leakage.

### 9.2 Train/Val/Test Split (D-02)

- **80 / 10 / 10**, grouped by unique text hash first, then stratified by relation label within each fold.
- **Why text-hash grouping:** The same sentence can appear in multiple rows (e.g., one row per drug-ADE pair in a multi-entity sentence). A row-level split leaks seen sentences into the test set. Grouping by `hashlib.md5(text.encode()).hexdigest()` ensures every row sharing a sentence stays in the same fold.
- Seeded (`seed=42`) for full reproducibility.
- Test split touched **once** — only for the final reporting numbers. Validation split used for the sweep.

| Split | Approx Size | Use |
|---|---|---|
| Train | ~24,000 | LoRA + QLoRA training |
| Validation | ~3,000 | Hyperparameter sweep, early stopping |
| Test | ~3,000 | Final reporting only |

### 9.3 Synthetic OOD Eval (D-30)

- 50–100 hand-crafted sentences in clinical-note style: telegraphic abbreviations (`Pt c/o N/V`), multi-drug sentences, negation (`no rash`), dosage variations (`5 mg PO daily`), and no-ADE sentences.
- Authored once via Claude/GPT-4 with manual review, committed as `evaluation/synthetic_ade_eval.jsonl`.
- Never appears in training or validation.

---

## 10. Schema Design (v1)

### 10.1 Output Schema

The schema has two parts: **what the model generates** and **what the system wrapper adds**. The model never sees or outputs `record_id` or `validation` — these are injected by the inference wrapper after generation and validation.

**Model output (what the model is trained to produce):**
```json
{
  "schema_version": "v1",
  "entities": [
    {
      "entity_type": "medication",
      "mention": "metformin",
      "dosage": "500 mg",
      "evidence": "started on metformin 500 mg",
      "source_span": {"start_char": 12, "end_char": 21}
    },
    {
      "entity_type": "adverse_event",
      "mention": "nausea",
      "linked_medication": "metformin",
      "evidence": "developed nausea after dose increase",
      "source_span": {"start_char": 46, "end_char": 52}
    }
  ],
  "relation_status": "related"
}
```

**Full system output (after wrapper adds record_id + validation flags):**
```json
{
  "record_id": "chunk_abc123",
  "schema_version": "v1",
  "entities": [...],
  "relation_status": "related",
  "validation": {
    "json_valid": true,
    "schema_valid": true,
    "enum_valid": true,
    "evidence_present": true
  }
}
```

**Why separate:** `record_id` changes per chunk and the model cannot learn to generate it (it would just copy an arbitrary string). `validation` is a post-hoc assessment of the model's own output — training the model to output validation flags would teach it to always claim success, because all training examples are valid by definition.

### 10.2 Field Specification

| Field | Type | Enum / Free | Required | Source in Dataset |
|---|---|---|---|---|
| `record_id` | string | free | yes | **System-injected** (not model-generated). Added by inference wrapper from chunk_id. |
| `schema_version` | string | enum `["v1"]` | yes | Hard-coded in prompt. Model learns to repeat it. |
| `entities[]` | list | — | yes (may be empty) | Constructed from dataset. |
| `entity_type` | string | **enum** `["medication", "adverse_event"]` | yes | drug → medication; effect → adverse_event. |
| `mention` | string | free | yes | `text[start_char:end_char]` from indexes. |
| `dosage` | string \| null | free | no | From `drug_dosage_relation` config. |
| `linked_medication` | string \| null | free | no (adverse_event only) | The drug mention in the same sentence. |
| `evidence` | string | free | yes | Sentence-level supporting text. |
| `source_span` | object | — | yes | `{start_char: int, end_char: int}`. |
| `relation_status` | string | **enum** `["related", "not_related", "none"]` | yes | From dataset: positive → related; negative → not_related; no entity → none. |
| `validation.*` | bool | — | yes | **System-injected** (not model-generated). Populated by Pydantic wrapper after generation. Never in training targets. |

### 10.3 Why Hybrid (D-06)

- **Strict enums (`entity_type`, `relation_status`, `schema_version`)**: the model cannot invent new entity types or relation labels. Easy to measure (enum-accuracy metric, EVAL-06). Safer outputs.
- **Free text (`mention`, `dosage`, `evidence`)**: clinical text is too varied for enums. Drug names alone number in the thousands. Char-offset `source_span` provides ground-truth localization regardless of free-text content.
- **Optional fields (`dosage`, `linked_medication`)**: dataset rows don't always have these. Model learns to emit `null` when absent — important real-world behavior.

### 10.4 Why Not the Full PS Schema (D-07)

The PS example shows `assertion_status`, `certainty`, `medication_action`, `temporal_status`. These are **not present in `ade_corpus_v2`**. Options were:

- **(A) Drop them — what we chose.** Honest, fully supervised, smaller schema.
- **(B) Silver-label via GPT-4.** Adds risk: errors propagate into training. Lead declined.
- **(C) Switch to n2c2 2018.** DUA timeline conflicts with project schedule. Lead declined.

The dropped fields are explicitly recorded as "not in scope for v1" in §4.2. v2 of the schema can add them if a richer dataset becomes available.

---

## 11. Data Format and Prompt Design

### 11.1 Chat Format (D-08)

Each training example is a two-turn chat:

```
[
  {"role": "user", "content": "<INSTRUCTION>\n\nClinical text:\n<TEXT>"},
  {"role": "assistant", "content": "<JSON_OUTPUT>"}
]
```

The Qwen2.5 chat template is applied via `tokenizer.apply_chat_template(...)`. The `DataCollatorForCompletionOnlyLM` from TRL masks the user-turn tokens (sets `label = -100`) so loss is computed only over the assistant turn.

### 11.2 Instruction Template

```
You are a clinical information extractor. Given a clinical text, extract all
medications and adverse events as a JSON object that follows the schema below.
Return ONLY valid JSON. If no entity is present, return entities=[] and
relation_status="none".

Return ONLY this JSON structure (no record_id, no validation block — those are added by the system):
{
  "schema_version": "v1",
  "entities": [
    {
      "entity_type": "medication" | "adverse_event",
      "mention": "<string>",
      "dosage": "<string>" | null,        // for medications only, null otherwise
      "linked_medication": "<string>" | null, // for adverse_events only, null otherwise
      "evidence": "<string>",
      "source_span": {"start_char": <int>, "end_char": <int>}
    }
  ],
  "relation_status": "related" | "not_related" | "none"
}

Clinical text:
<TEXT>
```

The instruction is identical at train and inference time. No prompt drift.

### 11.3 Why Chat Format Over Raw Instruction

- Qwen2.5 is trained natively as a chat model — its strongest performance is via the chat template.
- Loss masking on user turn is trivial with TRL's collator. Raw instruction strings make loss masking error-prone.
- Inference uses the same `apply_chat_template` call — guarantees zero train/inference template skew.

---

## 12. Training Design

### 12.1 SFT / PEFT / LoRA / QLoRA — How They Stack

These are not four separate methods to combine. They layer:

```
SFT (Supervised Fine-Tuning)               ← the training paradigm
  └── PEFT (parameter-efficient toolkit)   ← the library (HF peft)
        └── LoRA (low-rank adaptation)     ← the technique
              └── QLoRA = LoRA + 4-bit base model quantization
```

Both Project 3 notebooks do SFT, both use the PEFT library, both apply LoRA. The QLoRA notebook additionally quantizes the base model to 4-bit NF4. The LoRA notebook keeps the base model in FP16.

### 12.2 LoRA Configuration (D-11, D-12)

```python
peft_config = LoraConfig(
    r=16,                                    # tuned by sweep
    lora_alpha=32,                           # 2 × r
    target_modules=["q_proj","k_proj","v_proj","o_proj",
                    "gate_proj","up_proj","down_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
)
```

**Why target all linear layers, not just QV?** PEFT's default `(q_proj, v_proj)` is for chat assistants. For structured extraction, attaching to all linear projections measurably improves F1 (Hu et al., LoRA paper §5.4; QLoRA paper §3). Parameter count is still <1% of base.

### 12.3 QLoRA Configuration

```python
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_use_double_quant=True,
    bnb_4bit_compute_dtype=torch.float16,   # NOT bfloat16 — T4 (Turing) has no native BF16
)                                            # BF16 on T4 falls back to slow SW emulation
```

LoRA config is identical to LoRA-FP16 above — only the base model loading differs. This makes the comparison clean: any F1 gap is attributable to 4-bit quantization, not different LoRA configurations.

### 12.4 Why No Full Fine-Tuning (D-05)

| Method | VRAM needed (Qwen2.5-7B, seq_len=256, bs=4) | T4×2 (30 GB) verdict |
|---|---|---|
| Full FT FP16 | ~80 GB (weights + Adam states + activations + grads) | ❌ Impossible |
| LoRA FP16 | ~24 GB | ✅ Tight, with checkpointing + paged optimizer |
| QLoRA 4-bit | ~9 GB | ✅ Comfortable |

Full fine-tuning is documented as **infeasible on available hardware**, not as a skipped experiment. The Fine-Tuning Method Report includes the memory math above as the justification.

### 12.5 Kaggle Training Plan

- **Team member 1 (their own Kaggle account):** LoRA-FP16 notebook on T4×2. Internet enabled (for HF model download). GPU accelerator = "GPU T4 x2".
- **Team member 2 (their own Kaggle account):** QLoRA-4bit notebook on T4×2. Same settings.
- **Note on accounts:** Each team member uses their own personal Kaggle account. Kaggle TOS prohibits one person operating multiple accounts to gain extra compute — these are two different team members' accounts.
- **Both notebooks** download `Qwen/Qwen2.5-7B-Instruct` at a **pinned revision** once (cached in `/kaggle/working/`). Pin the revision hash at notebook start to ensure reproducibility across sessions:
  ```python
  model = AutoModelForCausalLM.from_pretrained(
      "Qwen/Qwen2.5-7B-Instruct",
      revision="abc123",   # replace with actual commit hash from HF Hub
      ...
  )
  ```
  Record the revision hash in `models/adapters/{lora_v1,qlora_v1}/training_args.json`.
- **Outputs:** `/kaggle/working/adapter/adapter_model.safetensors` + `adapter_config.json` + `tokenizer/`. Downloaded as zip, committed to `models/adapters/{lora_v1, qlora_v1}/` in the repo (or pushed to a private HF Hub repo if too large for git LFS).

### 12.6 Why Two Accounts

Kaggle session limit is 12 hours per session and 30 GPU-hours per week per account. Both sweeps fit per-account, but running them in parallel halves wall-clock time and isolates failure (one notebook crashing doesn't lose both sets of results).

### 12.7 Resumability

Save full checkpoints every 100 steps with `save_total_limit=2`. If a Kaggle session times out mid-training, the next session resumes from the latest checkpoint via `trainer.train(resume_from_checkpoint=True)`.

---

## 13. Hyperparameter Selection Strategy (D-10)

### 13.1 The Sweep — 7 Runs per Method

| Phase | Runs | Variable | Fixed | Steps | Purpose |
|---|---|---|---|---|---|
| 1. LR Sweep | 3 | `lr ∈ {1e-4, 2e-4, 5e-4}` | `r=16`, `α=32` | 500 | Pick best LR by val F1. |
| 2. Rank Sweep | 3 | `r ∈ {8, 16, 32}` (`α = 2r`) | best LR from Phase 1 | 500 | Pick best rank by val F1. |
| 3. Final Run | 1 | best LR, best rank | — | 3 epochs (~5000 steps) | Production adapter. |

Total: 7 runs per notebook × 2 notebooks = 14 runs. Estimated GPU time: ~6–8 hours per Kaggle account (well within 30 GPU-hours/week limit).

### 13.2 Why Sweep Instead of Defaults

The QLoRA-paper defaults (`lr=2e-4, r=16, α=32`) are good for general assistant tuning. For narrow structured-extraction tasks, the optimal rank is often lower (r=8 is enough for narrow tasks per Hu et al. §6.1). The sweep takes ~3 hours and produces *real* numbers for the Hyperparameter Report instead of "we used the paper defaults."

### 13.3 Final Locked Defaults (Applied to All Runs)

| Parameter | Value | Rationale |
|---|---|---|
| `max_seq_length` | 256 | `ade_corpus_v2` p95 length is ~80 tokens. To be confirmed during EDA; expand to 512 if EDA shows otherwise. |
| `per_device_train_batch_size` | 4 | Fits T4 with seq_len=256. |
| `gradient_accumulation_steps` | 4 | Effective batch = 16. |
| `num_train_epochs` | 3 (with early stopping on val F1) | Standard for SFT; early stopping prevents overfit on small dataset. |
| `optimizer` | **LoRA:** `adamw_torch`  /  **QLoRA:** `paged_adamw_8bit` | `paged_adamw_8bit` is designed for QLoRA (CPU-pages optimizer states). For LoRA-FP16, `adamw_torch` is more stable and avoids paging overhead. |
| `lr_scheduler_type` | cosine | Smooth decay to min_lr. |
| `warmup_ratio` | 0.03 | ~3% of total steps. |
| `weight_decay` | 0.0 | On LoRA params; do not decay. |
| `gradient_checkpointing` | True | Memory necessity for LoRA-FP16. |
| `fp16` | **LoRA:** True  /  **QLoRA:** True (compute dtype `float16`) | T4 is Turing architecture — no native BF16 hardware. Using `float16` throughout. BF16 on T4 is software-emulated and ~2× slower. |
| `logging_steps` | 10 | Frequent W&B logging. |
| `evaluation_strategy` | "steps", `eval_steps=100` | Val F1 every 100 steps. |
| `save_strategy` | "steps", `save_steps=100`, `save_total_limit=2` | Resumable checkpoints. |
| `load_best_model_at_end` | True | Restore best val F1 checkpoint at end of training. |
| `metric_for_best_model` | `eval_overall_f1` | Custom metric registered in the trainer. |
| `seed` | 42 | Reproducibility. |

### 13.4 Stop-Loss Rules

- If val F1 doesn't improve for 3 consecutive eval steps → early stop.
- If train loss diverges (NaN, inf) → kill the run, log to W&B, lower LR.
- If GPU OOM → reduce micro-batch to 2 and double grad_accum.

---

## 14. Evaluation Plan

### 14.1 EVAL-01 to EVAL-08 — What We Measure

| ID | Metric | Definition | Target | Computed By |
|---|---|---|---|---|
| EVAL-01 | Metrics defined pre-training | This table itself, committed before first run | ✅ this doc | — |
| EVAL-02 | JSON validity | % of outputs that `json.loads()` successfully (before repair) | ≥ 95% | Eval harness |
| EVAL-02b | JSON validity (post-repair) | % after `json_repair` fallback | ≥ 99.5% | Eval harness |
| EVAL-03 | Schema validity | % of outputs that pass Pydantic validation | ≥ 90% | Pydantic |
| EVAL-04 | Span F1 (strict) | Exact char-offset match | ≥ 0.65 | Eval harness |
| EVAL-04b | Span F1 (lenient, IoU ≥ 0.5) | Token overlap | ≥ 0.75 | Eval harness |
| EVAL-05a | Drug F1 | Per-entity-type F1 for medications | ≥ 0.75 | Eval harness |
| EVAL-05b | ADE F1 | Per-entity-type F1 for adverse events | ≥ 0.65 | Eval harness |
| EVAL-05c | Dosage F1 | Field-level F1 for dosage | ≥ 0.40 (best-effort — only ~224 training examples) | Eval harness |
| EVAL-05d | Relation F1 | Drug-ADE relation classification F1 | ≥ 0.70 | Eval harness |
| EVAL-06 | Enum accuracy | % outputs where `entity_type` and `relation_status` use allowed values | ≥ 98% | Pydantic |
| EVAL-07 | Evidence accuracy | % outputs where `evidence` is a substring of input text | ≥ 90% | Custom validator |
| EVAL-08 | Hallucination rate | % extracted entities whose `mention` is not a substring of input | ≤ 5% | Eval harness |

**Operational metrics (also tracked):**

- P50 / P95 inference latency (ms per chunk), separate for CPU and GPU.
- GPU-hours per training run (logged by W&B).
- Adapter file size (MB).
- Peak VRAM during training (logged by W&B system metrics).

### 14.2 Test Sets

1. **Held-out test split (~3000 examples)** from `ade_corpus_v2`. Same distribution as training. Primary reporting set.
2. **Synthetic OOD set (50–100 examples)** in clinical-note style. Generalization test. Reported separately.
3. **Harmony golden set (`evaluation/golden_set.jsonl`)** — used for the retrieval before/after demo (bonus P5), not for direct extraction F1.

### 14.3 Three-Way Comparison (D-31)

Every metric is reported for three configurations:

| Configuration | Description |
|---|---|
| **Baseline** | Zero-shot Qwen2.5-7B-Instruct with the same prompt. No fine-tuning. |
| **LoRA** | Qwen2.5-7B + LoRA adapter (FP16). |
| **QLoRA** | Qwen2.5-7B + QLoRA adapter (4-bit NF4). |

This proves (a) fine-tuning improves over base, (b) whether 4-bit quantization hurts F1, (c) which deployment configuration to use locally.

### 14.4 Reports

Stored as JSON under `evaluation/reports/`:

- `baseline.json`, `lora_v1.json`, `qlora_v1.json` — all eight EVAL metrics + operational metrics.
- `comparison.md` — auto-generated Markdown table summarizing the three configurations.
- `error_analysis.json` — sample of failed extractions for the error dashboard (bonus P7).

---

## 15. Validation and Guardrail Pipeline

### 15.1 The Six-Layer Defense (D-29)

```
Model Output (raw string)
  │
  ▼
┌─────────────────────────────────────┐
│ Layer 1: Constrained Decoding       │  ← bonus P2; lm-format-enforcer
│  Forces grammar-valid JSON at gen   │     guarantees EVAL-02 ~100%
│  time. Skipped if not enabled.      │
└──────────┬──────────────────────────┘
           ▼
┌─────────────────────────────────────┐
│ Layer 2: JSON Parse                 │
│  json.loads() → if fail, json_repair│
└──────────┬──────────────────────────┘
           ▼
┌─────────────────────────────────────┐
│ Layer 3: Pydantic Schema Validation │
│  ExtractionResult.model_validate()  │
│  Catches: missing fields, wrong     │
│  types, invalid enums.              │
└──────────┬──────────────────────────┘
           ▼
┌─────────────────────────────────────┐
│ Layer 4: Evidence Substring Check   │
│  For each entity, verify            │
│  text[span.start:span.end] ==       │
│  entity.mention (or close match).   │
│  Verify evidence ⊂ input text.      │
└──────────┬──────────────────────────┘
           ▼
┌─────────────────────────────────────┐
│ Layer 5: PHI Leak Check             │
│  Run Presidio on the JSON output.   │
│  Reject if PHI tokens appear.       │
│  (Inherits Harmony's PhiTagger.)    │
└──────────┬──────────────────────────┘
           ▼
┌─────────────────────────────────────┐
│ Layer 6: Audit Log                  │
│  Write extraction_id, model_version,│
│  validation flags, latency to       │
│  Postgres audit log.                │
└──────────┬──────────────────────────┘
           ▼
       Stored in OpenSearch
```

### 15.2 Pydantic Schema (Code-Ready)

```python
# app/schemas/extraction.py (new file)
from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator

class SourceSpan(BaseModel):
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)

class Entity(BaseModel):
    entity_type: Literal["medication", "adverse_event"]
    mention: str = Field(min_length=1)
    dosage: Optional[str] = None
    linked_medication: Optional[str] = None
    evidence: str = Field(min_length=1)
    source_span: SourceSpan

class ValidationFlags(BaseModel):
    json_valid: bool
    schema_valid: bool
    enum_valid: bool
    evidence_present: bool

class ExtractionResult(BaseModel):
    record_id: str
    schema_version: Literal["v1"]
    entities: list[Entity]
    relation_status: Literal["related", "not_related", "none"]
    validation: ValidationFlags

    @model_validator(mode="after")
    def check_spans_make_sense(self) -> "ExtractionResult":
        for e in self.entities:
            if e.source_span.end_char <= e.source_span.start_char:
                raise ValueError(f"Invalid span for {e.mention}")
        return self
```

The evidence-substring check is applied separately by the inference wrapper because it needs the original input text, which Pydantic doesn't see.

### 15.3 Inference Wrapper (Code-Ready)

```python
# app/ingestion/extractor.py (new file)
def extract(text: str, record_id: str) -> ExtractionResult:
    prompt = build_chat_prompt(text)
    raw = model.generate(prompt, **gen_config)

    # Layer 2
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        try:
            parsed = json_repair.loads(raw)
        except Exception:
            return empty_result(record_id, reason="json_parse_failed")

    # Layer 3
    try:
        result = ExtractionResult.model_validate(parsed)
    except ValidationError:
        return empty_result(record_id, reason="schema_invalid")

    # Layer 4
    for e in result.entities:
        if e.evidence not in text:
            result.validation.evidence_present = False
            # Don't reject — record the failure and continue.

    return result
```

---

## 16. Inference Plan (D-19, D-20)

### 16.1 Decoding Configuration

```python
generation_config = {
    "do_sample": False,
    "temperature": 0.0,
    "max_new_tokens": 512,
    "repetition_penalty": 1.05,
    "pad_token_id": tokenizer.eos_token_id,
}
```

**Why greedy?** Extraction is deterministic — the same input must produce the same output to be useful at search time. Sampling adds noise without benefit on this task.

**Why max_new_tokens=512?** A typical extraction JSON for a single sentence is ~150–250 tokens. 512 leaves headroom for multi-entity sentences.

**Why repetition_penalty=1.05?** Gentle penalty prevents the model from looping on `}}}}}` when JSON generation drifts. Higher values distort valid output.

### 16.2 Constrained Decoding (Bonus P2)

When enabled via `EXTRACTION_CONSTRAINED=true` env var:

```python
from lmformatenforcer import JsonSchemaParser
from lmformatenforcer.integrations.transformers import build_transformers_prefix_allowed_tokens_fn

parser = JsonSchemaParser(ExtractionResult.model_json_schema())
prefix_fn = build_transformers_prefix_allowed_tokens_fn(tokenizer, parser)

raw = model.generate(prompt, prefix_allowed_tokens_fn=prefix_fn, **gen_config)
```

Guarantees EVAL-02 = 100% and EVAL-03 ≥ 99% at the cost of ~10–20% slower generation. Reported as a before/after metric in the bonus deliverable.

### 16.3 Deployment Mode

- **Lazy singleton** following Harmony's pattern (`_get_embedder()`, `_get_phi()` in `app/api/documents.py`).
- **First call cost:** ~10s model load (CPU) or ~3s (GPU).
- **Steady-state cost:** ~1.5s per chunk on T4-class GPU, ~5–8s on CPU.
- **Env vars:** `EXTRACTION_ADAPTER_PATH`, `EXTRACTION_BASE_MODEL`, `EXTRACTION_CONSTRAINED`, `EXTRACTION_DEVICE` (cuda / cpu / auto).

---

## 17. Harmony Integration

### 17.1 OpenSearch Index Extension (D-23)

`app/ingestion/indexer.py` mapping additions:

```python
mapping["mappings"]["properties"].update({
    "medications": {
        "type": "nested",
        "properties": {
            "mention":      {"type": "keyword"},
            "dosage":       {"type": "keyword"},
            "evidence":     {"type": "text"},
            "start_char":   {"type": "integer"},
            "end_char":     {"type": "integer"},
        },
    },
    "adverse_events": {
        "type": "nested",
        "properties": {
            "mention":            {"type": "keyword"},
            "linked_medication":  {"type": "keyword"},
            "evidence":           {"type": "text"},
            "start_char":         {"type": "integer"},
            "end_char":           {"type": "integer"},
        },
    },
    "relation_status":          {"type": "keyword"},
    "relations": {
        "type": "nested",
        "properties": {
            "drug":          {"type": "keyword"},
            "adverse_event": {"type": "keyword"},
            "status":        {"type": "keyword"},   # "related" | "not_related"
            "evidence":      {"type": "text"},
        },
    },
    "extraction_model_version": {"type": "keyword"},
})
```

Nested mappings let us query "medication.mention = metformin AND adverse_event.mention = nausea on the same chunk" — without nested, OpenSearch would match across different chunks.

### 17.2 Ingestion Flow Change (D-23)

`app/api/documents.py` — insert the extraction step between PHI tagging and embedding:

```python
# Existing flow (lines ~150–200 today):
# chunker → phi_tagger → embedder → indexer

# New flow:
chunks = chunker.chunk(text)
chunks = phi_tagger.tag(chunks)          # PHI masked first
chunks = extractor.enrich(chunks)        # NEW — adds medications[], adverse_events[]
chunks = embedder.embed(chunks)
indexer.index_chunks(chunks)
```

**Why extraction after PHI tagging?** The extractor sees masked text — it cannot leak PHI it never saw.

**Why before embedding?** Parallelizable in the future. Logically independent.

### 17.3 Query-Time Structured Filters (D-24)

A lightweight regex layer in `app/search/retriever.py` detects patterns in queries:

- `"patients on <DRUG>"` → adds OpenSearch nested filter on `medications.mention=<DRUG>`.
- `"<DRUG> with <SIDE_EFFECT>"` → adds nested filter on `adverse_events.linked_medication=<DRUG> AND adverse_events.mention=<SIDE_EFFECT>`.

No LLM call at query time. Latency unchanged. This replaces bonus P4's full LLM query rewriter.

### 17.4 Search Result Explanation (D-26)

The search response includes evidence spans from the matched chunks:

```json
{
  "doc_id": "...",
  "score": 0.87,
  "matched_evidence": [
    {"type": "medication", "mention": "metformin", "evidence": "started on metformin 500 mg"}
  ]
}
```

Frontend renders evidence spans as highlighted tooltips on each result.

### 17.5 Reviewer Workflow (D-25)

A new Streamlit page (`demo/reviewer.py`) displays for each retrieved document:

- The raw chunk text.
- A structured table of medications (with dosage and evidence).
- A structured table of adverse events (with linked medication and evidence).
- The validation flags (so reviewers can see which extractions are flagged as low-confidence).

No new model call — purely reads OpenSearch fields.

---

## 18. HIPAA / Security Plan (D-27)

### 18.1 What We Claim

- "HIPAA-aware design suitable for controlled deployment."
- Not "HIPAA compliant" — that requires BAAs, formal risk assessment, and third-party audit, all explicitly out of scope per PS §9.

### 18.2 What We Do

| Concern | Mitigation |
|---|---|
| PHI in training data | Training data is PubMed-derived `ade_corpus_v2`. No patient identifiers. |
| PHI in training environment | Kaggle never receives real patient data. Only `ade_corpus_v2`. |
| External API calls at inference | None. Local inference only. No OpenAI / Anthropic / etc. |
| PHI in extracted JSON | Extraction runs *after* `PhiTagger` masking. Model sees masked text. Layer 5 of the guardrail pipeline re-runs Presidio on the JSON output as defense in depth. |
| Adapter weights leaking PHI | Adapter is trained on `ade_corpus_v2` only — there is no PHI in the training data to memorize. |
| ACL bypass | Extraction inherits Harmony's per-document ACL via the `acl` field. The new `medications[]` / `adverse_events[]` fields are written to the same OpenSearch document; ACL filters apply automatically. |
| Audit | Every extraction logged to Postgres audit table with `extraction_id`, `model_version`, validation flags, latency. Inherits Harmony's append-only audit pattern. |
| Encryption at rest | OpenSearch index sits on encrypted local volume (Harmony's existing setup). Source PDFs in S3 (SSE-KMS). |
| Encryption in transit | Local-only inference — no network for extraction. HTTPS for API. |

### 18.3 What We Explicitly Don't Do

- No BAA-required cloud APIs.
- No automatic PHI re-identification.
- No clinical decision-making — extraction is for search/filter only.
- No fine-tuning on MIMIC or other PhysioNet-credentialed data (PhysioNet TOS forbids upload to Kaggle).

---

## 19. Model Artifact Plan (D-28)

### 19.1 Repository Layout

```
Project-1-AI/
├── models/
│   ├── qwen2.5-7b/                           ← 15 GB, downloaded once
│   │   ├── config.json
│   │   ├── tokenizer.json
│   │   └── model-*.safetensors
│   ├── adapters/
│   │   ├── lora_v1/                          ← ~150-300 MB
│   │   │   ├── adapter_config.json
│   │   │   ├── adapter_model.safetensors
│   │   │   ├── tokenizer_config.json
│   │   │   ├── training_args.json
│   │   │   ├── wandb_run_url.txt
│   │   │   └── eval_metrics.json
│   │   └── qlora_v1/
│   │       └── ...
│   └── README.md                              ← download/load instructions
```

### 19.2 Storage Strategy

- **Base model (15 GB):** downloaded once via `huggingface-cli download Qwen/Qwen2.5-7B-Instruct --local-dir models/qwen2.5-7b/`. Listed in `.gitignore`.
- **Adapters (~150-300 MB each):** committed to git via Git LFS, OR pushed to a private HF Hub repo (`keertanaks/harmony-ade-extractor-lora-v1`) and downloaded at deploy time.
- **Decision:** start with HF Hub upload (cleaner, no LFS quota concerns), fall back to LFS commit only if Hub upload is blocked.

### 19.3 Loading Code

```python
# app/ingestion/extractor.py
class Extractor:
    _model = None
    _tokenizer = None

    @classmethod
    def get(cls):
        if cls._model is None:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            from peft import PeftModel

            base_path    = os.getenv("EXTRACTION_BASE_MODEL", "models/qwen2.5-7b")
            adapter_path = os.getenv("EXTRACTION_ADAPTER_PATH", "models/adapters/qlora_v1")
            device       = os.getenv("EXTRACTION_DEVICE", "auto")

            base = AutoModelForCausalLM.from_pretrained(
                base_path,
                torch_dtype=torch.bfloat16,
                device_map=device,
            )
            cls._model = PeftModel.from_pretrained(base, adapter_path)
            cls._tokenizer = AutoTokenizer.from_pretrained(base_path)
        return cls._model, cls._tokenizer
```

### 19.4 Versioning

Each adapter directory contains:
- `extraction_model_version` (e.g. `"lora_v1_2026-06-12"`) — written into every OpenSearch document at ingestion.
- This lets us re-ingest documents with a newer adapter and identify which extractions came from which model version.

---

## 20. Cost / Environment Comparison Plan

### 20.1 Training Cost Comparison

| Setup | Hardware | Peak VRAM | Time per Epoch (estimate) | GPU-hours (3 epochs + sweep) | Monetary Cost |
|---|---|---|---|---|---|
| Full FT | A100 80 GB (hypothetical) | ~75 GB | ~20 min | ~5 GPU-hr | ~$15 (cloud) |
| LoRA-FP16 | T4×2 (Kaggle) | ~24 GB | ~25 min | ~3.5 GPU-hr | $0 |
| QLoRA-4bit | T4×2 (Kaggle) | ~9 GB | ~12 min | ~1.5 GPU-hr | $0 |

### 20.2 Inference Cost Comparison

| Setup | VRAM | Latency (per chunk, T4) | Throughput (chunks/min) | Deployable On |
|---|---|---|---|---|
| LoRA merged into FP16 base | ~15 GB | ~1.5 s | ~40 | RTX 3090, A10 |
| LoRA adapter on FP16 base | ~15.5 GB | ~1.6 s | ~38 | RTX 3090, A10 |
| QLoRA adapter on 4-bit base | ~5 GB | ~2.0 s | ~30 | RTX 4060, T4, laptop GPUs |
| QLoRA + GPTQ post-quant | ~4 GB | ~1.8 s | ~33 | Most consumer GPUs |
| CPU only | 0 GB (RAM ~16 GB) | ~8 s | ~7 | Any modern laptop |

### 20.3 What Goes in the Cost Report

- All numbers in the tables above (filled in with real measurements, not estimates).
- W&B system-metrics screenshots for peak VRAM and GPU-hours per run.
- Kaggle session screenshots (or W&B compute logs) for total GPU-hour usage.
- A recommendation: **default deployment = QLoRA adapter on 4-bit base**, because (a) it fits the widest hardware range, (b) latency is acceptable for ingestion-time use, (c) F1 expected within 1–3% of LoRA.

---

## 21. Bonus Items Plan

| Bonus | Decision | Effort | Why / How |
|---|---|---|---|
| **P1 FFT comparison** | ❌ Skip | — | Infeasible on T4×2. Documented as architectural finding in the Fine-Tuning Method Report. |
| **P2 Constrained decoding** | ✅ Build | 0.5 day | `lm-format-enforcer` + JSON-schema parser. Before/after EVAL-02 and EVAL-03. Big win. |
| **P3 Active learning loop** | ❌ Skip | — | Scope too large for v1. Recorded as future work. |
| **P4 Query rewriting (full LLM)** | ⚠️ Replaced | 0.25 day | Lightweight regex/keyword layer in `retriever.py` reads ingestion-time fields. No LLM call. |
| **P5 OpenSearch enrichment + before/after** | ✅ Build | 1 day | Extend `indexer.py` (already designed). Run Harmony's existing `evaluation/golden_set.jsonl` queries before and after enrichment, report retrieval metric delta. |
| **P6 Schema ablation** | ⚠️ Optional | 0.5 day | If time permits: train one extra run with strict-enum-only schema (no free-text mention) and compare F1. |
| **P7 Error analysis dashboard** | ✅ Build | 0.5 day | Streamlit page reading `evaluation/reports/error_analysis.json`. Tabs: hallucinated entities, missing evidence, span errors, enum violations. |

---

## 22. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Kaggle session timeout mid-training | High | Medium | Checkpoint every 100 steps, `resume_from_checkpoint=True`, save full sweep state to W&B. |
| OOM during LoRA-FP16 on T4×2 | Medium | Medium | Pre-flight check at notebook start: load model, dry-run forward+backward at batch=4. If OOM, drop to batch=2 + grad_accum=8. |
| F1 doesn't hit ≥0.75 drug F1 target | Medium | Low | Honest negative result is still a deliverable. Report actual numbers and discuss what would fix it (more data, different base model, longer training). |
| QLoRA significantly worse than LoRA | Low | Low | That *is* the finding — write it up. The whole point of the comparison is to measure this. |
| `ade_corpus_v2` style mismatch hurts OOD performance | Medium | Medium | Synthetic OOD set surfaces this. If OOD F1 < 0.5, document the limitation honestly and recommend domain adaptation for v2. |
| HF download blocked on Kaggle | Low | High | Mirror model weights to a HF Hub private repo before training; fall back to that if direct download fails. |
| Adapter file too large for git LFS | Medium | Low | Push to HF Hub instead (private). |
| Pydantic v1 vs v2 conflict with Harmony deps | Low | Medium | Pin to v2 in `requirements.txt`; verify Harmony's existing schemas migrate cleanly. |
| Lead changes dataset mid-project | Low | High | Locked decision in writing (Kirti's confirmation, recorded in §6 D-07). Switching is a v2 task. |
| Bonus items eat into core deliverables | High | Medium | Strict bonus ordering: P2 first (highest ROI), then P5, then P7. Skip the rest if behind schedule. |

---

## 23. Glossary

| Term | Meaning |
|---|---|
| **SFT** | Supervised Fine-Tuning — training a base LLM on input-output pairs. |
| **PEFT** | Parameter-Efficient Fine-Tuning — the HuggingFace library that implements LoRA/QLoRA. |
| **LoRA** | Low-Rank Adaptation — instead of updating all model weights, train small low-rank matrices that augment the frozen base. |
| **QLoRA** | LoRA + 4-bit base model quantization. Lower memory, slightly lower precision. |
| **NF4** | 4-bit NormalFloat — the quantization format used in QLoRA. |
| **TRL** | HuggingFace's Transformer Reinforcement Learning library; includes `SFTTrainer`. |
| **`SFTTrainer`** | The wrapper around HF Trainer that handles chat-format SFT with loss masking. |
| **`DataCollatorForCompletionOnlyLM`** | TRL collator that masks user-turn tokens so loss is computed only on the assistant turn. |
| **Adapter** | The set of trained LoRA weights (~150–300 MB). Loaded on top of the frozen base model at inference. |
| **Gold labels** | Human-annotated labels (what `ade_corpus_v2` provides). |
| **Silver labels** | LLM-generated labels (not human-verified). Not used in this project. |
| **EVAL-XX** | A specific evaluation rule from the PS §12. |
| **Schema v1** | The extraction schema defined in §10. Bumped if fields are added/changed. |

---

## 24. References

- 2018 n2c2 Track 2 ADE and Medication Extraction shared task. (Considered as alternative dataset, not used due to DUA timeline.)
- Belousov et al., *GNTeam at 2018 n2c2: Feature-augmented BiLSTM-CRF for drug-related entity recognition*. https://arxiv.org/abs/1909.10390
- Mahendran and McInnes, *Extracting Adverse Drug Events from Clinical Notes*. https://arxiv.org/abs/2104.10791
- Hu et al., *LoRA: Low-Rank Adaptation of Large Language Models* (2021). https://arxiv.org/abs/2106.09685
- Dettmers et al., *QLoRA: Efficient Finetuning of Quantized LLMs* (2023). https://arxiv.org/abs/2305.14314
- HuggingFace PEFT documentation. https://huggingface.co/docs/peft
- HuggingFace TRL `SFTTrainer` documentation. https://huggingface.co/docs/trl/sft_trainer
- Qwen2.5 Technical Report. https://qwenlm.github.io/blog/qwen2.5/
- `ade-benchmark-corpus/ade_corpus_v2` on HuggingFace. https://huggingface.co/datasets/ade-benchmark-corpus/ade_corpus_v2
- Pydantic v2 documentation. https://docs.pydantic.dev/latest/
- `lm-format-enforcer` (for constrained decoding). https://github.com/noamgat/lm-format-enforcer
- Harmony (Project 1) Design Document. `docs/Design Document.md`.

---

## 25. Open Questions (To Be Resolved During Implementation)

1. Confirm `ade_corpus_v2` p95 sentence length during EDA — if >256 tokens, raise `max_seq_length` to 512 and re-check memory.
2. Confirm whether HF Hub private repo upload works from Kaggle, otherwise plan for git LFS.
3. Confirm Harmony's current Pydantic version (v1 or v2). If v1, plan a separate sub-PR to migrate the existing schemas before adding the extraction schema. *(Pre-flight check: `pip show pydantic` in venv.)*
4. Final adapter format: PeftModel adapter only, or pre-merged with base into a single FP16/4-bit set? Default: keep adapter separate (smaller, swappable). Merged variants only built if inference latency requires it.
5. Reviewer-workflow UI: Streamlit page or extension of the existing React frontend? Default: Streamlit for v1 (faster), migrate to React later if Harmony graduates.
6. `relation_status` vs `relations[]`: v1 uses a single top-level `relation_status` because `ade_corpus_v2` has one drug-ADE pair per row. For v2 (multi-entity clinical notes), replace with `relations: [{drug, adverse_event, status, evidence}]` to handle sentences with multiple independent drug-ADE pairs.

---

