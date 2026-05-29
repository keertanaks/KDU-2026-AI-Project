# Data Format Specification

**Project:** Harmony Clinical Structuring — Project 3  
**Phase:** Phase 1 (Data Preparation)  
**Status:** Final  

---

## Overview

Training examples for the Qwen2.5-7B-Instruct fine-tune are stored in `data/processed/` as newline-delimited JSON (JSONL). Each file (`train.jsonl`, `val.jsonl`, `test.jsonl`) contains one record per line. The format follows the OpenAI chat messages convention, which is natively supported by Hugging Face `trl`'s `SFTTrainer` and `DataCollatorForCompletionOnlyLM`.

---

## Chat Format

Each record has this top-level structure:

```json
{
  "messages": [
    {"role": "user", "content": "<instruction + clinical text>"},
    {"role": "assistant", "content": "<JSON output>"}
  ],
  "text_hash": "<md5 of original text>",
  "source_config": "<ade_corpus_v2 config name>"
}
```

### User Turn Template

The user turn is constructed from the following template (verbatim):

```
You are a clinical information extractor. Given a clinical text, extract all
medications and adverse events as a JSON object that follows the schema below.
Return ONLY valid JSON. If no entity is present, return entities=[] and
relation_status="none".

Return ONLY this JSON structure (no record_id, no validation block — those are added by the system):
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

Clinical text:
<raw clinical sentence>
```

The clinical text appears after the `Clinical text:\n` sentinel, making it trivially extractable with `user_content.split("Clinical text:\n", 1)[1].strip()`.

### Assistant Turn

The assistant turn is a compact JSON string with three fields only: `schema_version`, `entities`, and `relation_status`. System-injected fields (`record_id`, `validation`, `error_reason`) are never present in training targets.

---

## Example Records

### Example 1 — Positive (drug + ADE)

```json
{
  "messages": [
    {
      "role": "user",
      "content": "You are a clinical information extractor...\n\nClinical text:\nIntravenous azithromycin-induced ototoxicity."
    },
    {
      "role": "assistant",
      "content": "{\"schema_version\": \"v1\", \"entities\": [{\"entity_type\": \"medication\", \"mention\": \"azithromycin\", \"dosage\": null, \"linked_medication\": null, \"evidence\": \"Intravenous azithromycin-induced ototoxicity.\", \"source_span\": {\"start_char\": 12, \"end_char\": 24}}, {\"entity_type\": \"adverse_event\", \"mention\": \"ototoxicity\", \"dosage\": null, \"linked_medication\": \"azithromycin\", \"evidence\": \"Intravenous azithromycin-induced ototoxicity.\", \"source_span\": {\"start_char\": 33, \"end_char\": 44}}], \"relation_status\": \"related\"}"
    }
  ],
  "text_hash": "8f5bb3316bf3f969add12d93c2266445",
  "source_config": "drug_ade_relation"
}
```

### Example 2 — Negative (drug only, no ADE)

```json
{
  "messages": [
    {
      "role": "user",
      "content": "You are a clinical information extractor...\n\nClinical text:\nPatient was treated with metformin for type 2 diabetes."
    },
    {
      "role": "assistant",
      "content": "{\"schema_version\": \"v1\", \"entities\": [{\"entity_type\": \"medication\", \"mention\": \"metformin\", \"dosage\": null, \"linked_medication\": null, \"evidence\": \"Patient was treated with metformin for type 2 diabetes.\", \"source_span\": {\"start_char\": 24, \"end_char\": 33}}], \"relation_status\": \"not_related\"}"
    }
  ],
  "text_hash": "a7c3e2f1...",
  "source_config": "drug_ade_relation"
}
```

---

## Why Chat Format?

Three alternatives were considered:

1. **Raw instruction format** (`"<|im_start|>user\n...<|im_end|>\n<|im_start|>assistant\n{json}"`) — requires manual template management per model family. The `apply_chat_template` call handles this automatically.

2. **Token-label format** (token IDs with -100 masks pre-computed) — tightly coupled to a fixed tokenizer version; breaks if the base model is swapped or the tokenizer is updated.

3. **Chat messages format** (chosen) — model-family agnostic, handled end-to-end by `tokenizer.apply_chat_template`. `SFTTrainer` accepts the `messages` key directly when `dataset_text_field` is omitted and the dataset has the messages structure.

Chat format also makes the eval pipeline straightforward: `tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)` reconstructs the exact inference prompt from a test record without any template duplication.

---

## Loss Masking via DataCollatorForCompletionOnlyLM

`DataCollatorForCompletionOnlyLM` is used to mask the user turn from the loss computation. Only tokens in the assistant response contribute to training loss. The `response_template` parameter identifies the start of the assistant turn:

```python
response_template = "<|im_start|>assistant\n"
```

For Qwen2.5 chat format, the assistant turn always begins with this exact byte sequence after `apply_chat_template`. The collator scans each tokenized sequence for the template token IDs and sets all preceding positions to `-100`, which PyTorch's cross-entropy loss ignores. This prevents the model from being penalized for not reproducing the instruction, and ensures all gradient signal comes from the JSON output.

---

## Split Grouping

The 80/10/10 split groups by `md5(text) % 10`:

- Groups 0–7: train
- Group 8: validation
- Group 9: test

Grouping by text hash (not row index) ensures that duplicate or near-duplicate sentences across `ade_corpus_v2`'s three configs land in the same split, preventing cross-split data leakage.
