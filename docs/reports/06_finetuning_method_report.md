# Fine-Tuning Method Report — Harmony Clinical Structuring Fine-Tuning

**Report:** 06  
**Phase:** Phase 3 — LoRA Fine-Tuning  
**Date:** 2026-05-28  
**Status:** Locked — decision finalized

---

## 1. Purpose

This report documents the fine-tuning method selection for the Harmony clinical ADE extraction system. The methods form a stack — SFT, PEFT, LoRA, and QLoRA are not four independent alternatives but four layers of the same training recipe. This document explains the stack, the memory budget analysis that makes full fine-tuning infeasible, and the rationale for running both LoRA-FP16 and QLoRA-4bit as two parallel experiments.

---

## 2. The Fine-Tuning Stack

Fine-tuning Qwen2.5-7B-Instruct involves four layered concepts:

```
SFT (Supervised Fine-Tuning)
  └── objective: token-level cross-entropy on labeled (input, output) pairs
  └── PEFT (Parameter-Efficient Fine-Tuning)
        └── strategy: freeze base model, train only a small adapter
        └── LoRA (Low-Rank Adaptation)
              └── mechanism: inject low-rank matrices into attention/MLP projections
              └── variants:
                    ├── LoRA-FP16  — base model in FP16, adapters in FP16
                    └── QLoRA-4bit — base model in 4-bit NF4, adapters in FP16
```

All four experiments in this project use SFT + PEFT + LoRA. The only axis of variation between notebook 2 (LoRA) and notebook 3 (QLoRA) is the **quantization level of the base model weights** and the consequent **optimizer choice**.

---

## 3. Why Full Fine-Tuning Is Infeasible

Full fine-tuning (updating all 7.6B parameters) would require storing:
- Model weights in FP32: ~30 GB
- Gradients (same size as weights): ~30 GB
- Adam optimizer states (2× gradients): ~60 GB
- **Total: ~120 GB**

The T4×2 environment provides **30 GB total VRAM**. Full fine-tuning requires ~120 GB — 4× the available budget. This is a hard architectural finding, not a skipped optimization. The only path to fine-tuning Qwen2.5-7B-Instruct on T4×2 is PEFT.

| Method | Approx VRAM | Feasible on T4×2 |
|---|---|---|
| Full fine-tuning (FP32) | ~120 GB | ❌ Infeasible |
| Full fine-tuning (FP16) | ~80 GB | ❌ Infeasible |
| LoRA-FP16 | ~24 GB | ✅ Tight but fits |
| QLoRA-4bit | ~9 GB | ✅ Comfortable |

---

## 4. Memory Budget Detail

### 4.1 LoRA-FP16 (Notebook 2)

- Base model weights (FP16): ~15 GB
- LoRA adapter (FP16, r=16, 7 modules): ~0.15 GB
- Gradient checkpointing: reduces activation memory by ~4× at cost of recompute
- AdamW optimizer states for adapter params only: ~0.3 GB
- Activations + forward/backward pass overhead: ~8 GB
- **Total estimate: ~24 GB** — fits within 30 GB budget with gradient checkpointing enabled

### 4.2 QLoRA-4bit (Notebook 3)

- Base model weights (4-bit NF4 with double quantization): ~4–5 GB
- LoRA adapter (FP16): ~0.15 GB
- Paged AdamW optimizer states (paged to CPU when needed): ~0.3 GB
- Activations + overhead: ~4 GB
- **Total estimate: ~9 GB** — very comfortable, ample headroom for larger batches if needed

---

## 5. Method Comparison: LoRA-FP16 vs QLoRA-4bit

| Aspect | LoRA-FP16 (Notebook 2) | QLoRA-4bit (Notebook 3) |
|---|---|---|
| Base model precision | FP16 | 4-bit NF4 with double quantization |
| Adapter precision | FP16 | FP16 |
| VRAM usage | ~24 GB | ~9 GB |
| Quantization noise | None | Small (NF4 is near-lossless) |
| Training stability | High (full FP16 compute) | High (compute dtype=FP16) |
| Optimizer | adamw_torch | paged_adamw_8bit |
| Purpose | Clean baseline, no quantization artifacts | Tests whether 4-bit base model degrades F1 |

Both notebooks train the **same LoRA adapter architecture** (same target modules, same rank sweep, same effective batch size). The only difference is the base model quantization and the optimizer. This makes the two results directly comparable: any F1 gap between them is attributable to quantization noise from the 4-bit base.

---

## 6. Optimizer Selection

### 6.1 LoRA notebook: `adamw_torch`

Standard AdamW from PyTorch. Correct choice when the base model is in FP16 and optimizer states can live in GPU VRAM — which they can, since only the LoRA adapter parameters (~0.3 GB) need optimizer states. There is no reason to use paged optimizer states when VRAM is sufficient.

### 6.2 QLoRA notebook: `paged_adamw_8bit`

When the base model is loaded in 4-bit NF4, there is less VRAM available for optimizer states. `paged_adamw_8bit` from bitsandbytes:
1. Stores Adam's first and second moment estimates in 8-bit rather than FP32, reducing their memory by 4×
2. Pages optimizer states to CPU RAM when GPU VRAM is under pressure, then pages them back as needed

This is a **required** choice for QLoRA — using `adamw_torch` with a 4-bit base model risks OOM during the optimizer step. The paging mechanism is transparent to the trainer.

---

## 7. FP16 Not BF16: T4 Architecture Constraint

T4 is a Turing architecture GPU (compute capability 7.5). BF16 hardware acceleration was introduced in Ampere (compute capability 8.0, e.g., A100, A10G). On Turing:
- FP16: native hardware support → fast
- BF16: **software emulation** → 3–5× slower than FP16 on the same hardware

Therefore:
- Both notebooks use `fp16=True, bf16=False`
- The QLoRA notebook sets `bnb_4bit_compute_dtype=torch.float16` (not bfloat16) in BitsAndBytesConfig

Using BF16 on T4 would not cause incorrect results but would dramatically slow training. This is a hardware constraint, not a numerical preference.

---

## 8. Loss Masking

Both notebooks use `DataCollatorForCompletionOnlyLM` with `response_template="<|im_start|>assistant\n"`. This masks all tokens in the user turn (sets their labels to -100), so cross-entropy loss is computed **only on the assistant's JSON output tokens**.

Without loss masking, the model would be penalized for how it generates the instruction text, which it should not be generating at inference time. Loss masking ensures the model learns to produce the JSON output conditioned on the instruction, not to predict the instruction itself.

---

## 9. Gradient Checkpointing

Both notebooks enable `gradient_checkpointing=True`.

Gradient checkpointing trades compute for memory: instead of storing all intermediate activations during the forward pass (needed for backpropagation), it recomputes them during the backward pass. This adds ~30% compute overhead but reduces activation memory by ~4×.

For LoRA-FP16 on T4×2 (~24 GB estimated), gradient checkpointing is **required** to fit within budget. For QLoRA-4bit (~9 GB estimated), it is good practice even when not strictly required.

---

## 10. Hyperparameter Sweep Design

Each notebook runs 7 experiments following a two-phase sweep:

**Phase 1 — Learning rate sweep (3 runs)**
Fix LORA_RANK=16, vary LEARNING_RATE ∈ {1e-4, 2e-4, 5e-4} at MAX_STEPS=500. Pick the LR with the lowest eval_loss.

**Phase 2 — Rank sweep (3 runs)**
Fix best LR, vary LORA_RANK ∈ {8, 16, 32} at MAX_STEPS=500. Pick the rank with the lowest eval_loss.

**Final run (1 run)**
Fix best LR and best rank, set MAX_STEPS=-1 and NUM_EPOCHS=3. This is the production adapter.

The sweep is designed to be resumable: checkpoints are saved every 100 steps with `save_total_limit=3`, and `RESUME_FROM_CHECKPOINT` in the Cell 2 config allows resuming after a Kaggle session timeout.

---

## 11. References

- QLoRA: Efficient Finetuning of Quantized LLMs (Dettmers et al., 2023)
- LoRA: Low-Rank Adaptation of Large Language Models (Hu et al., 2021)
- bitsandbytes library: 4-bit NF4 quantization and paged optimizers
- See `docs/reports/05_model_selection_report.md` for base model selection rationale
