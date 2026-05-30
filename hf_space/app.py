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
import threading

import gradio as gr
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
_LLM_LOCK = threading.Lock()  # llama-cpp-python is not thread-safe


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
        with _LLM_LOCK:
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


# ---------------------------------------------------------------------------
# Gradio demo UI — mounted at "/" so the Space has a visible interface.
# The /extract and /health FastAPI routes are still reachable by the
# Harmony ingestion pipeline at their original paths.
# ---------------------------------------------------------------------------

EXAMPLES = [
    ["The patient developed severe hepatotoxicity after 3 months of isoniazid therapy."],
    ["Warfarin therapy was initiated; patient subsequently reported GI bleeding episodes."],
    ["Methotrexate 15mg weekly was initiated; the patient developed oral mucositis and elevated liver enzymes."],
    ["Ibuprofen 400mg was prescribed. Two days later the patient developed acute renal failure."],
    ["Patient was prescribed metformin 500mg BID for type 2 diabetes. No adverse events noted."],
]


def gradio_predict(text: str) -> str:
    if not text or not text.strip():
        return json.dumps({"error": "Please enter some clinical text."}, indent=2)
    try:
        resp = extract(ExtractRequest(text=text, record_id="gradio_demo"))
        raw = resp.raw_output
    except HTTPException as exc:
        return json.dumps({"error": exc.detail}, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, indent=2)
    try:
        return json.dumps(json.loads(raw), indent=2)
    except Exception:
        return raw


with gr.Blocks(
    theme=gr.themes.Soft(
        primary_hue="indigo",
        secondary_hue="blue",
        font=[gr.themes.GoogleFont("Inter"), "sans-serif"],
    ),
    title="Harmony Clinical Structuring",
) as demo:
    gr.Markdown(
        """
# Harmony Clinical Structuring
### LoRA Fine-tuned Qwen2.5-7B-Instruct · Clinical Drug & ADE Extraction

Fine-tuned on [ade_corpus_v2](https://huggingface.co/datasets/ade-benchmark-corpus/ade_corpus_v2)
· Powers the [Harmony Healthcare RAG](https://github.com/keertanaks/KDU-2026-AI-Project) ingestion pipeline
· Schema v1 · Drug F1 = 0.798
        """
    )

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### Input")
            text_input = gr.Textbox(
                lines=6,
                placeholder="Enter a clinical sentence, e.g.:\n\nThe patient developed severe rash after taking amoxicillin 500mg.",
                label="Clinical Text",
                show_label=False,
            )
            with gr.Row():
                clear_btn = gr.Button("Clear", variant="secondary")
                submit_btn = gr.Button("Extract", variant="primary", scale=2)

            gr.Markdown(
                """
**What the model extracts:**
- 💊 Medications with dosage and character spans
- ⚠️ Adverse events linked to their causative drug
- 🔗 Relation status (related / not_related / none)

> CPU inference — response takes **1–3 minutes**.
> One request at a time.
                """
            )

        with gr.Column(scale=1):
            gr.Markdown("### Extraction Result")
            json_output = gr.Code(
                language="json",
                label="Structured Output",
                show_label=False,
                lines=20,
            )

    gr.Markdown("### Try an example")
    gr.Examples(
        examples=EXAMPLES,
        inputs=text_input,
        label="",
    )

    submit_btn.click(fn=gradio_predict, inputs=text_input, outputs=json_output)
    clear_btn.click(fn=lambda: ("", ""), outputs=[text_input, json_output])

    gr.Markdown(
        """
---
**Model:** Qwen2.5-7B-Instruct + LoRA adapter (r=16, alpha=32, FP16) · **Training data:** 19,020 examples from ade_corpus_v2 · **Eval:** Drug F1 0.798 · ADE F1 0.542 · Hallucination rate 0.04%
        """
    )

# Mount Gradio at root — FastAPI API routes (/extract, /health) are unaffected.
app = gr.mount_gradio_app(app, demo, path="/")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)
