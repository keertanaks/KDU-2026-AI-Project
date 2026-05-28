# Report 01 — Dataset Selection Report

**Project:** Project 3 — Harmony Clinical Structuring Fine-Tuning System  
**Phase:** 1 — Data Preparation  
**Status:** Complete (actual split counts in `data/processed/dataset_stats.json` after notebook run)

---

## 1. Dataset Selected

**`ade-benchmark-corpus/ade_corpus_v2`** — all three configs, loaded via HuggingFace `datasets`.

HuggingFace page: https://huggingface.co/datasets/ade-benchmark-corpus/ade_corpus_v2

No Data Use Agreement (DUA) required. Publicly available under academic use.  
Lead-approved by Kirti (confirmed via Slack/email thread, 2026). Alternative dataset n2c2 2018 was evaluated and rejected due to DUA registration timeline — documented below.

---

## 2. What Each Config Provides

| Config name | Rows (approx) | What it labels | Used for |
|---|---|---|---|
| `Ade_corpus_v2_classification` | ~23,500 | Binary: ADE present (1) / not present (0) per sentence | Negative training examples (label=0 → `entities=[], relation_status="not_related"`) |
| `Ade_corpus_v2_drug_ade_relation` | ~6,800 | Drug name + ADE name + character offsets for each | Positive training examples: `medication` + `adverse_event` entities with `source_span` |
| `Ade_corpus_v2_drug_dosage_relation` | ~280 | Drug name + dosage string + character offsets | Best-effort `dosage` field training (small, ~224 examples after 80% train split) |

All examples are **sentence-level** from PubMed case reports. Each `drug_ade_relation` row is one drug-ADE pair — a sentence with two drugs and one ADE produces two rows for the same sentence.

---

## 3. Why This Dataset Was Chosen

### 3.1 No DUA required
`ade_corpus_v2` is publicly accessible on HuggingFace with no registration or institutional approval needed. This removes a scheduling dependency that would have blocked the project.

### 3.2 Gold annotations with character offsets
Both `drug_ade_relation` and `drug_dosage_relation` configs include `start_char`/`end_char` indexes for each entity mention. This is exactly what the extraction schema requires (`source_span`). No approximate span matching needed — ground-truth character-level spans are available directly.

### 3.3 Three complementary configs cover the full schema
- Drug names and ADE names from `drug_ade_relation`
- Dosage information from `drug_dosage_relation`
- Negative examples (no ADE) from `classification` label=0

Combined, these supervise every field in the extraction schema except the fields that were explicitly out of scope (`assertion_status`, `certainty`, `medication_action`, `temporal_status` — see §5 below).

### 3.4 Scale and class diversity
~23,500 classification rows + ~6,800 ADE pairs + ~280 dosage examples gives a combined dataset large enough for LoRA fine-tuning on T4×2. The classification negative examples (label=0, ~16,000 rows) provide the negative class needed to teach the model when NOT to extract.

---

## 4. Alternative Datasets Considered

| Dataset | Reason rejected |
|---|---|
| **n2c2 2018 (NLP Clinical Challenges)** | Requires DUA registration through https://n2c2.dbmi.hms.harvard.edu/ — institutional approval timeline conflicts with project schedule. Would provide richer labels (assertion_status, temporal). Deferred to v2 if timeline allows. Lead-approved rejection. |
| **MedMentions** | Entity linking to UMLS, not drug/ADE extraction. Wrong task. |
| **BC5CDR** | Drug and disease NER with character spans — good candidate, but does not include drug-ADE relation labels or dosage. Less complete than ade_corpus_v2 for this schema. |
| **GPT-4 silver labeling on n2c2** | Considered for filling missing fields (assertion_status etc.) but rejected: synthetic labels introduce noise that propagates into training. Lead declined this approach. |

---

## 5. Known Limitations

### 5.1 Dosage field is best-effort
Only ~280 rows in `drug_dosage_relation`. After 80% train split, ~224 training examples for dosage. The model may learn to extract dosage only for common formats seen in those 224 examples. Evaluation target for dosage (EVAL-05c) is lowered to ≥ 0.40 to reflect this.

### 5.2 PubMed case-report style, not clinical-note style
All sentences come from PubMed case reports. Clinical notes use abbreviations ("Pt c/o N/V x2d"), structured sections (Assessment/Plan), and informal language not present in the training data. Mitigation: 60 hand-crafted clinical-note style OOD examples in `evaluation/synthetic_ade_eval.jsonl` (Phase 5) test generalization to this style.

### 5.3 Schema narrower than PS example
The project specification example schema included `assertion_status`, `certainty`, `medication_action`, and `temporal_status`. None of these are labeled in `ade_corpus_v2`. Training on these fields without supervision would require silver labeling (rejected above). These fields are explicitly out of scope for v1. Lead-approved.

### 5.4 Sentence-level examples only
Each example is one sentence. Harmony's chunker (`app/ingestion/chunker.py`) splits documents into short chunks. At inference time, the model sees one chunk at a time — consistent with sentence-level training conditions.

### 5.5 Duplicate sentences across rows
One sentence can produce multiple rows in `drug_ade_relation` (one per drug-ADE pair). A naive row-level split would place duplicate sentences in both train and test — constituting data leakage. This is mitigated by the text-hash grouping strategy (§6 below).

---

## 6. Split Strategy

### 6.1 Rationale for 80/10/10

A three-way split is required to allow honest hyperparameter selection:
- **train**: model parameters are updated on this set
- **val**: used to select best hyperparameters (LR, LoRA rank) across 7 sweep runs
- **test**: touched only once at the end for final metric reporting. Never used during training or hyperparameter selection.

Using only train/test (80/20) would conflate validation loss (used to stop early) with test loss (used to report final numbers) — making reported metrics optimistically biased.

### 6.2 Text-hash grouping (leakage prevention)

Each row is assigned `text_hash = md5(normalized_text)`. The split is made at the **text_hash level**, not the row level:

1. For each unique text_hash, a primary relation label is assigned (most informative of all rows sharing that hash: `related` > `not_related` > `none`).
2. `StratifiedShuffleSplit` is applied to the unique text_hashes with these primary labels.
3. All rows sharing a text_hash are assigned to the same split.

This guarantees: if a sentence appears in both `drug_ade_relation` and `drug_dosage_relation`, both rows land in the same fold — preventing the model from memorizing a sentence from the train set that also appears in test.

### 6.3 Stratification

Stratification is by `relation_label` (related / not_related / none) to preserve class balance across splits. Without stratification, random assignment could concentrate all dosage examples in train and leave none for evaluation.

### 6.4 Actual split sizes

*Populated after running `notebooks/p3_01_data_prep.ipynb`. See `data/processed/dataset_stats.json`.*

| Split | Rows | % of total | Unique text hashes |
|---|---|---|---|
| train | FILL_AFTER_RUN | ~80% | FILL_AFTER_RUN |
| val   | FILL_AFTER_RUN | ~10% | FILL_AFTER_RUN |
| test  | FILL_AFTER_RUN | ~10% | FILL_AFTER_RUN |

---

## 7. Output Files

| File | Description |
|---|---|
| `data/processed/train.jsonl` | Training split, chat-format JSONL |
| `data/processed/val.jsonl` | Validation split, chat-format JSONL |
| `data/processed/test.jsonl` | Test split, chat-format JSONL — do not inspect until final evaluation |
| `data/processed/dataset_stats.json` | EDA numbers: text length, class balance, split sizes |
| `notebooks/p3_01_data_prep.ipynb` | Reproducible notebook to regenerate all files with `seed=42` |

---

## 8. Chat Format

Each JSONL line is:
```json
{
  "messages": [
    {"role": "user",      "content": "<INSTRUCTION>\n\nClinical text:\n<TEXT>"},
    {"role": "assistant", "content": "{\"schema_version\": \"v1\", \"entities\": [...], \"relation_status\": \"...\"}"}
  ],
  "text_hash": "<md5>",
  "source_config": "drug_ade_relation | drug_dosage_relation | classification_negative"
}
```

The assistant content is the model's target output. It contains **only** `schema_version`, `entities[]`, and `relation_status`. It does **not** contain `record_id` or `validation` — those are system-injected by `app/ingestion/validator.py` at inference time (Design Doc D-35).

Full format specification is in `docs/reports/04_data_format_specification.md` (Phase 5).

---

## 9. Fallback Plan

If `ade-benchmark-corpus/ade_corpus_v2` becomes unavailable on HuggingFace:

1. **BC5CDR** (`tner/bc5cdr`) — drug/disease NER with character spans. Missing dosage and relation labels but can supply entity extraction training examples. Schema would be reduced to entity-only.
2. **MedDRA subset** — if institutional access is arranged, provides ADE vocabulary that could supplement weak supervision.
3. **Re-approach n2c2 2018** — if DUA can be obtained, provides the richest annotation set including assertion_status and temporal fields.

For v1, no fallback is needed — `ade_corpus_v2` is accessible and has been confirmed downloaded successfully.
