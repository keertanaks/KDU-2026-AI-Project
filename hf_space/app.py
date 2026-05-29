# hf_space/app.py
#
# Harmony Project 3 — HuggingFace Space inference server.
#
# Lives at https://<username>-ade-inference.hf.space. Wraps the fine-tuned
# Qwen2.5-7B + LoRA adapter behind a single HTTP endpoint that the local
# Harmony backend calls via EXTRACTION_REMOTE_URL.
#
# Design choices honored here:
#   - INSTRUCTION below is byte-identical to the user-turn template in
#     app/ingestion/extractor.py and to the chat-format training data in
#     data/processed/train.jsonl. Do not paraphrase — drift here measurably
#     degrades extraction quality.
#   - Returns raw model JSON STRING (not a parsed dict) so the local validator
#     can run json_repair + Pydantic exactly as it does in the local-mode path.
#   - 4-bit quantization (NF4 + double-quant) so the 7B model fits in HF
#     Space CPU Basic free tier (~16 GB RAM). On GPU hardware this still works
#     and just runs faster.

import json
import logging
import os

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("harmony-extractor")

app = FastAPI(title="Harmony P3 Extractor", version="1.0")

# Configurable via Space "Variables" tab — defaults assume the same HF account
# owns both the adapter repo and this Space.
BASE_MODEL = os.getenv("BASE_MODEL", "Qwen/Qwen2.5-7B-Instruct")
ADAPTER_PATH = os.getenv("ADAPTER_PATH", "REPLACE_WITH_YOUR_USERNAME/ade-lora-adapter")
MAX_NEW_TOKENS = int(os.getenv("MAX_NEW_TOKENS", "512"))

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
# Model load — happens once at startup, blocks until ready
# ---------------------------------------------------------------------------


def _load_model_and_tokenizer():
    logger.info("Loading tokenizer from %s", ADAPTER_PATH)
    tokenizer = AutoTokenizer.from_pretrained(ADAPTER_PATH, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    use_cuda = torch.cuda.is_available()
    logger.info("CUDA available: %s", use_cuda)

    if use_cuda:
        bnb = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
        )
        logger.info("Loading base model %s with 4-bit quantization", BASE_MODEL)
        base = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL,
            quantization_config=bnb,
            device_map="auto",
            trust_remote_code=True,
        )
    else:
        # CPU fallback — slow but lets the free CPU tier work.
        logger.info("Loading base model %s on CPU (float32)", BASE_MODEL)
        base = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL,
            torch_dtype=torch.float32,
            device_map=None,
            trust_remote_code=True,
        )

    logger.info("Attaching LoRA adapter from %s", ADAPTER_PATH)
    model = PeftModel.from_pretrained(base, ADAPTER_PATH)
    model.eval()
    logger.info("Model ready.")
    return model, tokenizer


MODEL, TOKENIZER = _load_model_and_tokenizer()


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------


class ExtractRequest(BaseModel):
    text: str
    record_id: str | None = None  # optional, only used in logs


class ExtractResponse(BaseModel):
    raw_output: str
    model_version: str = "lora_v1"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health():
    """Liveness probe. Returns immediately once model is loaded."""
    return {"status": "ok", "model": BASE_MODEL, "adapter": ADAPTER_PATH}


@app.post("/extract", response_model=ExtractResponse)
def extract(req: ExtractRequest):
    """Run the fine-tuned extractor on ``req.text``.

    Returns the RAW generated string. The local Harmony backend's
    validator.py is responsible for json_repair + Pydantic validation +
    evidence checks. Keeping the responsibility split that way means this
    server stays a thin inference layer with no schema knowledge.
    """
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="text must be non-empty")

    messages = [
        {"role": "user", "content": f"{INSTRUCTION}\n\nClinical text:\n{req.text}"}
    ]
    prompt = TOKENIZER.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = TOKENIZER(prompt, return_tensors="pt").to(MODEL.device)

    try:
        with torch.no_grad():
            output_ids = MODEL.generate(
                **inputs,
                do_sample=False,
                max_new_tokens=MAX_NEW_TOKENS,
                repetition_penalty=1.05,
                pad_token_id=TOKENIZER.eos_token_id,
            )
    except Exception as exc:
        logger.error("generate() failed for record %s: %s", req.record_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"inference_failed: {exc}")

    prompt_len = inputs.input_ids.shape[1]
    decoded = TOKENIZER.decode(
        output_ids[0][prompt_len:], skip_special_tokens=True
    ).strip()

    logger.info("record_id=%s output_len=%d", req.record_id, len(decoded))
    return ExtractResponse(raw_output=decoded, model_version="lora_v1")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)
