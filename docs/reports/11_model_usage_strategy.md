# Report 11 — Model Usage Strategy

**Project 3 deliverable** (PS §11, success criterion §13 "final demo shows how the
model is used in the Harmony workflow"). Documents *how* the fine-tuned LoRA
adapter plugs into Harmony, and why the team chose that integration mode over the
three alternatives the PS lists.

---

## 1. Decision

> **Use the fine-tuned model at ingestion time only.**
> Extract structured fields once when a document is uploaded, persist them to
> OpenSearch alongside the embedding, and serve all downstream queries (search,
> review, evidence highlighting) from the stored fields with **zero model calls
> at query time**.

This decision is locked in CLAUDE.md and implemented in
[`app/api/documents.py`](../../app/api/documents.py) +
[`app/ingestion/extractor.py`](../../app/ingestion/extractor.py).

---

## 2. The Four Options on the Table

The PS (§4.2) lists four usage patterns; we evaluated each against four axes —
latency budget, cost shape, quality variance, and Harmony workflow fit.

| Option | Model calls | Where it runs | What we evaluated |
|---|---|---|---|
| **A. Ingestion-time only** ✅ | Once per chunk on upload | `documents.py` ingest endpoint | **Chosen.** |
| B. Query-time only | Once per user query | Search endpoint | Considered, rejected. |
| C. Both ingestion + query-time | Twice | Both endpoints | Considered, rejected. |
| D. Coder/reviewer workflow | Once per reviewer action | Reviewer panel route | Considered, deferred to Phase 7 demo only. |

---

## 3. Why Ingestion-Time Wins

### 3.1 Latency budget

End-to-end LoRA inference latency on `lora_v1` (measured during Phase 5 eval,
`evaluation/reports/lora_v1.json`):

- p50: **2.08 s / chunk**
- p95: **21.97 s / chunk**

| Option | User-visible latency impact |
|---|---|
| **A. Ingestion-time** | 0 s at query time. Ingest endpoint already runs OCR, normalization, embedding (each multi-second); adding a 2 s/chunk extraction increases upload time by a fraction users do not perceive (uploads are async-style with progress indication). |
| B. Query-time | A typical query retrieves 5–20 chunks; running the model on each would add 10–40 s of model time per search. **Unacceptable** for an interactive search UI where users expect sub-second results. |
| C. Both | Doubles model compute for no quality gain — the ingestion-time extraction is the canonical artifact. |

Query-time inference is a non-starter at p95=22 s. Even at p50=2 s, a 10-result
SERP would add 20 s to every search.

### 3.2 Cost shape

- **Ingestion-time** amortizes the model call across all future searches of
  that document. A document searched 1,000 times still costs **1 extraction**.
- **Query-time** scales linearly with search volume. The same document searched
  1,000 times costs **1,000 extractions** (or 5,000–20,000 if you re-extract
  every retrieved chunk per query).
- Empirically: typical hospital records workflow has read-many-write-once
  access patterns. Ingestion-time is strictly cheaper above ~1.5
  searches-per-document.

### 3.3 Quality variance

- **Ingestion-time** produces one deterministic artifact per document (greedy
  decoding, `do_sample=False`). Re-search returns identical structured fields.
  Reviewers can audit a stable record.
- **Query-time** re-runs the model on a per-query basis. Even with greedy
  decoding, different chunking windows or prompt variations across query
  contexts could shift outputs. Harder to audit, harder to debug.

### 3.4 Workflow fit

The Harmony workflow already produces a per-chunk OpenSearch document at
ingest. Adding structured fields to that same document means **zero new
infrastructure**:

- Existing OpenSearch nested-field queries handle medication / ADE filtering.
- Existing chunk-level ACLs (role-based, see `_resolve_acl()` in
  `documents.py`) automatically cover the new structured fields — no separate
  access-control surface.
- Existing reindex flow (delete-and-replace by deterministic `chunk_id`) means
  re-extracting with a future adapter version is a one-command reingest.

Query-time integration would require a parallel service path, a hot model
process per API replica, GPU at the search tier, and a separate caching layer.
None of that exists in Harmony today.

---

## 4. What This Looks Like in the Index

Each chunk document in OpenSearch (see
[`app/ingestion/indexer.py`](../../app/ingestion/indexer.py) for the full
mapping) now carries four new fields:

```json
{
  "chunk_id": "…",
  "doc_id": "…",
  "text": "…",
  "embedding": [...],
  "phi_spans": "...",
  "acl": [...],

  "medications": [
    {"mention": "metformin", "dosage": "500 mg",
     "evidence": "started on metformin 500 mg BID",
     "start_char": 14, "end_char": 23}
  ],
  "adverse_events": [
    {"mention": "nausea", "linked_medication": "metformin",
     "evidence": "reports nausea after dose increase",
     "start_char": 46, "end_char": 52}
  ],
  "relations": [
    {"drug": "metformin", "adverse_event": "nausea",
     "status": "related",
     "evidence": "reports nausea after dose increase"}
  ],
  "extraction_model_version": "lora_v1"
}
```

The `extraction_model_version` field is the basename of the adapter directory.
When we cut a `lora_v2` adapter, reingested documents will carry the new
version, so search consumers can filter by extraction provenance.

---

## 5. How Each PS Usage Pattern Is Still Served (Without Query-Time Inference)

The PS table (§4.2) lists five workflows. We deliver all five from a single
ingestion-time extraction:

| PS workflow | Served by | Model call at this step? |
|---|---|---|
| Structured search ("medication=aspirin") | OpenSearch nested query on `medications.mention` | **No** |
| Compliance audit (which fields are model-generated) | Read `extraction_model_version` + `validation` flags from each chunk | **No** |
| Reviewer panel (structured review sheet) | Read `medications` / `adverse_events` arrays for a retrieved chunk | **No** |
| Search result explanation (why this doc matched) | Surface the `evidence` substring + `source_span` from matched entities | **No** |
| Query rewriting (natural language → structured filter) | Out of scope for v1. If needed in v2, see §6. | n/a |

Bonus item **P5** ("ingestion-time enrichment to OpenSearch with retrieval
improvement") is delivered by this same path; Phase 7's `demo/before_after.py`
demonstrates the retrieval-quality lift.

---

## 6. What Was Deferred to v2

The reviewer workflow option (D in §2) was considered but reduced in scope:

- The Phase 7 reviewer demo (`demo/reviewer.py`) reads stored fields and shows
  them — it does **not** re-run the model. This is enough for the demo
  deliverable.
- A *true* active-learning reviewer loop (PS bonus item P3) where reviewer
  corrections become new fine-tuning examples requires: a corrections
  database, a periodic retrain trigger, and adapter versioning per retrain.
  Deferred to a v2 phase.

Query-time clinical query rewriting (PS bonus item P4) is also deferred. It
would benefit from a separate, smaller fine-tune (the current 7B model is too
heavy for an interactive query path).

---

## 7. Failure Modes and Graceful Degradation

The extractor must never crash the ingestion pipeline (D-23). Any failure path
returns an `ExtractionResult` with all validation flags False and an
`error_reason` string. Downstream the chunk is still indexed with embeddings,
PHI spans, and text — just with empty `medications`, `adverse_events`,
`relations` arrays.

Categories of failure:

| `error_reason` | Cause | What's still searchable |
|---|---|---|
| `extraction_disabled` | `EXTRACTION_ENABLED=false` env var | Everything except structured fields |
| `empty_input` | Chunk text was blank | n/a (nothing to extract) |
| `model_load_failed` | Adapter directory missing, no GPU, bad config | Everything except structured fields |
| `extraction_error` | OOM or runtime exception inside `.generate()` | Everything except structured fields |
| `json_parse_failed` | Model output unparseable even after `json_repair` | Everything except structured fields |
| `schema_invalid` | Parseable JSON but missing required fields / bad enums | Everything except structured fields |

Unit tests (`tests/test_extractor.py`) exercise every category. None propagate
to the API layer.

---

## 8. Knobs the Operator Has at Runtime

Environment variables (read at first extractor call, see top of
[`extractor.py`](../../app/ingestion/extractor.py)):

| Variable | Default | Purpose |
|---|---|---|
| `EXTRACTION_ENABLED` | `"true"` | Master switch. Set to `"false"` to skip extraction entirely — useful during incident response or A/B comparison ingests. |
| `EXTRACTION_BASE_MODEL` | `"Qwen/Qwen2.5-7B-Instruct"` | Base model id (HF) or local path. |
| `EXTRACTION_ADAPTER_PATH` | `"models/adapters/lora_v1"` | LoRA adapter directory. Swap to roll out a new adapter — no code change needed. |
| `EXTRACTION_DEVICE` | `"auto"` | `"auto"` / `"cpu"` / `"cuda"`. Passed to `from_pretrained(device_map=…)`. |
| `EXTRACTION_MAX_NEW_TOKENS` | `"512"` | Generation length cap. Should match what the model was trained to produce. |

---

## 9. Where to Look for Evidence

- **Code:** [`app/ingestion/extractor.py`](../../app/ingestion/extractor.py) +
  [`app/api/documents.py`](../../app/api/documents.py) (search for `_get_extractor`)
- **Index mapping:** [`app/ingestion/indexer.py`](../../app/ingestion/indexer.py)
  (search for `medications`, `adverse_events`, `relations`)
- **Tests:** `pytest tests/test_extractor.py -v` (12 tests, all mocked, no GPU
  required, runs in <1 s)
- **Quality numbers backing this decision:**
  [`evaluation/reports/lora_v1.json`](../../evaluation/reports/lora_v1.json) —
  Drug F1 0.798, JSON validity 100%, latency p50 = 2.08 s.

---

## 10. Summary

Ingestion-time extraction wins on every axis we measured: zero added query
latency, lowest amortized cost, deterministic auditable artifacts, zero new
infrastructure required. Query-time integration was rejected primarily on
latency (p95 = 22 s/chunk is incompatible with interactive search).
Reviewer-workflow integration was reduced to a read-only demo (Phase 7) rather
than a re-extracting feedback loop; an active-learning loop is deferred to v2.
