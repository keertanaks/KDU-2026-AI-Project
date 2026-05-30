# hf_space/app.py
#
# Harmony Project 3 — HuggingFace Space inference server.
# Uses llama-cpp-python with GGUF quantised model (Q8_0 base + LoRA adapter).
# Runs on free CPU tier (16 GB RAM) — inference ~20-40s per chunk.
#
# INSTRUCTION must stay byte-identical to app/ingestion/extractor.py.

import json
import logging
import os

import uvicorn
from fastapi import FastAPI, HTTPException
from huggingface_hub import hf_hub_download
from llama_cpp import Llama
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("harmony-extractor")

app = FastAPI(title="Harmony P3 Extractor", version="2.0")

REPO_ID      = os.getenv("REPO_ID",       "keer2004ks/ade-lora-adapter")
BASE_FILE    = os.getenv("BASE_FILE",     "base-q8.gguf")
ADAPTER_FILE = os.getenv("ADAPTER_FILE",  "adapter.gguf")
N_CTX        = int(os.getenv("N_CTX",     "512"))
N_THREADS    = int(os.getenv("N_THREADS", "2"))
MAX_TOKENS   = int(os.getenv("MAX_TOKENS", "512"))

# MUST stay byte-identical to app/ingestion/extractor.py::INSTRUCTION.
INSTRUCTION = (
    "You are a clinical information extractor. Given a clinical text, extract all\n"
    "medications and adverse events as a JSON object that follows the schema below.\n"
    "Return ONLY valid JSON. If no entity is present, return entities=[] and\n"
    'relation_status="none".\n\n'
    "Return ONLY this JSON structure (no record_id, no validation block — those are added by the system):\n"
    "{\n"
    '  "schema_version": "v1",\n'
    '  "entities": [\n'
    "    {\n"
    '      "entity_type": "medication" | "adverse_event",\n'
    '      "mention": "<string>",\n'
    '      "dosage": "<string>" | null,\n'
    '      "linked_medication": "<string>" | null,\n'
    '      "evidence": "<string>",\n'
    '      "source_span": {"start_char": <int>, "end_char": <int>}\n'
    "    }\n"
    "  ],\n"
    '  "relation_status": "related" | "not_related" | "none"\n'
    "}"
)

# ---------------------------------------------------------------------------
# Model load — once at startup
# ---------------------------------------------------------------------------

def _load_model() -> Llama:
    logger.info("Downloading %s from %s ...", BASE_FILE, REPO_ID)
    base_path = hf_hub_download(repo_id=REPO_ID, filename=BASE_FILE)
    logger.info("Base GGUF at: %s", base_path)

    logger.info("Downloading %s ...", ADAPTER_FILE)
    adapter_path = hf_hub_download(repo_id=REPO_ID, filename=ADAPTER_FILE)
    logger.info("Adapter GGUF at: %s", adapter_path)

    logger.info("Loading model (n_ctx=%d, n_threads=%d) ...", N_CTX, N_THREADS)
    llm = Llama(
        model_path=base_path,
        lora_path=adapter_path,
        n_ctx=N_CTX,
        n_threads=N_THREADS,
        verbose=False,
    )
    logger.info("Model ready.")
    return llm


LLM: Llama = _load_model()


# ---------------------------------------------------------------------------
# Request / response
# ---------------------------------------------------------------------------

class ExtractRequest(BaseModel):
    text: str
    record_id: str | None = None


class ExtractResponse(BaseModel):
    raw_output: str
    model_version: str = "lora_v1_gguf"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "model": BASE_FILE, "adapter": ADAPTER_FILE}


@app.post("/extract", response_model=ExtractResponse)
def extract(req: ExtractRequest):
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="text must be non-empty")

    messages = [
        {"role": "user", "content": f"{INSTRUCTION}\n\nClinical text:\n{req.text}"}
    ]

    try:
        response = LLM.create_chat_completion(
            messages=messages,
            max_tokens=MAX_TOKENS,
            temperature=0.0,
            repeat_penalty=1.05,
        )
    except Exception as exc:
        logger.error("Inference failed for record %s: %s", req.record_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"inference_failed: {exc}")

    raw = response["choices"][0]["message"]["content"].strip()
    logger.info("record_id=%s output_len=%d", req.record_id, len(raw))
    return ExtractResponse(raw_output=raw)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)
