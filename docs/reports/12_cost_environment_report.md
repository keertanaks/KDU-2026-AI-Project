# Cost and Environment Report

**Project:** Harmony Clinical Structuring — Project 3  
**Phase:** Phase 3 / Phase 4 (LoRA + QLoRA Training)  
**Status:** Final  

---

## Training Hardware

Both fine-tuning runs use Kaggle's free GPU tier:

| Resource | LoRA (Account 1) | QLoRA (Account 2) |
|---|---|---|
| GPU | 2× NVIDIA Tesla T4 (16 GB VRAM each) | 1× NVIDIA Tesla T4 (16 GB VRAM) |
| CPU | 4 vCPU | 4 vCPU |
| RAM | 29 GB | 29 GB |
| GPU quota | 30 GPU-hours/week (free tier) | 30 GPU-hours/week (free tier) |
| Cost | $0 | $0 |

The T4 is a Turing-architecture GPU (compute capability 7.5). It does **not** support native BF16 hardware acceleration; all compute uses FP16. Attempting BF16 on a T4 triggers silent numerical degradation.

---

## Training Time

### LoRA (FP16, 2× T4)

| Configuration | Estimated Wall Time |
|---|---|
| Full hyperparameter sweep (multiple runs) | ~20–30 hours total |
| Option B single-run (best config, 3 epochs) | ~6.5 hours |
| Per-epoch estimate at effective batch 16 | ~2.0–2.2 hours |

The 2× T4 setup uses `device_map="auto"` which distributes model layers across both cards. Effective batch size of 16 is achieved via micro-batch=4 × gradient_accumulation=4.

### QLoRA (4-bit NF4, 1× T4)

| Configuration | Estimated Wall Time |
|---|---|
| Full 3-epoch run (best config) | ~8–9 hours |
| Per-epoch estimate | ~2.7–3.0 hours |

QLoRA's 4-bit NF4 quantization reduces VRAM to ~3.6 GB, enabling training on a single T4 within Kaggle's 9-hour session limit. The `paged_adamw_8bit` optimizer keeps optimizer states in CPU RAM, preventing OOM during gradient accumulation.

---

## VRAM Usage

| Phase | LoRA FP16 | QLoRA 4-bit NF4 |
|---|---|---|
| Model weights | ~14 GB (split 2× T4) | ~3.6 GB (1× T4) |
| Optimizer states | ~2–3 GB (adamw_torch) | ~1 GB (paged_adamw_8bit, CPU-offloaded) |
| Activations (seq len 256, batch 4) | ~1–2 GB per card | ~1 GB |
| Total VRAM at peak | ~15–16 GB across 2× T4 | ~5–6 GB on 1× T4 |
| **Inference VRAM (adapter loaded)** | **~14 GB** | **~3.6 GB** |

---

## Cost Comparison

| Approach | Hardware | Estimated Cost | Notes |
|---|---|---|---|
| Full fine-tune (FP16) | 1× A100 80GB, cloud | ~$50–80 | Not feasible on free tier; requires high-memory GPU |
| Full fine-tune (FP16) | 2× T4, cloud | N/A | T4 VRAM insufficient for full 7B FP16 fine-tune |
| LoRA (FP16) | 2× T4 Kaggle free | **$0** | 6.5 hr run within weekly quota |
| QLoRA (4-bit NF4) | 1× T4 Kaggle free | **$0** | 8–9 hr run within session limit |
| LoRA (FP16) | 1× A10G (AWS g5.xlarge) | ~$4–6/run | Cloud alternative if Kaggle quota exhausted |
| QLoRA (4-bit NF4) | 1× T4 (GCP spot) | ~$1–2/run | Cheapest cloud fallback |

Total project training cost: **$0** (Kaggle free tier).

---

## Production Deployment Recommendation

| Scenario | Recommended Variant | Rationale |
|---|---|---|
| Best extraction quality, GPU available | **LoRA FP16** | Higher numeric precision; full FP16 weights after merge |
| CPU-only inference, edge deployment | **QLoRA 4-bit** | ~75% VRAM reduction; model fits in 4–5 GB; suitable for quantized CPU runtimes |
| Cloud API with autoscaling | **QLoRA 4-bit** | Smaller memory footprint reduces instance cost; quality difference is modest |
| Research / iterative evaluation | **QLoRA 4-bit** | Fast iteration; low GPU cost per experiment |

For the Harmony ingestion pipeline, LoRA is preferred for the production path because inference runs once per document chunk at ingestion time, not at query time, so latency is not a user-facing concern. The FP16 adapter merges cleanly with the base model weights and avoids any quantization artifacts in the structured JSON output.

---

## Environment Notes

- Python 3.10 on Kaggle (CUDA 11.8, cuDNN 8.x)
- `transformers==4.46.x`, `peft==0.13.x`, `trl==0.11.x`, `bitsandbytes==0.43.x`
- Weights & Biases (`wandb`) used for experiment tracking; runs logged to project `harmony-p3-lora` and `harmony-p3-qlora`
- Model weights stored as `adapter_model.safetensors` + `adapter_config.json` under `models/adapters/lora_v1/` and `models/adapters/qlora_v1/`
- Base model (`Qwen/Qwen2.5-7B-Instruct`, ~15 GB) is gitignored and downloaded via `snapshot_download` at runtime
