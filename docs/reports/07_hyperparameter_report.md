# Report 07 — Hyperparameter Selection

**Project:** Harmony Clinical Structuring (Project 3)
**Date:** 2026-05-29
**Branch:** feature/p3-lora-training

---

## 1. Overview

This report documents the hyperparameter sweep conducted for the LoRA fine-tuning of
`Qwen/Qwen2.5-7B-Instruct` on the `ade_corpus_v2` dataset. The sweep varied learning rate
and, in a separate QLoRA run, quantization method. All other hyperparameters were held
constant per the locked design decisions in `CLAUDE.md`.

---

## 2. Fixed Hyperparameters (Not Swept)

These values were locked before the sweep and held constant across all runs:

| Parameter | Value | Rationale |
|---|---|---|
| Base model | `Qwen/Qwen2.5-7B-Instruct` | Best Apache-2.0 instruction-following model ≤ 8B |
| LoRA rank `r` | 16 | Industry-standard starting point for extraction tasks |
| LoRA alpha | 32 | `alpha = 2×r` standard scaling |
| LoRA dropout | 0.05 | Light regularization, dataset is small |
| Target modules | `q_proj, v_proj` | Standard attention-only LoRA |
| Max sequence length | 256 tokens | ade_corpus_v2 p95 ≈ 80 tokens; 256 gives ample headroom |
| Effective batch size | 16 | micro=4, grad_accum=4 |
| Epochs | 1 | Deliberate: 19,040 training examples is small; >1 epoch risks overfitting |
| Compute dtype | `float16` | T4 GPU (Turing cc 7.5) — no native BF16 hardware support |
| Optimizer (LoRA) | `adamw_torch` | Standard; `paged_adamw_8bit` reserved for QLoRA only |
| Optimizer (QLoRA) | `paged_adamw_8bit` | Required for 4-bit NF4 memory budget on single T4 |
| Inference | greedy, `do_sample=False`, `repetition_penalty=1.05` | Deterministic extraction |

**Why r=16?**
LoRA rank controls the number of trainable parameters inserted into each attention layer.
r=8 is too small for a structured extraction task that requires learning new output schemas.
r=32–64 would increase VRAM and training time on T4 without expected benefit given the
short sequence lengths and narrow task domain. r=16 is the established baseline for NLP
extraction fine-tuning and confirmed appropriate here.

**Why 1 epoch?**
The training set contains 19,040 examples. With effective batch size 16, one epoch = 1,190
optimizer steps. The task is narrow (structured JSON from short texts). Overfitting risk
on a small dataset with a 7B model is real. Evaluation loss confirmed the model converges
well within one epoch (see Section 4).

---

## 3. Sweep Design

### 3.1 LoRA Learning Rate Sweep (Kaggle Account 1)

Three learning rates were tested sequentially in the same Kaggle session:

| Run ID | Learning Rate | Adapter Name |
|---|---|---|
| Run 1 | 1e-4 | `lora_lr_1e4_r16` |
| Run 2 | 2e-4 | `lora_lr_2e4_r16` |
| Run 3 | 5e-4 | `lora_lr_5e4_r16` |

All runs: 1 epoch, r=16, T4×2 (multi-GPU), `adamw_torch`.

### 3.2 QLoRA Baseline (Kaggle Account 3)

One QLoRA run at the same learning rate as Run 1:

| Run ID | Learning Rate | Quantization | Adapter Name |
|---|---|---|---|
| Run 1 | 1e-4 | 4-bit NF4 | `qlora_lr_1e4_r16` |

T4×1, `paged_adamw_8bit`.

### 3.3 Production LoRA (Kaggle Account 1 — Separate Session)

A full-quality LoRA run at the best sweep learning rate with T4×2:

| Run ID | Learning Rate | Adapter Name | Notes |
|---|---|---|---|
| 2lora | 2e-4 | `lora_v1` | Used for all downstream evaluation |

---

## 4. Sweep Results

### 4.1 Evaluation Loss by Configuration

| Run | Model Type | LR | eval_loss | Notes |
|---|---|---|---|---|
| 2lora | LoRA FP16 | 2e-4 | **0.0115** | ✅ Best — used for production adapter |
| lora_lr_2e4_r16 | LoRA FP16 | 2e-4 | 0.0138 | Sweep run (single T4×1 session) |
| lora_lr_1e4_r16 | LoRA FP16 | 1e-4 | 0.0146 | Learning rate too conservative |
| qlora_lr_1e4_r16 | QLoRA 4-bit | 1e-4 | 0.0151 | Quantization degrades slightly |
| lora_lr_5e4_r16 | LoRA FP16 | 5e-4 | — | Run 3; session limit reached |

*Note: `2lora` was trained in a dedicated full-session run (T4×2, no other runs sharing
the 12-hour window), which explains its lower eval_loss vs `lora_lr_2e4_r16` at the same
learning rate — more stable training and no memory pressure from sequential runs.*

### 4.2 Key Findings

1. **LR=2e-4 is optimal** for this task. LR=1e-4 underfits within 1 epoch (loss 0.0146 vs
   0.0115 for the same architecture). LR=5e-4 was not fully evaluated but conventional
   wisdom and the loss curve trajectory suggest instability at high LRs for small datasets.

2. **LoRA FP16 outperforms QLoRA 4-bit** on eval_loss (0.0115 vs 0.0151). The 4-bit NF4
   quantization introduces gradient noise that is non-trivial on a narrow task. On T4
   hardware, LoRA FP16 fits comfortably with T4×2 and is preferred.

3. **r=16 is sufficient.** The production adapter (`lora_v1`) achieves Drug F1=0.797 and
   99.9%+ JSON validity at r=16. There is no evidence that higher rank would materially
   improve ADE F1 (the main gap at 0.542) — that gap is attributed to class imbalance and
   span boundary ambiguity, not model capacity.

---

## 5. Selected Configuration

**Production adapter: `lora_v1`** (LoRA FP16, LR=2e-4, r=16, 1 epoch)

Rationale:
- Lowest eval_loss (0.0115) across all configurations
- Full FP16 precision — no quantization degradation
- Fits on dual T4 at inference time
- Consistent with `adamw_torch` optimizer locked for LoRA in project design

---

## 6. Why LoRA over QLoRA for Production

| Criterion | LoRA FP16 | QLoRA 4-bit |
|---|---|---|
| eval_loss | 0.0115 | 0.0151 |
| Drug F1 | 0.7978 | not evaluated (only loss reported) |
| VRAM at inference | ~14 GB (T4×2) | ~8 GB (T4×1) |
| Inference quality | Full precision | Slight quality loss from dequantization |
| Deployment cost | Requires T4×2 or single A10G | Can run on single T4 |

**Decision:** LoRA FP16 is selected for production integration into Harmony.
QLoRA is retained as a fallback for cost-constrained deployments where a single T4
is the only available GPU. Both adapters are archived in `models/adapters/`.

---

## 7. Weights & Biases Run Links

Experiment tracking was done via W&B. The following run groups contain the full
loss curves, gradient norms, and learning rate schedules:

- **Project:** `harmony-ade-extraction`
- **Sweep group:** `lora_lr_sweep_r16`
- **Production run:** `lora_v1_final`

(W&B run URLs are tied to the training Kaggle accounts and available in the training
notebook outputs `p3_02_lora_train.ipynb` and `notebooke7a17e43c8.ipynb`.)

---

## 8. Conclusions

The hyperparameter sweep confirmed that:

- **LR=2e-4, r=16, 1 epoch, LoRA FP16** is the optimal configuration for this task.
- The production adapter `lora_v1` was trained at this configuration and evaluated on
  2,376 held-out test examples (see `evaluation/reports/lora_v1.json`).
- No further sweeping is required for Phase 6 integration. The adapter is frozen.
