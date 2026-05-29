# app/ingestion/extractor.py
#
# Project 3 — Phase 6: Clinical entity extractor.
#
# Wraps the fine-tuned Qwen2.5-7B + LoRA adapter (Phase 3) behind a stable interface
# the ingestion pipeline can call. Lazy-loaded singleton — model weights are only
# materialized on first .extract() call so unit tests and import-time code paths stay
# light.
#
# Architectural rules honored here:
#   D-35: Extraction runs on ORIGINAL (unmasked) text. The caller in
#         app/api/documents.py invokes us on chunk.child_text BEFORE persisting any
#         PHI-masked variant. Source-span offsets are therefore valid against the
#         original chunk text.
#   D-15: No external API calls at inference time — everything runs on the local
#         base model + LoRA adapter.
#   D-23: Never crash the ingestion pipeline. Any OOM / CUDA error / missing adapter
#         must degrade gracefully via build_empty_result(reason=...).
#
# Public surface:
#   ClinicalExtractor.get()             -> singleton instance
#   ClinicalExtractor.extract(text, id) -> ExtractionResult
#   ClinicalExtractor.adapter_version() -> str (for OpenSearch extraction_model_version field)
#
# Environment variables (read once at first .get() call):
#   EXTRACTION_ENABLED        ("true" | "false") default "true"
#   EXTRACTION_BASE_MODEL     HuggingFace model id or local path
#                             default "Qwen/Qwen2.5-7B-Instruct"
#   EXTRACTION_ADAPTER_PATH   Local LoRA adapter directory
#                             default "models/adapters/lora_v1"
#   EXTRACTION_DEVICE         "auto" | "cpu" | "cuda" — passed to from_pretrained
#                             default "auto"
#   EXTRACTION_MAX_NEW_TOKENS Max tokens to generate per call (greedy decoding)
#                             default "512"

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from app.ingestion.validator import build_empty_result, validate_extraction
from app.schemas.extraction import ExtractionResult

load_dotenv(Path(__file__).parent.parent.parent / "config" / ".env")

logger = logging.getLogger(__name__)


# Instruction template — MUST match the user-turn template used in Phase 1 training
# (data/processed/train.jsonl). Any drift here will degrade extraction quality.
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


class ClinicalExtractor:
    """Lazy-loaded singleton wrapper around the fine-tuned extraction model.

    Use ``ClinicalExtractor.get()`` to obtain the singleton; never instantiate
    directly in callers (the constructor is reserved for tests that need to
    inject a mocked model/tokenizer pair).
    """

    _instance: Optional["ClinicalExtractor"] = None

    def __init__(self, model=None, tokenizer=None) -> None:
        # Read env vars at construction time. Defaults match the production layout.
        self.enabled: bool = (
            os.getenv("EXTRACTION_ENABLED", "true").lower() == "true"
        )
        self.base_model: str = os.getenv(
            "EXTRACTION_BASE_MODEL", "Qwen/Qwen2.5-7B-Instruct"
        )
        self.adapter_path: str = os.getenv(
            "EXTRACTION_ADAPTER_PATH", "models/adapters/lora_v1"
        )
        self.device: str = os.getenv("EXTRACTION_DEVICE", "auto")
        self.max_new_tokens: int = int(os.getenv("EXTRACTION_MAX_NEW_TOKENS", "512"))

        # Injected by tests; loaded lazily in production.
        self._model = model
        self._tokenizer = tokenizer

    # ------------------------------------------------------------------ public

    @classmethod
    def get(cls) -> "ClinicalExtractor":
        """Return process-wide singleton."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_singleton(cls) -> None:
        """Drop the cached instance. Intended for tests; not for production callers."""
        cls._instance = None

    def adapter_version(self) -> str:
        """Identifier persisted to OpenSearch as ``extraction_model_version``.

        Returns the basename of the adapter directory (e.g. ``"lora_v1"``)
        when extraction is enabled, otherwise ``"disabled"``.
        """
        if not self.enabled:
            return "disabled"
        return Path(self.adapter_path).name or self.adapter_path

    def extract(self, text: str, record_id: str) -> ExtractionResult:
        """Extract medications, adverse events, and their relation from ``text``.

        Never raises. On any failure path (extraction disabled, model load
        failure, OOM, JSON parse error, schema violation) returns an
        ``ExtractionResult`` whose ``validation`` flags are all False and
        ``error_reason`` explains the failure category.

        Args:
            text: Clinical text to analyze. Should be the ORIGINAL, unmasked
                text per D-35; offsets in the returned ``source_span`` fields
                are anchored to this string.
            record_id: Identifier (typically a chunk_id) to embed in the
                returned ExtractionResult.

        Returns:
            ExtractionResult, always.
        """
        if not self.enabled:
            return build_empty_result(record_id, reason="extraction_disabled")

        if not text or not text.strip():
            return build_empty_result(record_id, reason="empty_input")

        try:
            self._ensure_loaded()
        except Exception as exc:  # noqa: BLE001 — never propagate to caller
            logger.error("Extractor load failed: %s", exc, exc_info=True)
            return build_empty_result(record_id, reason="model_load_failed")

        try:
            raw = self._generate(text)
        except Exception as exc:  # noqa: BLE001 — never propagate to caller
            logger.error(
                "Extractor inference failed for record %s: %s", record_id, exc,
                exc_info=True,
            )
            return build_empty_result(record_id, reason="extraction_error")

        # validate_extraction never raises: it always returns an ExtractionResult.
        return validate_extraction(raw_text=raw, record_id=record_id, input_text=text)

    # ----------------------------------------------------------------- internal

    def _ensure_loaded(self) -> None:
        """Load base model + LoRA adapter on first use.

        Idempotent. Heavy imports (torch, transformers, peft) are deferred to
        this method so that ``import app.ingestion.extractor`` is cheap for
        callers that may never invoke .extract() (e.g. unit tests of other modules).
        """
        if self._model is not None and self._tokenizer is not None:
            return

        # Deferred imports — keep module import time low for non-extraction paths.
        import torch  # noqa: PLC0415
        from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: PLC0415
        from peft import PeftModel  # noqa: PLC0415

        logger.info(
            "Loading extractor: base=%s adapter=%s device=%s",
            self.base_model, self.adapter_path, self.device,
        )

        tokenizer = AutoTokenizer.from_pretrained(self.base_model)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        tokenizer.padding_side = "right"

        torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        device_map = self.device if self.device == "auto" else None

        base = AutoModelForCausalLM.from_pretrained(
            self.base_model,
            torch_dtype=torch_dtype,
            device_map=device_map,
        )
        base.config.use_cache = True

        model = PeftModel.from_pretrained(base, self.adapter_path)
        model.eval()

        self._model = model
        self._tokenizer = tokenizer
        logger.info("Extractor loaded.")

    def _generate(self, text: str) -> str:
        """Run a single greedy generation call. Returns raw decoded string.

        Decoding config matches the training-time inference plan locked in
        CLAUDE.md (do_sample=False, temperature=0.0, repetition_penalty=1.05).
        """
        import torch  # noqa: PLC0415 — deferred to keep import lightweight

        messages = [
            {"role": "user", "content": f"{INSTRUCTION}\n\nClinical text:\n{text}"}
        ]
        prompt = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self._tokenizer(prompt, return_tensors="pt").to(self._model.device)

        with torch.no_grad():
            output_ids = self._model.generate(
                **inputs,
                do_sample=False,
                max_new_tokens=self.max_new_tokens,
                repetition_penalty=1.05,
                pad_token_id=self._tokenizer.eos_token_id,
            )

        # Strip the prompt portion — only return the generated continuation.
        prompt_len = inputs.input_ids.shape[1]
        decoded = self._tokenizer.decode(
            output_ids[0][prompt_len:], skip_special_tokens=True
        )
        return decoded.strip()
