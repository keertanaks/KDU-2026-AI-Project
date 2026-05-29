---
title: Harmony P3 Extractor
emoji: 💊
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
license: apache-2.0
short_description: Fine-tuned Qwen2.5-7B + LoRA for clinical drug/ADE extraction
---

# Harmony Project 3 — Clinical Extractor (HF Space)

Inference server for the Harmony clinical structuring fine-tune
(Qwen2.5-7B-Instruct + LoRA adapter trained on `ade_corpus_v2`).
Exposes one endpoint:

- `POST /extract` — body `{"text": "<clinical text>"}` → `{"raw_output": "<json string>", "model_version": "lora_v1"}`
- `GET /health` — liveness probe

The returned `raw_output` is the raw model JSON; the Harmony backend's
validator (json_repair + Pydantic v2 + evidence checks) parses it locally.

## How it's used

This Space is called by the Harmony backend during ingest. The local
backend sets `EXTRACTION_REMOTE_URL=https://<space-url>` in its `.env` —
its `ClinicalExtractor` then POSTs to `/extract` instead of loading the
model locally. See `app/ingestion/extractor.py` in the Harmony repo.

## Hardware

- **CPU Basic (free):** model loads in float32. Inference ~30 s – 2 min per
  short clinical sentence. Acceptable for demo, slow for live use.
- **T4 small (paid, ~$0.60/hr):** 4-bit NF4 quantization (see `app.py`),
  inference ~2 s per chunk. Recommended for demo day.

## Variables (optional, set in Space → Settings → Variables)

| Variable | Default | Purpose |
|---|---|---|
| `BASE_MODEL` | `Qwen/Qwen2.5-7B-Instruct` | HF id of the base model |
| `ADAPTER_PATH` | `keer2004ks/ade-lora-adapter` | HF id of the LoRA adapter repo |
| `MAX_NEW_TOKENS` | `512` | Generation length cap |

## Schema produced

The model is trained to emit:

```json
{
  "schema_version": "v1",
  "entities": [
    {
      "entity_type": "medication" | "adverse_event",
      "mention": "<string>",
      "dosage": "<string>" | null,
      "linked_medication": "<string>" | null,
      "evidence": "<string>",
      "source_span": {"start_char": <int>, "end_char": <int>}
    }
  ],
  "relation_status": "related" | "not_related" | "none"
}
```

The local validator injects `record_id`, `validation`, and `error_reason`
after receiving this output — see `app/ingestion/validator.py`.

## Project context

- Repo: <https://github.com/keertanaks/KDU-2026-AI-Project>
- Phase 3 (LoRA training): merged via PR #26
- Phase 6 (Harmony integration): PR #28
- Adapter base: Qwen2.5-7B-Instruct (Apache 2.0)
- Training data: `ade-benchmark-corpus/ade_corpus_v2` (CC-BY)
- HIPAA posture: project is "HIPAA-aware design," NOT certified.
  Use only with synthetic / non-PHI data.
