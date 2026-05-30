# Report 08 — Training Pipeline

**Project:** Harmony Clinical Structuring (Project 3)
**Date:** 2026-05-30
**Branch:** feature/p3-lora-training

---

## 1. Overview

This report documents the end-to-end training pipeline for fine-tuning
`Qwen/Qwen2.5-7B-Instruct` on the `ade_corpus_v2` dataset. Two adapters were
produced: `lora_v1` (FP16 LoRA, production) and `qlora_v1` (4-bit NF4 QLoRA,
cost-constrained fallback). All training was executed on Kaggle T4 GPU notebooks.

---

## 2. Pipeline Overview

```
ade_corpus_v2 (HuggingFace)
     │
     ▼
Phase 1: Data Preparation (p3_01_data_prep.ipynb)
  • Load all 3 configs: drug_ade_relation, ade_true_labels, drug_ade_text
  • Deduplicate on text content
  • Group by md5(text) → 80/10/10 split (no row-level leakage)
  • Format as chat-format JSONL (user: INSTRUCTION + text, assistant: JSON)
     │
     ▼
data/processed/
  train.jsonl  (19,040 examples)
  val.jsonl    (2,380 examples)
  test.jsonl   (2,376 examples)
     │
     ▼
Phase 3: LoRA Training (p3_02_lora_train.ipynb — Kaggle Account 1)
  • Base: Qwen/Qwen2.5-7B-Instruct (FP16)
  • LoRA: r=16, alpha=32, target q_proj+v_proj
  • Optimizer: adamw_torch, LR=2e-4, 1 epoch
  • Hardware: T4×2 (Kaggle), ~3h45m
     │
     ▼
models/adapters/lora_v1/
  adapter_config.json
  adapter_model.safetensors

Phase 4: QLoRA Training (p3_03_qlora_train.ipynb — Kaggle Account 3)
  • Base: Qwen/Qwen2.5-7B-Instruct (4-bit NF4)
  • LoRA: r=16, alpha=32, target q_proj+v_proj
  • Optimizer: paged_adamw_8bit, LR=1e-4, 1 epoch
  • Hardware: T4×1 (Kaggle), ~4h
     │
     ▼
models/adapters/qlora_v1/
  adapter_config.json
  adapter_model.safetensors
```

---

## 3. Data Preparation (Phase 1)

### 3.1 Dataset

Source: `ade-benchmark-corpus/ade_corpus_v2` (HuggingFace, CC-BY license, no DUA).
All 3 configs were loaded and merged:

| Config | Purpose |
|---|---|
| `drug_ade_relation` | Sentence-level drug-ADE pairs with relation labels |
| `ade_true_labels` | ADE entity annotations |
| `drug_ade_text` | Drug entity annotations |

### 3.2 Train/Val/Test Split

Split strategy: group by `md5(text[:200])` hash, then assign bucket:
- `md5 % 10 in {0,1}` → val (10%)
- `md5 % 10 in {2,3}` → test (10%)
- else → train (80%)

This ensures all examples sharing identical source text appear in the same split,
preventing test-time leakage from duplicated sentences in the corpus.

| Split | Examples |
|---|---|
| Train | 19,040 |
| Val | 2,380 |
| Test | 2,376 |
| **Total** | **23,796** |

### 3.3 Chat Format

Each example is formatted as a HuggingFace chat-format message pair:

```json
{
  "messages": [
    {"role": "user", "content": "<INSTRUCTION>\n\nClinical text:\n<text>"},
    {"role": "assistant", "content": "{\"schema_version\": \"v1\", \"entities\": [...], \"relation_status\": \"...\"}"}
  ]
}
```

The INSTRUCTION string is identical to the one used at inference time in
`app/ingestion/extractor.py`. Any drift between training and inference instruction
format would degrade extraction quality.

---

## 4. LoRA Training Run (lora_v1)

### 4.1 Configuration

| Parameter | Value |
|---|---|
| Base model | `Qwen/Qwen2.5-7B-Instruct` |
| LoRA rank `r` | 16 |
| LoRA alpha | 32 |
| LoRA dropout | 0.05 |
| Target modules | `q_proj, v_proj` |
| Max sequence length | 256 tokens |
| Micro batch size | 4 |
| Gradient accumulation | 4 (effective batch = 16) |
| Epochs | 1 (= 1,190 optimizer steps) |
| Learning rate | 2e-4 |
| Optimizer | `adamw_torch` |
| LR scheduler | cosine |
| Compute dtype | `float16` |
| Hardware | Kaggle T4×2 |
| Training time | ~3h45m |

### 4.2 Loss Curve

Logged to W&B project `harmony-ade-extraction`, run group `lora_v1_final`.

| Step | Train Loss | Val Loss |
|---|---|---|
| 200 | 0.0407 | 0.0184 |
| 400 | 0.0308 | 0.0148 |
| 1190 (final) | ~0.028 | **0.0115** |

### 4.3 Adapter Storage

Adapter saved to `models/adapters/lora_v1/` and uploaded to HuggingFace Hub
(`keer2004ks/ade-lora-adapter`, private). The GGUF-quantized version
(`base-q8.gguf` + `adapter.gguf`) is served by the HuggingFace Space for
the Harmony ingestion pipeline in remote mode.

---

## 5. QLoRA Training Run (qlora_v1)

### 5.1 Configuration

| Parameter | Value |
|---|---|
| Base model | `Qwen/Qwen2.5-7B-Instruct` (4-bit NF4) |
| Quantization | `bitsandbytes` NF4, double-quant, compute dtype FP16 |
| LoRA rank `r` | 16 |
| LoRA alpha | 32 |
| Target modules | `q_proj, v_proj` |
| Max sequence length | 256 tokens |
| Micro batch size | 4 |
| Gradient accumulation | 4 (effective batch = 16) |
| Epochs | 1 |
| Learning rate | 1e-4 |
| Optimizer | `paged_adamw_8bit` |
| Hardware | Kaggle T4×1 |
| Training time | ~4h |

### 5.2 Loss Curve

| Step | Train Loss | Val Loss |
|---|---|---|
| 100 | 0.0375 | 0.0236 |
| 200 | 0.0402 | 0.0182 |
| 500 (final) | — | **0.0151** |

### 5.3 QLoRA vs LoRA

QLoRA final val_loss (0.0151) is higher than LoRA FP16 (0.0115). This is expected:
4-bit NF4 quantization introduces gradient noise during training that FP16 avoids.
QLoRA is retained as a cost-constrained fallback (fits on single T4 at ~8 GB VRAM
vs ~14 GB for LoRA FP16).

---

## 6. Experiment Tracking

All training runs tracked in Weights & Biases:
- **Project:** `harmony-ade-extraction`
- **Run groups:** `lora_lr_sweep_r16`, `lora_v1_final`, `qlora_sweep`

W&B run URLs are embedded in the training notebook outputs
(`notebooks/p3_02_lora_train.ipynb`, `notebooks/p3_03_qlora_train.ipynb`).

---

## 7. Adapter Artifacts

| Artifact | Location | Size |
|---|---|---|
| `lora_v1` adapter (safetensors) | `models/adapters/lora_v1/` | ~134 MB |
| `qlora_v1` adapter (safetensors) | `models/adapters/qlora_v1/` | ~134 MB |
| Base GGUF Q8_0 | HuggingFace Hub `keer2004ks/ade-lora-adapter/base-q8.gguf` | ~8 GB |
| Adapter GGUF | HuggingFace Hub `keer2004ks/ade-lora-adapter/adapter.gguf` | ~134 MB |

---

## 8. SFTTrainer Configuration (trl)

Training uses HuggingFace `trl.SFTTrainer` with the following key settings:

```python
training_args = TrainingArguments(
    output_dir="lora_v1",
    per_device_train_batch_size=4,
    gradient_accumulation_steps=4,
    learning_rate=2e-4,
    num_train_epochs=1,
    evaluation_strategy="steps",
    eval_steps=100,
    save_steps=500,
    bf16=False,     # T4 is Turing (cc 7.5) — no native BF16
    fp16=True,
    optim="adamw_torch",
    lr_scheduler_type="cosine",
    report_to="wandb",
    logging_steps=10,
)
```

---

## 9. Conclusions

- `lora_v1` (LoRA FP16) is the production adapter with eval_loss=0.0115.
- `qlora_v1` (QLoRA 4-bit) is a fallback with eval_loss=0.0151.
- The adapter is frozen for Phase 6 integration. No retraining is planned.
- See Report 07 for the hyperparameter sweep that selected LR=2e-4.
- See Report 09 for evaluation metrics on the held-out test set.
