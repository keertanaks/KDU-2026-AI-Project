# Harmony — Project Guide for Claude

This file is read automatically at the start of every Claude Code session.
Do not delete it. Update it when decisions change.

---

## Project Status

| Project | Status | Branch |
|---|---|---|
| **Project 1 — Harmony Healthcare RAG** | ✅ Complete | `main` (merged via PR #22) |
| **Project 3 — Clinical Structuring Fine-Tuning** | 🚧 In Progress | `feature/p3-fine-tuning` (umbrella) |

**Full design doc for Project 3:** `docs/Project3_Design_Document.md` — read this fully before writing any Project 3 code.
**Implementation plan with copy-paste prompts:** `docs/Project3_Implementation_Plan.md`
**Memory files:** `.claude/projects/.../memory/project3_fine_tuning.md`

---

## CRITICAL RULES — Never Violate These

### 1. Extraction order (D-35)
**Extraction MUST run on original text BEFORE PHI masking.**
PHI masking shifts character offsets. If you run extraction after masking, all `source_span`
values will be wrong relative to the original document.
Drug names and ADE mentions are clinical findings, not PHI — safe to process on unmasked text.
After extraction, run Presidio on the output fields (`mention`, `evidence`) to strip any leaked PHI.

### 2. No real patient data
Never use real patient notes, MIMIC, PhysioNet, or any DUA-restricted dataset in training or tests.
Training uses only `ade-benchmark-corpus/ade_corpus_v2` (public, no DUA).
Synthetic eval examples must be completely fictional.

### 3. No external API calls in the inference path
No OpenAI, Anthropic, or any hosted LLM API may be called at inference time.
All model inference is local only. The fine-tuned Qwen2.5-7B adapter runs on local GPU/CPU.

### 4. Never load the real 7B model in unit tests
Unit tests must mock both `model` and `tokenizer` entirely.
Tests must pass with no GPU and no downloaded model weights.
Use `unittest.mock.patch` or `pytest monkeypatch`.

### 5. Do not modify existing Project 1 files unless a phase prompt explicitly says to
Existing Harmony files (`indexer.py`, `documents.py`, etc.) are modified only in Phase 6.
All other phases add new files only.

### 6. Pydantic v2 only
The codebase uses Pydantic v2 everywhere. Never import from `pydantic.v1`.
Use `model_validate()` not `parse_obj()`. Use `model_dump()` not `dict()`.

---

## File Name Disambiguation — Read This Before Phase 2 or 6

There are two validators with similar names. They are completely different:

| File | Project | What it does |
|---|---|---|
| `app/ingestion/extraction_validator.py` | **Project 1 — DO NOT TOUCH** | Scores OCR/PDF text quality. Checks for truncated medication names, flattened table headers, etc. Has its own tests in `tests/test_extraction_validator.py`. |
| `app/ingestion/validator.py` | **Project 3 — Phase 2 creates this** | JSON repair + Pydantic validation wrapper for the fine-tuned model's output. Different file, different purpose. |

---

## Project 3 — Architecture in One Paragraph

Fine-tune Qwen2.5-7B-Instruct on `ade_corpus_v2` to extract structured drug/ADE/dosage JSON
from clinical text. Two notebooks: LoRA (FP16, Kaggle Account 1) and QLoRA (4-bit NF4,
Kaggle Account 2). Trained adapters are stored in `models/adapters/`. At ingestion time,
`app/ingestion/extractor.py` (Phase 6) calls the adapter before PHI masking and writes
`medications[]`, `adverse_events[]`, `relations[]`, `extraction_model_version` to OpenSearch.
No model call at query time — structured fields are read from the index.

---

## Branch Strategy

```
main
  └── feature/p3-fine-tuning          ← umbrella branch, never work here directly
        ├── feature/p3-data-prep       ← Phase 1
        ├── feature/p3-schema          ← Phase 2
        ├── feature/p3-lora-training   ← Phase 3
        ├── feature/p3-qlora-training  ← Phase 4
        ├── feature/p3-evaluation      ← Phase 5
        ├── feature/p3-harmony-integration ← Phase 6
        └── feature/p3-demo            ← Phase 7
```

Each sub-branch PRs into `feature/p3-fine-tuning`, not into `main`.
Final PR: `feature/p3-fine-tuning → main` (after all 7 phases merged).

---

## Key Locked Decisions (Summary)

| Decision | Value |
|---|---|
| Dataset | `ade-benchmark-corpus/ade_corpus_v2` (all 3 configs) |
| Base model | `Qwen/Qwen2.5-7B-Instruct` (Apache 2.0) |
| Fine-tuning | LoRA (FP16) on Account 1 + QLoRA (4-bit NF4) on Account 2 |
| Split | 80/10/10 grouped by `md5(text)` hash — NOT row-level (prevents leakage) |
| No blind dedup | Keep all rows. Use text_hash only for split grouping. |
| Target JSON | Model generates: `schema_version`, `entities[]`, `relation_status` only |
| System-injected | `record_id`, `validation`, `error_reason` are added by wrapper — NOT by model |
| Validator injection | Must inject BOTH `record_id` AND `validation` block before `model_validate()` |
| relations[] | Built from `ae.linked_medication`, NOT cartesian product of medications × ADEs |
| Optimizer | LoRA → `adamw_torch`. QLoRA → `paged_adamw_8bit`. Never swap. |
| Compute dtype | `float16` everywhere — T4 is Turing arch (cc 7.5), NO native BF16 hardware |
| Max seq len | 256 tokens (ade_corpus_v2 p95 ≈ 80 tokens) |
| Effective batch | micro=4, grad_accum=4 → effective 16 |
| Inference | Greedy: `do_sample=False`, `temperature=0.0`, `repetition_penalty=1.05` |
| Experiment tracking | W&B (not MLflow, not LangSmith — LangSmith is for Harmony inference tracing) |
| HIPAA posture | "HIPAA-aware design" — NOT "HIPAA compliant" (no formal certification) |
| Integration | Ingestion-time only. Zero model calls at query time. |

---

## Data Paths (Project 3)

```
data/
  processed/
    train.jsonl       ← 80% split, chat-format
    val.jsonl         ← 10% split, chat-format
    test.jsonl        ← 10% split — touch only once for final eval
    dataset_stats.json

models/
  qwen2.5-7b/         ← base model, 15 GB, gitignored
  adapters/
    lora_v1/          ← adapter_config.json, adapter_model.safetensors, training_args.json
    qlora_v1/         ← same structure

notebooks/
  p3_01_data_prep.ipynb
  p3_02_lora_train.ipynb
  p3_03_qlora_train.ipynb

evaluation/
  harness/
    eval_runner.py
    metrics.py
  synthetic_ade_eval.jsonl   ← 60 fictional OOD examples, never in training
  reports/

docs/
  reports/
    01_dataset_selection_report.md
    02_schema_design_document.md
    03_enums_vs_freeform_decision.md
    04_data_format_specification.md
    05_model_selection_report.md
    06_finetuning_method_report.md
    07_hyperparameter_report.md
    08_training_pipeline.md
    09_evaluation_harness.md
    10_validation_engine.md
    11_model_usage_strategy.md
    12_cost_environment_report.md
    13_final_report.md

demo/
  reviewer.py
  before_after.py
  error_dashboard.py
```

---

## ExtractionResult Schema (Phase 2 — app/schemas/extraction.py)

```python
# Model generates ONLY these three fields:
{
  "schema_version": "v1",
  "entities": [...],
  "relation_status": "related" | "not_related" | "none"
}

# Wrapper injects the rest before model_validate():
{
  "record_id": "<chunk_id>",                # system-injected
  "validation": {                            # system-injected, updated by validator
    "json_valid": True,
    "schema_valid": True,
    "enum_valid": True,
    "evidence_present": True
  },
  "error_reason": None                       # set by build_empty_result() on failure
}
```

Entity fields: `entity_type` (enum: medication/adverse_event), `mention` (str),
`dosage` (Optional[str]), `linked_medication` (Optional[str]), `evidence` (str),
`source_span` {`start_char`: int, `end_char`: int}

---

## How to Run Tests

```bash
# All tests (fast suite, no model loading)
pytest tests/ -v

# Specific test file
pytest tests/test_extraction_schema.py -v

# Skip slow tests (Presidio model loading)
pytest tests/ -v -m "not slow"

# Project 1 tests only (sanity check existing system)
pytest tests/test_ingestion.py tests/test_search.py tests/test_auth.py -v
```

---

## Tech Stack

| Component | Library / Version |
|---|---|
| API framework | FastAPI |
| Schema validation | **Pydantic v2** |
| Training | HuggingFace `transformers`, `peft`, `trl` (SFTTrainer) |
| Quantization | `bitsandbytes` (4-bit NF4 for QLoRA only) |
| JSON repair | `json-repair` |
| Experiment tracking | Weights & Biases (`wandb`) |
| Vector search | OpenSearch (nmslib HNSW, 1536-d embeddings) |
| PHI detection | Presidio (`presidio-analyzer`, `presidio-anonymizer`) |
| Inference tracing | LangSmith (Project 1 only — NOT used for training) |
| Test runner | `pytest` with `asyncio_mode = auto` |
| Python | 3.11 |

---

## Evaluation Targets (must be reported for baseline + LoRA + QLoRA)

| Metric | Target |
|---|---|
| JSON validity (pre-repair) | ≥ 95% |
| JSON validity (post-repair) | ≥ 99.5% |
| Schema validity | ≥ 90% |
| Span F1 strict | ≥ 0.65 |
| Span F1 lenient (IoU ≥ 0.5) | ≥ 0.75 |
| Drug F1 | ≥ 0.75 |
| ADE F1 | ≥ 0.65 |
| Dosage F1 | ≥ 0.40 (best-effort, ~224 training examples only) |
| Relation F1 | ≥ 0.70 |
| Enum accuracy | ≥ 98% |
| Evidence substring accuracy | ≥ 90% |
| Hallucination rate | ≤ 5% |
