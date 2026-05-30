# Project 3: Complete Implementation Plan

## Overview

7 phases, 7 branches, all PRing into `feature/p3-fine-tuning` umbrella branch, which PRs to `main` at the end.

```
main
  └── feature/p3-fine-tuning
        ├── Phase 1: feature/p3-data-prep
        ├── Phase 2: feature/p3-schema
        ├── Phase 3: feature/p3-lora-training
        ├── Phase 4: feature/p3-qlora-training
        ├── Phase 5: feature/p3-evaluation
        ├── Phase 6: feature/p3-harmony-integration
        └── Phase 7: feature/p3-final
```

**Dependency order:**
```
Phase 1 (data prep)
    │
    ├──► Phase 2 (schema) — can run in parallel with Phase 1
    │
    └──► Phase 3 + Phase 4 (training) — need Phase 1 JSONL files
              │
              └──► Phase 5 (evaluation) — needs trained adapters
                        │
                        └──► Phase 6 (integration) — needs schema + adapters
                                  │
                                  └──► Phase 7 (demo) — needs integration
```

---

## Phase 1: Data Preparation

**Branch:** `feature/p3-data-prep`
**PRs into:** `feature/p3-fine-tuning`
**Depends on:** Nothing (start here)

**What this phase produces:**
```
notebooks/
  p3_01_data_prep.ipynb          ← Kaggle-ready notebook
data/
  processed/
    train.jsonl                  ← 80% split, chat-format
    val.jsonl                    ← 10% split, chat-format
    test.jsonl                   ← 10% split, chat-format (touch only once)
    dataset_stats.json           ← EDA output: lengths, class balance, field coverage
docs/
  reports/
    01_dataset_selection_report.md  ← PS deliverable
```

**What the notebook does:**
1. Downloads all 3 configs of ade_corpus_v2
2. EDA: text length distribution, class balance, field coverage
3. Computes text_hash per row; groups by text_hash for split (does NOT blindly deduplicate)
4. Splits 80/10/10 stratified by text_hash group
5. Converts each row to chat-format JSON with correct target JSON
6. Saves to data/processed/

---

### PHASE 1 PROMPT (copy-paste this to start a new session):

```
Read memory first, then do the following.

Project context: We are building Project 3 (Harmony Clinical Structuring Fine-Tuning System).
Design doc is at docs/Project3_Design_Document.md — read it fully before writing any code.

Task: Create the data preparation notebook for Project 3.

Create the branch:
git checkout feature/p3-fine-tuning
git checkout -b feature/p3-data-prep

Create the following files:

1. notebooks/p3_01_data_prep.ipynb
This is a Kaggle notebook. It must:
- Install: datasets, pandas, scikit-learn, hashlib (stdlib)
- Download ade_corpus_v2 all 3 configs: Ade_corpus_v2_classification, Ade_corpus_v2_drug_ade_relation, Ade_corpus_v2_drug_dosage_relation
- Run EDA: print text length distribution (mean, p50, p95, max), class balance per config, field coverage (how many rows have dosage vs not), duplicate text count
- Save dataset_stats.json with these numbers
- Combine all 3 configs into a unified dataframe. Each row gets a text_hash = hashlib.md5(text.encode()).hexdigest()
- IMPORTANT — do NOT blindly deduplicate rows:
  ade_corpus_v2 has one row per drug-ADE pair; the same sentence appears in multiple rows if it
  contains multiple pairs. Use text_hash ONLY to prevent train/val/test leakage:
  all rows sharing the same text_hash must land in the same split.
  Do not drop duplicate rows. Preserve all gold relation rows exactly as-is.
  (If a safe merge function is desired later, that is a v2 data-prep task.)
- Split 80/10/10 grouped by text_hash (not row-level) stratified by relation_label (related/not_related/none). Use sklearn GroupShuffleSplit. seed=42.
- Convert each split to chat format JSONL. The chat format is:
  [
    {"role": "user", "content": "<INSTRUCTION>\n\nClinical text:\n<TEXT>"},
    {"role": "assistant", "content": "<MODEL_JSON_OUTPUT>"}
  ]
  The INSTRUCTION is the exact template from docs/Project3_Design_Document.md §11.2.
  The MODEL_JSON_OUTPUT is the target JSON the model should produce — it includes schema_version, entities[], relation_status. It does NOT include record_id or validation block (those are system-injected).
- Save train.jsonl, val.jsonl, test.jsonl to /kaggle/working/data/processed/ (or data/processed/ locally)
- Print final counts: train/val/test sizes, positive/negative ratio per split

2. data/processed/dataset_stats.json (placeholder — filled when notebook is run)

3. docs/reports/01_dataset_selection_report.md
Write the Dataset Selection Report deliverable (PS §11).
Use the decisions from the design doc. Include:
- Dataset chosen and why (no DUA, 3 configs, gold labels)
- What each config provides
- Known limitations (dosage best-effort ~280 examples, PubMed style not clinical note style)
- Split strategy and why text-hash grouping (leakage prevention)
- Train/val/test sizes
- Fallback plan if dataset access blocked

After creating files, commit and push feature/p3-data-prep.
Create PR: feature/p3-data-prep → feature/p3-fine-tuning
```

---

## Phase 2: Schema and Validation Engine

**Branch:** `feature/p3-schema`
**PRs into:** `feature/p3-fine-tuning`
**Depends on:** Can run in parallel with Phase 1

**What this phase produces:**
```
app/schemas/
  extraction.py                  ← Pydantic v2 ExtractionResult model
app/ingestion/
  validator.py                   ← validation + JSON repair wrapper
tests/
  test_extraction_schema.py      ← unit tests for schema + validator
docs/
  reports/
    02_schema_design_document.md    ← PS deliverable
    03_enums_vs_freeform_decision.md ← PS deliverable
```

---

### PHASE 2 PROMPT:

```
Read memory first, then do the following.

Project context: We are building Project 3 (Harmony Clinical Structuring Fine-Tuning System).
Design doc is at docs/Project3_Design_Document.md — read it fully before writing any code.

Task: Create the Pydantic v2 extraction schema and validation engine for Project 3.

Create the branch:
git checkout feature/p3-fine-tuning
git checkout -b feature/p3-schema

Create the following files:

1. app/schemas/extraction.py
Pydantic v2 schema. Must define:
- SourceSpan(BaseModel): start_char: int (ge=0), end_char: int (ge=0)
- Entity(BaseModel): entity_type: Literal["medication","adverse_event"], mention: str (min_length=1), dosage: Optional[str]=None, linked_medication: Optional[str]=None, evidence: str (min_length=1), source_span: SourceSpan
- ValidationFlags(BaseModel): json_valid: bool, schema_valid: bool, enum_valid: bool, evidence_present: bool
- ExtractionResult(BaseModel): record_id: str, schema_version: Literal["v1"], entities: list[Entity], relation_status: Literal["related","not_related","none"], validation: ValidationFlags, error_reason: Optional[str] = None
- model_validator on ExtractionResult: check end_char > start_char for all entities
- Note: record_id, validation, and error_reason are NOT in the model's target JSON — they are system-injected. The Pydantic model represents the full system output after injection.
- error_reason is None on success; populated by build_empty_result() to explain why extraction was skipped/failed.

2. app/ingestion/validator.py
Validation + JSON repair wrapper. Must implement:
- build_empty_result(record_id, reason) → ExtractionResult with all validation flags False and error_reason=reason
- validate_extraction(raw_text: str, record_id: str, input_text: str) → ExtractionResult
  Steps:
  1. Try json.loads(raw_text)
  2. On JSONDecodeError: try json_repair.loads(raw_text). If still fails → return build_empty_result(reason="json_parse_failed")
  3. Inject system fields into parsed dict — BOTH of these, not just record_id:
     parsed["record_id"] = record_id
     parsed["validation"] = {"json_valid": True, "schema_valid": True, "enum_valid": True, "evidence_present": True}
     (validation flags are updated below after further checks)
  4. Try ExtractionResult.model_validate(parsed)
  5. On ValidationError → return build_empty_result(reason="schema_invalid")
  6. For each entity: check if entity.evidence is substring of input_text. If not, set validation.evidence_present=False (don't reject, just flag)
  7. For each entity: check if entity.mention is substring of input_text. If not, flag as potential hallucination (add to a hallucination_warnings list, log it)
  8. Set validation.json_valid=True, schema_valid=True, enum_valid=True
  9. Return the ExtractionResult
- Add install requirement: json_repair (pip install json-repair)

3. tests/test_extraction_schema.py
Unit tests covering:
- Valid entity passes Pydantic validation
- Invalid entity_type raises ValidationError
- Invalid span (end <= start) raises ValidationError
- validate_extraction on valid JSON returns schema_valid=True
- validate_extraction on broken JSON (missing bracket) returns json_valid=False
- validate_extraction on wrong enum returns schema_valid=False
- validate_extraction where evidence is NOT a substring of input sets evidence_present=False
- validate_extraction where mention is NOT in input logs hallucination warning

4. docs/reports/02_schema_design_document.md
Schema Design Document deliverable (PS §11). Include:
- Full field specification table (from design doc §10.2)
- Why hybrid schema (design doc §10.3)
- Why not the full PS schema (design doc §10.4)
- Example input → model output → system output
- Schema version v1

5. docs/reports/03_enums_vs_freeform_decision.md
Enums vs Free-Form Decision Record deliverable (PS §11). Include:
- Three options considered (strict enums, LLM-decided, hybrid)
- Why hybrid was chosen
- Which fields are enums and why
- Which fields are free-text and why

After creating files, run: python -m pytest tests/test_extraction_schema.py -v
All tests must pass. Fix any failures before committing.

Commit and push feature/p3-schema.
Create PR: feature/p3-schema → feature/p3-fine-tuning
```

---

## Phase 3: LoRA Training Notebook

**Branch:** `feature/p3-lora-training`
**PRs into:** `feature/p3-fine-tuning`
**Depends on:** Phase 1 (needs train.jsonl/val.jsonl format confirmed)
**Runs on:** Kaggle Account 1 (Team Member 1), T4×2

**What this phase produces:**
```
notebooks/
  p3_02_lora_train.ipynb         ← Kaggle notebook, 7 runs (LR sweep + rank sweep + final)
models/
  adapters/
    lora_v1/
      adapter_config.json
      adapter_model.safetensors
      tokenizer_config.json
      training_args.json          ← includes wandb_run_url, base_model_revision
      eval_metrics.json           ← val F1 per run
docs/
  reports/
    05_model_selection_report.md    ← PS deliverable
    06_finetuning_method_report.md  ← PS deliverable (shared with Phase 4)
    07_hyperparameter_report.md     ← PS deliverable (filled after both phases done)
```

---

### PHASE 3 PROMPT:

```
Read memory first, then do the following.

Project context: We are building Project 3 (Harmony Clinical Structuring Fine-Tuning System).
Design doc is at docs/Project3_Design_Document.md — read it fully, especially §12 (Training Design) and §13 (Hyperparameter Strategy) before writing any code.

Task: Create the LoRA training notebook for Project 3. This runs on Kaggle T4×2.

Create the branch:
git checkout feature/p3-fine-tuning
git checkout -b feature/p3-lora-training

Create the following files:

1. notebooks/p3_02_lora_train.ipynb
This is a Kaggle notebook for LoRA fine-tuning. Must be structured as these cells:

CELL 1 — Install:
pip install transformers peft trl bitsandbytes accelerate datasets wandb

CELL 2 — Config (edit this cell before each run):
RUN_NAME = "lora_lr_sweep_1"     # change per run
LEARNING_RATE = 2e-4             # sweep: 1e-4, 2e-4, 5e-4
LORA_RANK = 16                   # sweep: 8, 16, 32
LORA_ALPHA = LORA_RANK * 2
MAX_STEPS = 500                  # short for sweep runs; set -1 for final run (use num_epochs=3)
NUM_EPOCHS = 3                   # only used when MAX_STEPS = -1
WANDB_PROJECT = "harmony-p3-lora"
BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"
BASE_MODEL_REVISION = "FILL_IN"   # paste commit hash from HF Hub before running

CELL 3 — Load data (reads train.jsonl and val.jsonl from Kaggle input dataset)

CELL 4 — Load model in FP16 (NOT 4-bit — that's QLoRA):
model = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL,
    revision=BASE_MODEL_REVISION,
    torch_dtype=torch.float16,
    device_map="auto",
)
tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, revision=BASE_MODEL_REVISION)

CELL 5 — LoRA config:
LoraConfig with r=LORA_RANK, alpha=LORA_ALPHA, target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"], dropout=0.05, bias="none", task_type="CAUSAL_LM"

CELL 6 — Training:
SFTConfig with:
- learning_rate=LEARNING_RATE
- per_device_train_batch_size=4
- gradient_accumulation_steps=4 (effective batch 16)
- max_steps=MAX_STEPS
- num_train_epochs=NUM_EPOCHS (used when max_steps=-1)
- optimizer="adamw_torch"       ← NOT paged_adamw_8bit (that's for QLoRA only)
- lr_scheduler_type="cosine"
- warmup_ratio=0.03
- weight_decay=0.0
- fp16=True                     ← T4 uses FP16, NOT BF16
- bf16=False
- gradient_checkpointing=True
- max_seq_length=256
- evaluation_strategy="steps", eval_steps=100
- save_strategy="steps", save_steps=100, save_total_limit=2
- load_best_model_at_end=True
- metric_for_best_model="eval_loss"
- logging_steps=10
- report_to="wandb"
- output_dir="/kaggle/working/checkpoints"

DataCollatorForCompletionOnlyLM with response_template="<|im_start|>assistant\n"

CELL 7 — Run sweep instructions (markdown cell explaining the 7 runs):
Run 1: LR=1e-4, rank=16, max_steps=500
Run 2: LR=2e-4, rank=16, max_steps=500
Run 3: LR=5e-4, rank=16, max_steps=500
→ Pick best LR (lowest eval_loss)
Run 4: best_LR, rank=8, max_steps=500
Run 5: best_LR, rank=16, max_steps=500
Run 6: best_LR, rank=32, max_steps=500
→ Pick best rank
Run 7: best_LR, best_rank, max_steps=-1, num_epochs=3 (FINAL RUN)

CELL 8 — Save adapter:
model.save_pretrained("/kaggle/working/lora_v1_adapter")
tokenizer.save_pretrained("/kaggle/working/lora_v1_adapter")
Save training_args.json with: run_name, lr, rank, alpha, wandb_run_url, base_model, base_model_revision

CELL 9 — Quick validation (run inference on 3 test sentences, print raw output):
Verify model outputs parseable JSON before downloading.

2. models/adapters/lora_v1/training_args.json (placeholder template)
{
  "method": "LoRA",
  "base_model": "Qwen/Qwen2.5-7B-Instruct",
  "base_model_revision": "FILL_AFTER_TRAINING",
  "final_lr": "FILL_AFTER_SWEEP",
  "final_rank": "FILL_AFTER_SWEEP",
  "final_alpha": "FILL_AFTER_SWEEP",
  "optimizer": "adamw_torch",
  "fp16": true,
  "bf16": false,
  "wandb_run_url": "FILL_AFTER_TRAINING",
  "kaggle_account": "team_member_1"
}

3. docs/reports/05_model_selection_report.md
Model Selection Report deliverable. Include:
- Candidates considered: Qwen2.5-7B-Instruct, Mistral-7B-Instruct-v0.3, Phi-3.5-mini-instruct
- Comparison table: JSON output quality, license, VRAM on T4×2, 2026 benchmark position
- Why Qwen2.5-7B-Instruct was selected (best structured JSON, Apache 2.0, fits hardware)
- Why alternatives were not chosen

4. docs/reports/06_finetuning_method_report.md
Fine-Tuning Method Report deliverable. Include:
- SFT/PEFT/LoRA/QLoRA explained as a stack (not 4 separate methods)
- Memory math table: Full FT vs LoRA-FP16 vs QLoRA-4bit on T4×2
- Why full FT is infeasible (documented as architectural finding)
- Why LoRA-FP16 was chosen for this notebook
- How QLoRA comparison works (Phase 4, same base model)
- Optimizer choice: adamw_torch for LoRA (not paged — designed for QLoRA)
- FP16 not BF16: T4 Turing arch has no native BF16 hardware

Commit and push feature/p3-lora-training.
Create PR: feature/p3-lora-training → feature/p3-fine-tuning
```

---

## Phase 4: QLoRA Training Notebook

**Branch:** `feature/p3-qlora-training`
**PRs into:** `feature/p3-fine-tuning`
**Depends on:** Phase 1 (same JSONL format)
**Runs on:** Kaggle Account 2 (Team Member 2), T4×2

**What this phase produces:**
```
notebooks/
  p3_03_qlora_train.ipynb        ← Kaggle notebook, 7 runs
models/
  adapters/
    qlora_v1/
      adapter_config.json
      adapter_model.safetensors
      tokenizer_config.json
      training_args.json
      eval_metrics.json
```

---

### PHASE 4 PROMPT:

```
Read memory first, then do the following.

Project context: We are building Project 3 (Harmony Clinical Structuring Fine-Tuning System).
Design doc is at docs/Project3_Design_Document.md — read §12 and §13 fully before writing any code.

Task: Create the QLoRA training notebook for Project 3. This runs on Kaggle T4×2.
This is IDENTICAL in structure to notebooks/p3_02_lora_train.ipynb BUT with 4-bit quantization.

Create the branch:
git checkout feature/p3-fine-tuning
git checkout -b feature/p3-qlora-training

Create the following files:

1. notebooks/p3_03_qlora_train.ipynb
Same structure as the LoRA notebook BUT with these differences:

CELL 4 — Load model with 4-bit quantization:
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_use_double_quant=True,
    bnb_4bit_compute_dtype=torch.float16,   ← float16 NOT bfloat16 (T4 has no native BF16)
)
model = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL,
    revision=BASE_MODEL_REVISION,
    quantization_config=bnb_config,
    device_map="auto",
)
model = prepare_model_for_kbit_training(model)   ← required for QLoRA

CELL 6 — Training config differences:
- optimizer="paged_adamw_8bit"   ← QLoRA uses paged optimizer (LoRA used adamw_torch)
- fp16=False                      ← base model is 4-bit, not fp16
- bf16=False
No other differences from LoRA notebook.

CELL 7 — Sweep instructions (same 7-run plan as LoRA, but note QLoRA should be faster ~12 min/epoch vs ~25 min for LoRA)

2. models/adapters/qlora_v1/training_args.json (placeholder template)
{
  "method": "QLoRA",
  "base_model": "Qwen/Qwen2.5-7B-Instruct",
  "base_model_revision": "FILL_AFTER_TRAINING",
  "quantization": "4-bit NF4 with double-quant",
  "compute_dtype": "float16",
  "final_lr": "FILL_AFTER_SWEEP",
  "final_rank": "FILL_AFTER_SWEEP",
  "final_alpha": "FILL_AFTER_SWEEP",
  "optimizer": "paged_adamw_8bit",
  "wandb_run_url": "FILL_AFTER_TRAINING",
  "kaggle_account": "team_member_2"
}

Commit and push feature/p3-qlora-training.
Create PR: feature/p3-qlora-training → feature/p3-fine-tuning
```

---

## Phase 5: Evaluation Harness

**Branch:** `feature/p3-evaluation`
**PRs into:** `feature/p3-fine-tuning`
**Depends on:** Phase 1 (test.jsonl), Phase 2 (extraction.py schema), Phase 3+4 (adapters downloaded)

**What this phase produces:**
```
evaluation/
  harness/
    __init__.py
    eval_runner.py               ← main eval script, runs all 3 configs (baseline, lora, qlora)
    metrics.py                   ← F1, span IoU, enum accuracy, hallucination rate calculations
  synthetic_ade_eval.jsonl       ← 50-100 OOD hand-crafted examples
  reports/
    baseline.json                ← after running
    lora_v1.json                 ← after running
    qlora_v1.json                ← after running
    comparison.md                ← auto-generated comparison table
    error_analysis.json          ← sample failures for error dashboard
tests/
  test_metrics.py                ← unit tests for metric calculations
docs/
  reports/
    04_data_format_specification.md  ← PS deliverable
    07_hyperparameter_report.md      ← filled after sweep results available
    12_cost_environment_report.md    ← PS deliverable
```

---

### PHASE 5 PROMPT:

```
Read memory first, then do the following.

Project context: We are building Project 3 (Harmony Clinical Structuring Fine-Tuning System).
Design doc is at docs/Project3_Design_Document.md — read §14 (Evaluation Plan) fully before writing any code.

Prerequisites: 
- Phase 1 complete (data/processed/test.jsonl exists)
- Phase 2 complete (app/schemas/extraction.py exists)
- Phase 3 adapter downloaded to models/adapters/lora_v1/
- Phase 4 adapter downloaded to models/adapters/qlora_v1/
  NOTE: Run QLoRA first in practice — it uses ~9 GB on T4 vs ~24 GB for LoRA. QLoRA is more
  likely to succeed on the first attempt without OOM. LoRA can run in parallel on the second account.

Task: Create the evaluation harness for Project 3.

Create the branch:
git checkout feature/p3-fine-tuning
git checkout -b feature/p3-evaluation

Create the following files:

1. evaluation/harness/metrics.py
Implement these functions:
- compute_entity_f1(predicted: list[Entity], gold: list[Entity], entity_type: str) → dict with precision, recall, f1
  Match predicted to gold by (entity_type, mention). Case-insensitive mention match.
- compute_span_f1_strict(pred_span, gold_span) → bool (exact start_char + end_char match)
- compute_span_f1_lenient(pred_span, gold_span, text: str) → float (character-level IoU)
- compute_relation_f1(predicted_status: str, gold_status: str) → bool
- compute_hallucination_rate(entities: list[Entity], input_text: str) → float (% mentions not in input)
- compute_evidence_accuracy(entities: list[Entity], input_text: str) → float (% evidence that is substring)
- compute_enum_accuracy(results: list[ExtractionResult]) → float (% valid enum values)

2. evaluation/harness/eval_runner.py
Main eval script. CLI: python eval_runner.py --model [baseline|lora|qlora] --test_file data/processed/test.jsonl --output_dir evaluation/reports/
- Loads model based on --model arg:
  - baseline: Qwen2.5-7B-Instruct base only, no adapter
  - lora: base + models/adapters/lora_v1/
  - qlora: base + models/adapters/qlora_v1/ with 4-bit config
- Runs inference on data/processed/test.jsonl
- Computes all EVAL metrics (EVAL-02 through EVAL-08 from design doc §14.1)
- Also runs on evaluation/synthetic_ade_eval.jsonl (OOD set) — report separately
- Measures P50/P95 latency per chunk
- Saves results to evaluation/reports/{model_name}.json
- After all 3 models run, generates evaluation/reports/comparison.md table
- Generates evaluation/reports/error_analysis.json: 20 sample failures with category (json_invalid, schema_invalid, hallucination, span_error, enum_error)

3. evaluation/synthetic_ade_eval.jsonl
Create 60 hand-crafted clinical-note style examples (NOT PubMed style).
IMPORTANT: All examples must be completely fictional — no real patient names, no real patient notes, no MIMIC or PhysioNet data. Each example must be manually reviewed for clinical plausibility before inclusion. Never copy real notes.
Must include:
- 20 positive drug-ADE examples in clinical abbreviation style (e.g., "Pt c/o N/V x2d, started metformin 500mg BID last wk")
- 15 examples with dosage present
- 10 negative examples (drug mentioned, no ADE)
- 10 negation examples ("no rash noted after amoxicillin")
- 5 multi-drug examples
Each entry: {"id": "syn_001", "text": "...", "gold": {"entities": [...], "relation_status": "..."}}

4. tests/test_metrics.py
Unit tests for metrics.py:
- Test F1 = 1.0 when perfect match
- Test F1 = 0.0 when no match
- Test span IoU calculation
- Test hallucination detection (mention not in text)
- Test evidence substring check

5. docs/reports/04_data_format_specification.md
Data Format Specification deliverable (PS §11). Include:
- Exact chat format used (user turn template, assistant turn JSON)
- The INSTRUCTION template verbatim
- 3 complete example records (one positive, one negative, one dosage-only)
- Why chat format was chosen over raw instruction or token-label format
- How DataCollatorForCompletionOnlyLM masks the user turn

6. docs/reports/12_cost_environment_report.md
Cost/Environment Report deliverable. Include:
- Training cost comparison table (Full FT hypothetical vs LoRA vs QLoRA): VRAM, time/epoch, GPU-hours, cost
- Inference cost comparison table: VRAM, latency/chunk, deployable hardware
- Fill actual numbers from W&B logs after training completes (leave placeholders if not yet available)
- Recommendation: which setup to use in production and why

Run: python -m pytest tests/test_metrics.py -v
All tests must pass before committing.

Commit and push feature/p3-evaluation.
Create PR: feature/p3-evaluation → feature/p3-fine-tuning
```

---

## Phase 6: Harmony Integration

**Branch:** `feature/p3-harmony-integration`
**PRs into:** `feature/p3-fine-tuning`
**Depends on:** Phase 2 (schema), Phase 3 or 4 (at least one adapter)

**What this phase produces:**
```
app/
  ingestion/
    extractor.py                 ← NEW: clinical entity extractor (lazy singleton)
    validator.py                 ← already created in Phase 2
    indexer.py                   ← MODIFIED: new OpenSearch fields
  api/
    documents.py                 ← MODIFIED: extractor wired in (before PHI masking)
  schemas/
    extraction.py                ← already created in Phase 2
tests/
  test_extractor.py              ← unit tests with mocked model
  test_integration_extraction.py ← integration test (CPU inference on small model)
docs/
  reports/
    11_model_usage_strategy.md   ← PS deliverable
```

---

### PHASE 6 PROMPT:

```
Read memory first, then do the following.

Project context: We are building Project 3 (Harmony Clinical Structuring Fine-Tuning System).
Design doc is at docs/Project3_Design_Document.md — read §7 (Architecture), §15 (Validation), §16 (Inference Plan), and §17 (Harmony Integration) fully before writing any code.
Also read the existing files: app/ingestion/indexer.py, app/api/documents.py, app/ingestion/phi_tagger.py, app/schemas/extraction.py

Task: Wire the fine-tuned extractor into Harmony's ingestion pipeline.

Create the branch:
git checkout feature/p3-fine-tuning
git checkout -b feature/p3-harmony-integration

KEY ARCHITECTURAL RULE (from design doc D-35):
Extraction MUST run on original text BEFORE PHI masking.
Reason: PHI masking shifts character offsets — extraction after masking produces wrong source_span values.
Drug/ADE mentions are clinical findings, not PHI — running on unmasked text is safe.
After extraction, run Presidio on the output fields (mention, evidence) as a secondary PHI-strip.

Create/modify the following files:

1. app/ingestion/extractor.py (NEW)
Lazy-loaded singleton following the exact _get_*() pattern in app/api/documents.py.
Implement:
- class ClinicalExtractor with class-level _model, _tokenizer = None
- classmethod get() → loads base model + adapter on first call using env vars:
  EXTRACTION_BASE_MODEL (default: "models/qwen2.5-7b")
  EXTRACTION_ADAPTER_PATH (default: "models/adapters/qlora_v1")
  EXTRACTION_DEVICE (default: "auto")
  EXTRACTION_ENABLED (default: "true") — if "false", skip extraction entirely
- method extract(text: str, record_id: str) → ExtractionResult
  1. Build chat prompt using tokenizer.apply_chat_template with the EXACT instruction template from docs/Project3_Design_Document.md §11.2
  2. Generate: do_sample=False, temperature=0.0, max_new_tokens=512, repetition_penalty=1.05
  3. Decode output, strip the prompt portion
  4. Call validate_extraction(raw_output, record_id, text) from app/ingestion/validator.py
  5. Return ExtractionResult
- If EXTRACTION_ENABLED=false → return build_empty_result(record_id, reason="extraction_disabled")
- If any exception (OOM, CUDA error) → log error, return build_empty_result(reason="extraction_error"). Never crash the ingestion pipeline.

2. app/ingestion/indexer.py (MODIFY)
In ensure_index(), add these new fields to the mapping properties dict:
"medications": {
    "type": "nested",
    "properties": {
        "mention": {"type": "keyword"},
        "dosage": {"type": "keyword"},
        "evidence": {"type": "text"},
        "start_char": {"type": "integer"},
        "end_char": {"type": "integer"},
    }
},
"adverse_events": {
    "type": "nested",
    "properties": {
        "mention": {"type": "keyword"},
        "linked_medication": {"type": "keyword"},
        "evidence": {"type": "text"},
        "start_char": {"type": "integer"},
        "end_char": {"type": "integer"},
    }
},
"relations": {
    "type": "nested",
    "properties": {
        "drug": {"type": "keyword"},
        "adverse_event": {"type": "keyword"},
        "status": {"type": "keyword"},
        "evidence": {"type": "text"},
    }
},
"extraction_model_version": {"type": "keyword"},
Do NOT modify the existing fields. Only add new ones.
Note: The index already exists in production — adding new fields to ensure_index() only affects new index creation, not existing indices. Document this.

3. app/api/documents.py (MODIFY)
Add extraction step. It must run on ORIGINAL text BEFORE phi_tagger.
Find the section in documents.py where chunker runs, phi_tagger runs, and embedder runs.
Insert extraction between chunker and phi_tagger:

# NEW: extract structured entities from original (unmasked) text
if os.getenv("EXTRACTION_ENABLED", "true").lower() == "true":
    extractor = _get_extractor()  # add lazy singleton like _get_phi(), _get_embedder()
    for chunk in chunks:
        extraction = extractor.extract(chunk["text"], chunk["chunk_id"])
        chunk["medications"] = [
            {"mention": e.mention, "dosage": e.dosage, 
             "evidence": e.evidence,
             "start_char": e.source_span.start_char, 
             "end_char": e.source_span.end_char}
            for e in extraction.entities if e.entity_type == "medication"
        ]
        chunk["adverse_events"] = [
            {"mention": e.mention, "linked_medication": e.linked_medication,
             "evidence": e.evidence,
             "start_char": e.source_span.start_char,
             "end_char": e.source_span.end_char}
            for e in extraction.entities if e.entity_type == "adverse_event"
        ]
        # Build relations from linked_medication — NOT cartesian product of all drugs × ADEs.
        # linked_medication is populated by the model to indicate the specific drug each ADE is tied to.
        # Cartesian product would create wrong pairings for chunks with multiple drugs or ADEs.
        chunk["relations"] = []
        if extraction.relation_status == "related":
            for ae in extraction.entities:
                if ae.entity_type == "adverse_event" and ae.linked_medication:
                    chunk["relations"].append({
                        "drug": ae.linked_medication,
                        "adverse_event": ae.mention,
                        "status": "related",
                        "evidence": ae.evidence,
                    })
        chunk["extraction_model_version"] = os.getenv("EXTRACTION_ADAPTER_PATH", "models/adapters/qlora_v1")

# THEN phi_tagger runs (after extraction)
# ... existing phi_tagger code ...

Also add _get_extractor() lazy singleton function following the exact same pattern as _get_embedder() and _get_phi().

4. tests/test_extractor.py
Unit tests using mocked model. CRITICAL: do NOT load the real 7B model in any unit test.
Mock both model and tokenizer entirely using unittest.mock.patch or pytest monkeypatch.
The test file must be runnable with no GPU and no downloaded weights.
- Mock the model.generate() to return a valid JSON string
- Test extract() returns valid ExtractionResult
- Test extract() handles OOM (mock raises RuntimeError) → returns empty result, no crash
- Test EXTRACTION_ENABLED=false skips extraction

5. docs/reports/11_model_usage_strategy.md
Model Usage Strategy deliverable (PS §11). Include:
- Decision: ingestion-time only (not query-time)
- Why: latency (0 at query time), cost (one extraction per doc reused forever), Harmony fit
- How query-time structured search works: regex layer reads stored fields, no model call
- How reviewer workflow works: reads stored fields from OpenSearch, no model call
- How search result explanation works: evidence spans from ingestion surfaced in UI
- Trade-offs considered (ingestion vs query-time vs both)

Run: python -m pytest tests/test_extractor.py -v
All tests must pass before committing.

Commit and push feature/p3-harmony-integration.
Create PR: feature/p3-harmony-integration → feature/p3-fine-tuning
```

---

## Phase 7: Demo and Bonus Items

**Branch:** `feature/p3-final`
**PRs into:** `feature/p3-fine-tuning`
**Depends on:** All previous phases

**What this phase produces:**
```
demo/
  reviewer.py                    ← Streamlit reviewer panel (P5 + search result explanation)
  error_dashboard.py             ← P7 error analysis dashboard
  before_after.py                ← P5 before/after retrieval on golden_set.jsonl
docs/
  reports/
    08_training_pipeline.md      ← PS deliverable (links to notebooks)
    09_evaluation_harness.md     ← PS deliverable (links to harness code)
    10_validation_engine.md      ← PS deliverable (links to validator.py)
    13_final_report.md           ← PS deliverable (stitches everything)
```

---

### PHASE 7 PROMPT:

```
Read memory first, then do the following.

Project context: We are building Project 3 (Harmony Clinical Structuring Fine-Tuning System).
Design doc is at docs/Project3_Design_Document.md — read §17 (Harmony Integration) and §21 (Bonus Items) fully.
Also read: evaluation/reports/comparison.md (results from Phase 5), evaluation/reports/error_analysis.json

Task: Create the demo, error dashboard, and remaining report documents for Project 3.

Create the branch:
git checkout feature/p3-fine-tuning
git checkout -b feature/p3-final

Create the following files:

1. demo/reviewer.py
Streamlit app — Reviewer Panel. Run with: streamlit run demo/reviewer.py
Shows:
- Sidebar: enter search query
- Main panel: search results from Harmony OpenSearch (call existing /api/search or query directly)
- For each result: show the raw chunk text + a structured table of medications (mention, dosage, evidence) + a table of adverse events (mention, linked_medication, evidence)
- Highlight evidence spans in the raw text using st.markdown with colored spans
- Show extraction_model_version and validation flags per chunk
- If extraction fields are empty (extraction_enabled=false or failed): show "No structured extraction available"

2. demo/before_after.py
Streamlit app — P5 Before/After Retrieval Demo. Run with: streamlit run demo/before_after.py
Shows retrieval quality comparison:
- Load evaluation/golden_set.jsonl (existing Harmony golden set)
- For each golden query: run search WITHOUT structured filter, run WITH structured filter (medications.mention or adverse_events.mention keyword)
- Show side-by-side: documents retrieved before vs after
- Compute and display: Recall@5 before vs after
- Plots a simple bar chart comparing before/after recall
Note: This demonstrates bonus P5 — retrieval improvement from ingestion-time enrichment.

3. demo/error_dashboard.py
Streamlit app — P7 Error Analysis Dashboard. Run with: streamlit run demo/error_dashboard.py
Reads evaluation/reports/error_analysis.json and lora_v1.json and qlora_v1.json.
Shows:
- Tabs: JSON Invalid | Schema Invalid | Hallucinations | Span Errors | Enum Errors
- Each tab: table of example failures with input text, predicted output, gold output, failure reason
- Summary metrics sidebar: counts per error type, % of test set affected
- Model selector: compare LoRA vs QLoRA error distributions
- Bar chart: error type breakdown for LoRA vs QLoRA

4. docs/reports/08_training_pipeline.md
Training Pipeline deliverable. Include:
- Links to notebooks/p3_02_lora_train.ipynb and notebooks/p3_03_qlora_train.ipynb
- How to reproduce: step-by-step run instructions (upload data, set W&B key, run cells)
- Checkpoint saving and resume strategy
- W&B project link

5. docs/reports/09_evaluation_harness.md
Evaluation Harness deliverable. Include:
- How to run: python evaluation/harness/eval_runner.py --model [baseline|lora|qlora]
- What each EVAL metric measures (EVAL-02 through EVAL-08)
- The synthetic OOD set description and how to extend it
- Link to evaluation/reports/comparison.md for results

6. docs/reports/10_validation_engine.md
Validation Engine deliverable. Include:
- The six-layer guardrail pipeline (from design doc §15.1)
- How json_repair works
- How Pydantic v2 enforces schema
- The evidence-substring check
- What build_empty_result returns and why
- How to interpret validation flags in OpenSearch records

7. docs/reports/13_final_report.md
Final Report deliverable. Include these sections:
1. Executive Summary
2. Dataset (link to report 01)
3. Schema Design (link to report 02 + 03)
4. Data Format (link to report 04)
5. Model Selection (link to report 05)
6. Fine-Tuning Method (link to report 06)
7. Hyperparameter Results (link to report 07 + paste comparison table from evaluation/reports/comparison.md)
8. Evaluation Results (paste table from comparison.md with baseline vs LoRA vs QLoRA for all EVAL metrics)
9. Validation Engine (link to report 10)
10. Harmony Integration (link to report 11)
11. Cost/Environment (link to report 12)
12. Failure Analysis (summarize top 3 failure modes from error_analysis.json)
13. Recommendations (which adapter to use in production and why, what would improve results in v2)
14. Bonus Items Delivered (P2, P5, P7 — what was built and what it showed)

Commit and push feature/p3-final.
Create PR: feature/p3-final → feature/p3-fine-tuning
```

---

## Final Step: Merge to Main

After all 7 PRs are merged into `feature/p3-fine-tuning`:

```
FINAL PROMPT:

All 7 Project 3 phases are complete and merged into feature/p3-fine-tuning.
Create a final PR: feature/p3-fine-tuning → main

PR title: "feat: Project 3 — Harmony Clinical Structuring Fine-Tuning System"

PR body should include:
- What was built (fine-tuned Qwen2.5-7B with LoRA and QLoRA for drug/ADE extraction)
- Key results (paste final comparison table from evaluation/reports/comparison.md)
- Files added: list all new files
- Files modified: app/ingestion/indexer.py, app/api/documents.py
- How to run the demo: streamlit run demo/reviewer.py
- W&B project link
- Design doc location: docs/Project3_Design_Document.md
```

---

## Quick Reference: What Each Phase Delivers to PS §11

| PS Deliverable | Phase |
|---|---|
| Dataset Selection Report | Phase 1 |
| Schema Design Document | Phase 2 |
| Enums vs Free-Form Decision Record | Phase 2 |
| Data Format Specification | Phase 5 |
| Model Selection Report | Phase 3 |
| Fine-Tuning Method Report | Phase 3 |
| Hyperparameter Report | Phase 5 (after sweep results) |
| Training Pipeline | Phase 7 |
| Evaluation Harness | Phase 5 |
| Validation Engine | Phase 6 |
| Model Usage Strategy | Phase 6 |
| Cost/Environment Report | Phase 5 |
| Final Demo | Phase 7 |
| Final Report | Phase 7 |
