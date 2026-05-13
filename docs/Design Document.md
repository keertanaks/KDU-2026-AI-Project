# Design Document

# Semantic Search for Healthcare Records

**Project**  
Semantic Search for Healthcare Records (Customer-Replica of Harmony)

**Type**  
Lightweight Production Design Document

**Version**  
5.0 · Draft for Implementation

**Scope**  
~1000 synthetic medical records · RAG (no GraphRAG) · HIPAA-aware

---

## 1. System Architecture

A HIPAA-aware RAG (Retrieval-Augmented Generation) system that lets clinicians search across mixed-format medical records — typed PDFs, scanned PDFs, and free-text notes — using natural language. The system performs hybrid retrieval (vector + keyword) with cross-encoder reranking, masks PII based on the caller’s role, and writes an immutable audit log for every access.

The architecture is split into two independent pipelines — an Ingestion Pipeline (synchronous, runs when documents arrive, ~45 seconds per document) and a Search Pipeline (real-time, runs on each user query) — sharing a common vector store (OpenSearch, local Docker), an authentication layer, and an audit log. Splitting them lets each side scale independently: ingestion is bursty and CPU-heavy, while search must stay low-latency.

**Figure 1. End-to-end system architecture.**

### Data Flow

**Upload** — A clinician (treating or non-treating) uploads a PDF or text file via the React frontend; FastAPI receives the file, validates it, stores it in S3 (SSE-KMS), and processes it synchronously. Patients do not use this system directly — this is a clinician-facing search tool.

**Classify & OCR** — The document is classified using heuristics (no CNN): typed PDFs go through PyMuPDF text extraction (99%+ accuracy); scanned PDFs go through Tesseract OCR with full preprocessing (92–95%); handwritten PDFs go through PaddleOCR (PP-OCRv5) with full preprocessing (85–90%). Preprocessing pipeline (applied to scanned + handwritten): render at 300 DPI, crop bounding box, grayscale, CLAHE contrast enhancement, sharpen, safe deskew, optional form-line removal — adds +10–15% accuracy at 3–5 sec/page.

**Clean, Chunk & Tag PII** — Text is normalized then chunked using adaptive document-type-aware chunking: prescriptions (short < 300 tokens) kept as atomic chunks, lab reports and tables have rows serialized as independent chunks via PyMuPDF find_tables(), long clinical notes use parent-child with LangChain RecursiveCharacterTextSplitter, forms keep key-value groups together. Fallback: Iterative Builder (Claude 3.5 Haiku, $20–30/1000 docs) triggered if RAGAS Context Precision < 90%. PHI/PII tagged using Microsoft Presidio; phi_spans stored as metadata only — never written to the audit log.

**Embed & Index** — Each chunk is embedded with OpenAI text-embedding-3-small; the vector, raw text, and metadata (doc_id, patient_id, date, doc_type, PHI tags, ACL) are written as a single OpenSearch document. Source PDFs are stored in S3 with KMS encryption.

**Query** — A doctor submits a natural-language query through the UI; FastAPI authenticates the user and resolves role + document ACL.

**Retrieve (Hybrid)** — The query is normalized, embedded, and run against OpenSearch as a hybrid search (BM25 + HNSW kNN), pre-filtered by the user’s document ACL.

**Rerank** — The top-K candidates from hybrid retrieval are reranked by a cross-encoder (BGE-reranker-base) to produce the final top-N.

**Mask & Respond** — The Response Masker applies role-based masking using each chunk’s stored PHI spans; masked snippets and source citations are returned to the UI.

**Audit** — A query_hash (SHA-256), user identity, document IDs touched, role, masking applied, and timestamp are written to an append-only Postgres audit log. Raw query text and document content are never stored — PHI must not appear in the audit log.

**Observe** — Every retrieval call (query, retrieved chunks, rerank scores, final response, latency) is traced into LangSmith for evaluation and debugging.

---

## 2. Tech Stack

| Layer | Technology / Tool | Purpose | Why Chosen |
|---|---|---|---|
| Frontend | React + Vite + Tailwind | Search UI, results display, audit dashboard | Decouples UI from backend; supports per-role views and richer UX than Streamlit. |
| Backend / API | FastAPI (Python 3.11) | REST API, auth, orchestration | Async, strong Pydantic typing, native fit with the Python ML/RAG stack. |
| RAG Framework | LangChain + LangGraph | Pipeline orchestration, splitters, retrievers | Pre-built splitters and hybrid-retriever abstractions; LangGraph gives explicit state for the multi-step search flow. |
| Vector Store | OpenSearch (k-NN plugin) — local Docker container | Hybrid search (BM25 + HNSW) + metadata filtering | Single record holds vector + text + metadata, so pre-filtering and vector search happen in one query — no cross-system joins. |
| Embeddings | OpenAI text-embedding-3-small (1536-d) | Chunk + query embeddings | Strong general-domain quality; cheap; no GPU dependency at this scale. |
| Reranker | BGE-reranker-base (cross-encoder) | Re-score top-K from hybrid retrieval | Cross-encoder accuracy on a small candidate set; runs locally with no per-query API cost. |
| OCR (typed) | PyMuPDF (fitz) | Extract text from typed PDFs | Native PDF text layer is faster and more accurate than OCR when text is already embedded. |
| OCR (scanned/handwritten) | Tesseract 5 (scanned) + PaddleOCR PP-OCRv5 (handwritten) | Extract text from images and scans | Free, runs on-prem (HIPAA-friendly), good enough at intern scale; AWS Textract rejected on cost and data-egress. |
| Document Classifier | Heuristics only (no CNN): text-layer probe + contrast/edge/density checks | Route: text-layer vs. OCR; typed vs. handwritten | Heuristics handle 100% of cases at zero cost and zero ML overhead: PyMuPDF text-layer probe identifies TYPED docs (99%+); contrast + edge + density checks distinguish SCANNED from HANDWRITTEN (85–90%). No CNN training, no GPU, no maintenance. |
| PII / PHI Detection | Microsoft Presidio | Detect 18 HIPAA identifiers | Open-source, extensible with custom medical recognizers, runs on-prem (no PHI leaves the trust boundary). |
| Object Storage | AWS S3 (SSE-KMS) | Source PDF storage | Encryption at rest with KMS-managed keys; HIPAA-eligible service. |
| Encryption | AWS KMS | Key management for S3 + audit log | Centralized key rotation; auditable key usage via CloudTrail. |
| Audit Log | PostgreSQL (append-only table) | Immutable access log | Relational queries needed for the admin audit view; append-only enforced at DB role level. |
| Auth | Session-based auth (fastapi-sessions) | User identity, role claims | Standard, integrates with FastAPI middleware for per-request role checks. |
| Observability | LangSmith | RAG tracing, dataset management | Native LangChain integration; captures full prompt/retrieval traces. |
| Evaluation | RAGAS + LangSmith datasets | Retrieval and answer quality metrics | RAGAS provides standard RAG metrics; LangSmith hosts the golden eval datasets. |
| Queue / Workflow | Synchronous ingestion (no queue) | Ingestion job orchestration | Lightweight at this scale; full Temporal is overkill for ~1000 docs. |

---

## 3. Verification Pipeline — Step by Step

This section walks the end-to-end pipeline. Each step covers its purpose, a concrete example, and the key design decisions taken — with the alternatives considered and the rationale for the choice.

### Step 1: Document Upload & Classification

**Purpose:** Accept a file, decide whether it has an extractable text layer or needs OCR, and route accordingly. Misrouting here cascades into garbage downstream.

**Example:**

Input: discharge_summary_4421.pdf — text-layer probe returns 4,800 chars of clean text → classified typed-PDF, routed to PyMuPDF.

Input: handwritten_rx_18.pdf — probe returns 0 chars; heuristics score low contrast + complex edges → classified HANDWRITTEN, routed to PaddleOCR with full preprocessing pipeline.

**Key Design Decisions:**

**Decision:** Three-way heuristic classifier: PyMuPDF text-layer probe (TYPED); contrast + edge complexity + text density checks (SCANNED vs. HANDWRITTEN). No CNN, no ML training, no GPU.

**Options Considered:** (a) Always-OCR everything, (b) Always trust the PDF text layer, (c) Heuristic probe + CNN fallback, (d) Pure heuristics (contrast + edges + density).

**Why This Decision:** Always-OCR wastes compute and degrades quality on typed PDFs. Always trusting the text layer fails on scanned PDFs with empty/garbage layers. CNN fallback requires weeks of setup, GPU infrastructure ($2000+), labeled training data, and ongoing retraining — unacceptable overhead for 85–90% accuracy that heuristics already match. Pure heuristics (contrast std-dev, edge complexity via Canny, text density ratio) deliver equivalent classification at zero cost, zero maintenance, and ~50 lines of Python.

**Decision:** Smart OCR routing: PyMuPDF for TYPED (99%+), Tesseract 5 + preprocessing for SCANNED (92–95%), PaddleOCR PP-OCRv5 + preprocessing for HANDWRITTEN (85–90%).

**Options Considered:** Tesseract 5, AWS Textract, PaddleOCR, EasyOCR — evaluated per document type (typed, scanned, handwritten).

**Why This Decision:** Textract rejected on cost and PHI data-egress. PyMuPDF is 99%+ on typed — no OCR needed. Tesseract handles clean scans well (92–95% with preprocessing). PaddleOCR (PP-OCRv5) chosen over EasyOCR for handwritten: 90–92% vs. 85–88% accuracy, 13% improvement in v5, faster init (1–2s vs. 3–5s), layout analysis included, better for medical documents. All scanned + handwritten docs pass through the preprocessing pipeline first: render at 300 DPI → crop bounding box → grayscale → CLAHE contrast enhancement → sharpen → safe deskew (only if >5°) → optional form-line removal. This adds +10–15% accuracy at 3–5 seconds/page, ~80 lines of code, $0 cost.

### Step 2: Text Extraction & Cleaning

**Purpose:** Produce clean, normalized text from whatever the classifier routed in. OCR output is noisy and must be normalized before chunking.

**Example:**

OCR raw: "Pt was prescr ibed parace tamol 65O mg BD"

After cleaning: "Pt was prescribed paracetamol 650 mg BD"

After medical normalization: drug = paracetamol, dose = 650 mg, frequency = BD retained as a structured tag.

**Key Design Decisions:**

**Decision:** Apply a domain-aware deterministic cleaner before chunking; do not rewrite content.

**Options Considered:** (a) Pass raw OCR straight to chunker, (b) LLM-based rewriter, (c) Deterministic rule-based cleaner.

**Why This Decision:** Raw OCR poisons embedding quality — “65O” and “650” embed to different vectors. An LLM rewriter is powerful but introduces hallucination risk and is unauditable, which is unacceptable for medical text. Deterministic cleaning is auditable, reversible, and good enough for the noise patterns Tesseract and PaddleOCR actually produce.

### Step 3: Semantic Chunking

**Purpose:** Split each document into chunks small enough to embed well but large enough to retain clinical context (e.g., a full prescription line should not be split across chunks).

**Example:**

Input: a 6-page discharge summary.

Output: ~22 chunks of 400–600 tokens each, with section headers preserved (Diagnosis, Medications, Plan) and a 75-token overlap between adjacent chunks within the same section.

**Key Design Decisions:**

**Decision:** Adaptive document-type-aware chunking as primary strategy. Four policies matched to document structure: (1) SHORT / PRESCRIPTION (<300 tokens) — kept as single atomic chunk, preserving drug-dose-instruction relationships. (2) TABLE / LAB REPORT — PyMuPDF find_tables() reconstructs rows for typed PDFs; each row serialized as one chunk: "HbA1c: 8.2% (Normal: 4.0–5.6%) — FLAG: HIGH". PaddleOCR layout analysis for scanned tables; AWS Textract fallback if structure garbled. (3) LONG PROSE / CLINICAL NOTE (>300 tokens) — parent-child with LangChain RecursiveCharacterTextSplitter. Parent = page or section level context. Child = 512 tokens, 50-token overlap. Retrieve child, return parent context to LLM. (4) FORM — key-value field groups kept together. Fallback: Iterative Builder (Claude 3.5 Haiku via Cloud API, 94% semantic correctness, $20–30/1000 docs) triggered when RAGAS Context Precision < 90%.

**Options Considered:** Fixed-size chunking, recursive splitter with custom separators, semantic (similarity-based) chunking, agentic / LLM chunking.

**Why This Decision:** Section-parent-aware chunking (ADR-005) assumes every document has clean section headings — not true for prescriptions (no headings), lab reports (tables), or forms (key-value structure). Adaptive chunking applies the correct policy per document type. Prescriptions kept atomic preserve clinical unit integrity. Lab report rows reconstructed ensure test-result-normal-flag relationships stay together (essential for retrieval). Long clinical notes use RecursiveCharacterTextSplitter (good for prose, wrong for structured data). Cost is $0, deterministic, and each policy is independently testable and explainable. Iterative Builder retained as data-driven fallback: if RAGAS Context Precision < 90%, system switches to LLM-based chunking (94% semantic correctness, $20–30/1000 docs).

**Decision:** Document type detected at classification stage (short + drug names = prescription, table structure = lab report, key-value patterns = form, long prose = clinical note). Chunking policy selector routes to appropriate handler. PyMuPDF find_tables() used for typed PDFs; PaddleOCR layout analysis for scanned tables. RecursiveCharacterTextSplitter applied only to long clinical notes where it is appropriate. No LangChain splitter or custom class needed — each handler is simple and focused.

**Options Considered:** Fixed chunking, recursive splitter only, section-aware chunking, section-parent-aware (ADR-005), adaptive document-type-aware, Iterative Builder via Claude API, LangChain built-ins, Unstructured.io.

**Why This Decision:** Adaptive chunking is correct per document type — section-parent-aware requires section headings that don't exist in prescriptions or lab reports. RecursiveCharacterTextSplitter applied only where it fits (long prose). PyMuPDF find_tables() is purpose-built and free. Cost is $0. Each policy is independently testable, explainable, and auditable. Iterative Builder kept as a measurable, triggered fallback — not a default — to avoid unnecessary API cost on well-structured documents where deterministic chunking succeeds.

### Step 4: PII / PHI Tagging (Detection, not Removal)

**Purpose:** Find all HIPAA-defined identifiers in each chunk and store them as metadata. Critically, PII is detected at ingest, but masking happens at query time based on caller role — this keeps a single source of truth.

**Example:**

Chunk text: "John Smith (MRN 11223344) was admitted on 2025-03-12 for chest pain."

Metadata: phi_spans = [{type: NAME, start: 0, end: 10}, {type: MRN, start: 16, end: 24}, {type: DATE, start: 41, end: 51}]

Raw text stays intact in the index; masking is applied at response time per role.

**Key Design Decisions:**

**Decision:** Microsoft Presidio with custom medical recognizers (MRN, NPI patterns).

**Options Considered:** Presidio, AWS Comprehend Medical, custom regex + spaCy NER.

**Why This Decision:** Presidio is purpose-built for the 18 HIPAA identifiers, open-source (runs on-prem), and extensible with custom recognizers. AWS Comprehend Medical is more accurate on medical-specific PHI but sends data out of our trust boundary on every call — exactly what we are trying to avoid. Custom regex + spaCy is reinventing what Presidio already does, with worse maintenance.

**Decision:** Detect-once-at-ingest, mask-at-query — do not store a masked copy.

**Options Considered:** (a) Store raw + masked copies, (b) Store only masked, (c) Store raw with PHI offsets and mask at response time.

**Why This Decision:** Storing both copies doubles storage and creates a sync problem (the two copies will drift). Storing only masked means a treating clinician can never see the unmasked record they are legally entitled to. Storing raw with offsets keeps one source of truth, and the masking algorithm becomes the only thing that varies per role — which is exactly the role-based masking model we want.

### Step 5: Embedding & Indexing

**Purpose:** Convert each chunk to a vector and write the chunk + vector + metadata into OpenSearch as a single document, ready for hybrid retrieval.

**Example:**

OpenSearch document fields: doc_id, patient_id, chunk_id, text, embedding (1536-d), doc_type, date, phi_spans, acl.

**Key Design Decisions:**

**Decision:** OpenAI text-embedding-3-small (1536-d).

**Options Considered:** OpenAI text-embedding-3-small (1536), text-embedding-3-large (3072), open-source medical embeddings (BioBERT / MedCPT, ~768).

**Why This Decision:** A domain-tuned medical embedding is theoretically better, but open-source options at this scale come with deployment overhead (GPU, model serving) we do not need. text-embedding-3-small gives strong general-domain quality ($0.30 / 1000 docs), is cheap enough to re-embed the entire corpus on iteration, and has no GPU dependency. text-embedding-3-large doubles cost for a modest quality bump not yet justified by metrics. ClinicalBERT (91–95% quality, domain-tuned) is retained as a data-driven upgrade: if RAGAS shows Context Recall < 85% and embeddings are confirmed as the bottleneck, switch to ClinicalBERT. Medical embeddings otherwise stay on the table if the eval set shows a quality ceiling.

**Decision:** Co-locate vector + text + metadata in a single OpenSearch document.

**Options Considered:** (a) Vector store + separate metadata DB, (b) Co-located in OpenSearch.

**Why This Decision:** Separating vectors and metadata forces a cross-system join on every query, which adds latency and a consistency failure mode. Co-locating means a single OpenSearch query can pre-filter by metadata (doc_type, date, ACL) and then run vector search on the surviving subset — fewer hops, lower latency, simpler ops.

**Decision:** HNSW for the vector index.

**Options Considered:** HNSW, IVF, flat.

**Why This Decision:** Flat is exact but does not scale. IVF is faster to build but has worse recall at this scale. HNSW is the standard for sub-second kNN at our document counts and is what OpenSearch’s k-NN plugin optimizes for.

### Step 6: Query Processing & Hybrid Retrieval

**Purpose:** Take a natural-language query, run it against the index using both lexical and semantic signals in parallel, and return a ranked candidate set.

**Example:**

Query: "patients with cardiac issues treated in Q1 2025"

After NER + normalization: entities = {condition: cardiac, date_range: 2025-01-01..2025-03-31}

Pre-filter applied to OpenSearch: date ∈ Q1 2025 AND user_acl_match = true

Hybrid retrieval: top-50 by BM25 ∪ top-50 by HNSW kNN, deduped → ~75 candidates.

**Key Design Decisions:**

**Decision:** Hybrid retrieval (BM25 + kNN) combined via Reciprocal Rank Fusion (RRF).

**Options Considered:** Vector-only, BM25-only, vector + BM25 with score normalization, vector + BM25 with RRF.

**Why This Decision:** Vector-only misses exact identifiers (drug names, MRNs, ICD codes) where lexical match is the right signal. BM25-only misses semantic intent ("blood thinner" ≠ "warfarin" lexically). Score normalization is sensitive to outliers and can zero out legitimately relevant chunks. RRF ranks by position across the two retrievers, so a chunk strong in both lists rises naturally regardless of absolute score scales — best fit for a system where we want correctness over fragile tuning.

**Decision:** Apply metadata pre-filter (date, doc_type, ACL) before kNN.

**Options Considered:** Pre-filter, post-filter.

**Why This Decision:** Post-filtering throws away results after the expensive vector search — you can lose all your top results to an ACL check and end up with zero hits. Pre-filtering narrows the search space first, so kNN runs over only the legally accessible subset, which is both faster and correct-by-construction.

### Step 7: Reranking

**Purpose:** Re-score the candidate set with a more expensive but more accurate model, so the final top-N shown to the user is genuinely the most relevant.

**Example:**

Input: ~75 candidates from Step 6.

Cross-encoder scores each (query, chunk) pair → reorders → top-5 returned.

Net effect: a chunk that was rank 18 in hybrid retrieval but is a clear semantic match jumps to rank 1.

**Key Design Decisions:**

**Decision:** Cross-encoder reranker (BGE-reranker-base) on top-K from hybrid retrieval.

**Options Considered:** No reranking, RRF-only, cross-encoder reranking, LLM-as-reranker.

**Why This Decision:** No reranking leaves the final ranking at the mercy of two retrievers, neither of which jointly scores the (query, chunk) pair. RRF already handles fusion but does not actually score relevance — only position. LLM-as-reranker is more accurate again but slow (per-pair API call) and expensive. A bi-encoder gave us the candidates fast; a cross-encoder now scores those candidates with full cross-attention — best accuracy/latency trade-off.

**Decision:** Use both bi-encoder (retrieval) and cross-encoder (reranking) — not one or the other.

**Options Considered:** Bi-encoder only, cross-encoder only, both.

**Why This Decision:** Cross-encoder-only is infeasible — scoring the query against every chunk on each request is O(N) per query. Bi-encoder-only is fast but loses accuracy because it embeds query and chunk independently, with no cross-attention. The standard pattern — bi-encoder narrows from N to K (fast), cross-encoder re-scores K (accurate) — gives both properties.

### Step 8: PII Masking & Response Assembly

**Purpose:** Apply role-based masking to the final response and return cited snippets to the user.

**Example:**

User role: non_treating_admin

Raw snippet: "John Smith (MRN 11223344) was admitted on 2025-03-12 for chest pain."

Masked response: "<NAME> (MRN <REDACTED>) was admitted on <DATE> for chest pain."

A treating physician on the same record sees the unmasked text.

**Key Design Decisions:**

**Decision:** Role-based masking applied at response time using PHI spans stored in metadata.

**Options Considered:** Store masked copies per role, mask at response time using offsets, encrypt PHI fields and decrypt by role.

**Why This Decision:** Per-role copies multiply storage and cause sync drift. Field-level encryption per identifier is the most secure but adds significant complexity at this scope. Response-time masking using pre-computed offsets is fast (no re-detection on every query), keeps a single source of truth, and the only thing that varies per role is which span types get masked — exactly the model that maps to HIPAA’s minimum-necessary principle.

**Decision:** Default mask policy: treating_clinician sees all; non_treating_clinician sees all except direct identifiers (NAME, MRN, ADDRESS, PHONE); admin/auditor sees fully redacted text + metadata.

**Options Considered:** Binary masked/unmasked, granular per-identifier rules.

**Why This Decision:** Binary policies are easy but blunt — auditors need to see that a record matched a query without seeing who. Granular per-identifier rules mapped to role match the actual HIPAA minimum-necessary principle and align with how clinical access actually works in practice.

### Step 9: Audit Logging

**Purpose:** Record every access — who, what, when — into an immutable log that satisfies HIPAA’s access-tracking requirement and supports the admin audit user story.

**Example:**

Per-query log row: audit_id, user_id, role, timestamp, query_hash (SHA-256 of query text — raw query never stored, PHI must not appear in audit log), document_ids_returned (IDs only, no content), masking_applied, result_count, latency_ms. PHI is never written to the audit log under any role or condition.

**Key Design Decisions:**

**Decision:** PostgreSQL append-only audit table with row-level immutability (no UPDATE/DELETE grants for the app role).

**Options Considered:** App-level append-only convention, append-only DB table with role grants, DynamoDB stream, dedicated audit service.

**Why This Decision:** App-level conventions are violated by any future bug or migration. Enforcing append-only at the database role level makes it physically impossible for the app to mutate or delete log rows, which is what HIPAA-style auditability actually requires. DynamoDB streams work but add a service for marginal benefit at this scale; Postgres is already in the stack for users/roles.

### Step 10: Observability & Evaluation

**Purpose:** Continuously measure retrieval quality and answer faithfulness so the system can be tuned and regressions caught.

**Example:**

Golden eval set of 50 query → expected-doc pairs hosted in LangSmith.

Nightly job runs the full pipeline against the set; reports top-3 hit rate, context precision, context recall, faithfulness.

Any drop > 5% on top-3 hit rate from baseline blocks the next deploy.

**Key Design Decisions:**

**Decision:** RAGAS for RAG-specific metrics; LangSmith for trace capture and dataset hosting.

**Options Considered:** RAGAS only, TruLens, manual labeling, LangSmith built-in evaluators, RAGAS + LangSmith.

**Why This Decision:** RAGAS gives the four metrics that actually map to this problem (context precision, context recall, faithfulness, answer relevancy), so we do not have to invent our own. LangSmith already captures full traces and hosts the eval dataset, so plugging RAGAS into LangSmith means evals run on real production traces, not a synthetic test harness. TruLens overlaps with RAGAS without unique value here. Manual labeling is a backstop for the small golden set.

---

## 4. Core Components

### 4.1 Ingestion Components

#### Document Receiver

**Responsibility:** Accept uploaded PDFs/text files from the API, validate type/size, process synchronously (45 sec/doc), store in S3.

**Input:** Multipart upload from FastAPI endpoint; auth context.

**Output:** S3 object URL + document_id + chunks_created count.

**Notes:** Files written to S3 with SSE-KMS; raw file never lives on the API host.

#### Document Classifier

**Responsibility:** Decide route: text-layer extract vs. OCR; typed vs. handwritten.

**Input:** S3 object URL.

**Output:** Routing decision {strategy: text_layer | tesseract_ocr, doc_type_hint}.

**Notes:** Heuristic-only (PyMuPDF text-layer probe for TYPED; contrast + edge + density checks for SCANNED vs. HANDWRITTEN). No CNN, no ML.

#### OCR Worker

**Responsibility:** TYPED: PyMuPDF text extraction (99%+). SCANNED: Tesseract 5 + preprocessing (92–95%). HANDWRITTEN: PaddleOCR PP-OCRv5 + preprocessing (85–90%). Preprocessing: 300 DPI render → crop → grayscale → CLAHE → sharpen → deskew → optional form-line removal.

**Input:** S3 object + routing decision.

**Output:** Raw extracted text + page-level offsets.

**Notes:** Tesseract uses --oem 1 --psm 3 for scanned; PaddleOCR uses use_angle_cls=True for handwritten; per-page extraction enables per-page citations later.

#### Text Cleaner

**Responsibility:** Deterministic cleaning — de-hyphenation, OCR-error patterns, whitespace.

**Input:** Raw text.

**Output:** Cleaned text + page-level offset preservation.

**Notes:** Rule-based only; no LLM rewriting.

#### Chunker

**Responsibility:** Split cleaned text into ~500-token chunks with section-aware separators and 75-token overlap.

**Input:** Cleaned text + doc_type hint.

**Output:** List of chunks with chunk_id, parent doc_id, page span.

**Notes:** Adaptive document-type-aware chunking: prescriptions (atomic), lab reports and tables (row-serialized via PyMuPDF find_tables()), long clinical notes (parent-child with RecursiveCharacterTextSplitter), forms (key-value groups). Fallback: Iterative Builder (Claude 3.5 Haiku) if RAGAS Context Precision < 90%.

#### PHI Tagger

**Responsibility:** Detect 18 HIPAA identifiers per chunk; emit span list.

**Input:** Chunk text.

**Output:** phi_spans = [{type, start, end, confidence}] stored as chunk metadata.

**Notes:** Presidio with custom MRN/NPI recognizers; runs entirely on-prem.

#### Embedder

**Responsibility:** Embed each chunk via OpenAI embeddings API.

**Input:** Chunk text.

**Output:** 1536-d float vector.

**Notes:** Batched to reduce API round-trips; backoff/retry on rate-limit.

#### Indexer

**Responsibility:** Write the assembled chunk record (text + vector + metadata + ACL) to OpenSearch.

**Input:** Chunk + embedding + metadata.

**Output:** OpenSearch document ID.

**Notes:** Bulk-write API; idempotent by chunk_id.

### 4.2 Search Components

#### Query API

**Responsibility:** Accept query, resolve user/role/ACL, orchestrate the search pipeline.

**Input:** {query: str, session_id: str}

**Output:** {results: [{snippet, source, page, score}], audit_id}

**Notes:** FastAPI endpoint; session validated per request; role + ACL resolved before retrieval begins. LangGraph state machine drives the multi-step search pipeline.

#### Query Normalizer

**Responsibility:** Clean and normalize query (spell-check, medical-term normalization).

**Input:** Raw query string.

**Output:** Normalized query string.

**Notes:** Mirrors ingest-time cleaning so user input lands in the same shape as indexed text.

#### Hybrid Retriever

**Responsibility:** Run BM25 + kNN in OpenSearch with pre-filters; fuse via RRF.

**Input:** Normalized query + filter set (date, doc_type, ACL).

**Output:** Top-K (default K=50) candidate chunks.

**Notes:** Single OpenSearch hybrid query; ACL pre-filter is non-negotiable.

#### Reranker

**Responsibility:** Score (query, chunk) pairs with cross-encoder; reorder; return top-N.

**Input:** Top-K candidates + query.

**Output:** Top-N reranked chunks (default N=5).

**Notes:** BGE-reranker-base; runs on CPU with batched inference.

#### Response Masker

**Responsibility:** Apply role-based masking using each chunk’s stored phi_spans.

**Input:** Top-N chunks + user role.

**Output:** Masked snippets ready for display.

**Notes:** Mask policy is a config map {role → masked_identifier_types}.

### 4.3 Security & Compliance Components

#### Auth Service

**Responsibility:** Authenticate user via username/password, create server-side session with role claim, validate session on each request.

**Input:** Login credentials / token.

**Output:** Authenticated request context.

**Notes:** fastapi-sessions; session stored server-side in Postgres (encrypted); role checked per request; immediate revocation on logout. No JWT, no token expiry complexity.

#### ACL Resolver

**Responsibility:** Resolve which documents/departments a user can access at query time.

**Input:** User ID + role.

**Output:** ACL filter expression injected into OpenSearch pre-filter.

**Notes:** Single source of truth in Postgres; cached per-request.

#### Audit Logger

**Responsibility:** Append a row per query to the immutable audit table.

**Input:** Query, user, role, returned doc IDs, masking applied, timestamp, latency.

**Output:** Audit row ID.

**Notes:** Postgres append-only table; DB role lacks UPDATE/DELETE grants.

#### KMS Key Manager

**Responsibility:** Provide encryption keys for S3 (at rest) and TLS termination (in transit).

**Input:** Key request from S3/app.

**Output:** Data key.

**Notes:** AWS KMS, customer-managed keys, rotation enabled.

### 4.4 Observability Components

#### LangSmith Tracer

**Responsibility:** Capture full pipeline traces (query, retrieved chunks, rerank scores, final response, latency per step).

**Input:** Pipeline events.

**Output:** Trace records in LangSmith.

**Notes:** Wraps LangChain components; near-zero code overhead.

#### Eval Runner

**Responsibility:** Run RAGAS metrics against the golden dataset on a schedule and on PRs.

**Input:** Golden dataset (query → expected docs).

**Output:** Metric report (context precision/recall, faithfulness, top-3 hit rate).

**Notes:** Runs in CI; regression gate on top-3 hit rate.

---

## 5. POCs

These POCs are decision exercises — comparing options against the constraints of this project (intern scale, HIPAA posture, mixed document formats) rather than fully coded experiments. Each entry states what was compared, the option chosen, the trade-offs accepted, and what would trigger a revisit.

### POC 1: OCR Engine Selection

**What Was Tested:** Compared OCR engines on representative medical samples (typed discharge summaries, scanned prescriptions, handwritten notes) along accuracy, cost, deployment posture, and latency.

**Why It Was Tested:** OCR quality is the upstream bottleneck for the entire pipeline — garbage here is garbage everywhere downstream. Cost matters because OCR runs on every document.

**Options Compared:**

- Tesseract 5 (open-source, on-prem)
- AWS Textract (managed, high accuracy)
- PaddleOCR (open-source, strong handwriting)

**Outcome:** Smart OCR routing locked in: PyMuPDF for TYPED (99%+), Tesseract 5 + preprocessing for SCANNED (92–95%), PaddleOCR PP-OCRv5 + preprocessing for HANDWRITTEN (85–90%). AWS Textract rejected on cost and data-egress posture. PaddleOCR chosen over EasyOCR for handwritten (90–92% vs. 85–88%, faster init, layout analysis included).

**Trade-offs Accepted:** PaddleOCR adds a dependency vs. Tesseract-only, but 85–90% handwriting accuracy (with preprocessing) is a necessary trade-off for medical documents where handwritten notes carry critical clinical information. Preprocessing adds 3–5 sec/page but the accuracy gain justifies the cost. Fallback to AWS Textract available if PaddleOCR quality < 85%.

**Decision Impact:** Locks in three-way OCR routing (PyMuPDF / Tesseract / PaddleOCR) with a shared preprocessing pipeline. Classifier output directly determines which OCR engine runs — a future engine swap is a config change, not a rewrite.

### POC 2: Chunking Strategy

**What Was Tested:** Compared chunking strategies on a sample medical document set against three criteria — semantic coherence, structural respect, and reproducibility.

**Why It Was Tested:** Bad chunking silently destroys retrieval — split a drug name from its dose, and no retriever, however good, can recover it.

**Options Compared:**

- Fixed-size character chunking
- Recursive character splitter with section-aware separators
- Semantic chunking (embedding-similarity-based)
- Agentic / LLM-based chunking

**Outcome:** Adaptive document-type-aware chunking chosen. Four policies: prescriptions atomic, lab reports row-serialized via PyMuPDF find_tables(), long clinical notes parent-child with RecursiveCharacterTextSplitter, forms key-value grouped. Cost $0. RecursiveCharacterTextSplitter used only for the document types where it is appropriate — not as a one-size-fits-all solution. Section-parent-aware (ADR-005) retired as primary because prescriptions have no sections and lab reports are tables.

**Trade-offs Accepted:** Section detection heuristics need tuning per document template and may degrade on heavily OCR-noisy or unstructured documents. This is mitigated by the Iterative Builder fallback (Claude 3.5 Haiku, $20–30/1000 docs): triggered automatically when RAGAS Context Precision < 90%, so the quality bar is always enforced by data, not assumption.

**Decision Impact:** Chunking policy is now determined at document classification stage alongside OCR routing. Document type detection (heuristics: token count, table structure, key-value patterns) feeds into policy selector. Each document type gets the chunking strategy that preserves its clinical structure. PyMuPDF find_tables() added to typed PDF processing path for table reconstruction. Prescription atomic chunks preserve dose-instruction integrity. Lab report rows stay together enabling retrieval of test-result-normal relationships.

### POC 3: Vector Store Selection

**What Was Tested:** Compared vector stores on hybrid search support (BM25 + kNN in one query), metadata-filter performance, ops complexity, and HIPAA deployment posture.

**Why It Was Tested:** The vector store is the system’s hot path for every query; choosing wrong forces architectural workarounds (cross-system joins, manual fusion).

**Options Compared:**

- OpenSearch (local Docker container, k-NN plugin)
- Chroma (lightweight, local)
- Pinecone (managed SaaS)

**Outcome:** OpenSearch chosen.

**Trade-offs Accepted:** Higher ops complexity than Chroma and somewhat higher cost than self-hosted alternatives. In exchange we get true hybrid search (BM25 + HNSW in a single query), production-grade metadata filtering with pre-filter support, and AWS-native HIPAA-eligible deployment. Chroma is excellent for prototyping but lacks the hybrid-search story we need. Pinecone is strong but PHI leaving our boundary is exactly the compliance posture we are trying to avoid.

**Decision Impact:** Hybrid retrieval (Step 6) becomes a single query rather than two systems stitched together. ACL pre-filter becomes native rather than an application-level join.

### POC 4: Embedding Model Selection

**What Was Tested:** Evaluated embedding models on retrieval quality on a small medical query set, cost per million tokens, dimensionality vs. index size, and deployment posture.

**Why It Was Tested:** Embedding choice determines the semantic ceiling — no amount of reranking can recover information the embeddings collapsed.

**Options Compared:**

- OpenAI text-embedding-3-small (1536-d)
- OpenAI text-embedding-3-large (3072-d)
- BioBERT / MedCPT (open-source, ~768-d, medical-domain)

**Outcome:** OpenAI text-embedding-3-small chosen.

**Trade-offs Accepted:** Not domain-tuned. A medical-domain model could give better semantic separation on close clinical concepts. In exchange we get strong general-domain quality with zero model-serving infrastructure, low per-token cost (so re-embedding the corpus during iteration is cheap), and no GPU dependency for ingestion. text-embedding-3-large would cost roughly 2× for a modest gain not yet justified. ClinicalBERT (91–95% quality) is the named upgrade path if RAGAS Context Recall < 85%.

**Decision Impact:** Pins embedding dimension at 1536; defines the OpenSearch index mapping. Cross-encoder reranker carries the burden of fine-grained discrimination on top of general-purpose embeddings.

### POC 5: Reranking Strategy

**What Was Tested:** Compared post-retrieval reranking approaches, evaluating accuracy lift, latency cost, and operational complexity.

**Why It Was Tested:** Retrieval gives candidates; reranking decides what the user actually sees. The wrong choice either tanks accuracy (no rerank) or tanks latency (LLM rerank).

**Options Compared:**

- No reranking (use RRF output directly)
- Score normalization (min-max / z-score across retrievers)
- Cross-encoder reranking (BGE-reranker-base)
- LLM-as-judge reranking

**Outcome:** Cross-encoder reranking (BGE-reranker-base) chosen, layered on top of RRF fusion.

**Trade-offs Accepted:** Adds ~50–150 ms latency per query (CPU inference on top-50 pairs) vs. no reranking. We pay this cost because it consistently lifts top-3 hit rate — the metric we are graded on. Score normalization was rejected because min-max compresses scores around outliers and can zero out valid chunks. LLM-as-judge would be more accurate again but adds another API hop and unpredictable latency.

**Decision Impact:** Locks in a two-stage retrieval pattern: bi-encoder for recall, cross-encoder for precision. Reranker runs in-process on the FastAPI host; no separate model server needed at this scale.

### POC 6: PII Masking Approach

**What Was Tested:** Compared PHI-handling strategies on three criteria — single source of truth, support for per-role views, and operational simplicity.

**Why It Was Tested:** PHI handling is the highest-stakes part of the system from a compliance perspective; getting the data model wrong forces every downstream feature to work around it.

**Options Compared:**

- Store raw + pre-masked copies, switch by role
- Store only masked, deny non-treating roles entirely
- Store raw with PHI offset metadata, mask at query time per role

**Outcome:** Store raw + PHI offsets; mask at query time.

**Trade-offs Accepted:** Slightly more CPU at query time to apply masking. In exchange we get one source of truth (no drift between raw and masked copies), full flexibility to add new roles without re-ingesting the corpus, and the ability for a treating clinician to see unmasked text they have a legal right to view.

**Decision Impact:** Defines the OpenSearch document schema (PHI spans as metadata). Makes the masker a pure function (text, spans, role) → masked_text, which is testable in isolation.

### POC 7: API & Frontend Choice

**What Was Tested:** Evaluated whether to build a Streamlit prototype or a FastAPI + React app, weighed against the user stories (doctor search, admin audit, role-based views).

**Why It Was Tested:** Streamlit is faster to ship but constrains UX; the wrong choice here gets felt every time a new role view or audit page is added.

**Options Compared:**

- Streamlit (single-process, Python UI)
- FastAPI + React
- FastAPI + Streamlit

**Outcome:** FastAPI + React.

**Trade-offs Accepted:** Higher upfront effort than Streamlit. In exchange the API is reusable (the audit dashboard, the search UI, and any future agent all hit the same endpoints), per-role views are clean React components rather than if-role branches in a script, and the security model (session-based auth, middleware-enforced ACL) is simpler and more auditable than JWT — better suited for HIPAA’s access-tracking requirements.

**Decision Impact:** Confirms a clean client/server split. Allows the audit log UI to be a separate React route with its own role guard rather than a tab in the same Streamlit app.

### POC 8: Evaluation Framework

**What Was Tested:** Evaluated RAG evaluation frameworks for fit with the stack and the metrics we need to gate on.

**Why It Was Tested:** Without a reproducible eval loop, every "improvement" is anecdotal and regressions are invisible.

**Options Compared:**

- RAGAS
- TruLens
- LangSmith built-in evaluators only
- Manual labeling

**Outcome:** RAGAS for metrics, LangSmith for traces and dataset hosting, combined.

**Trade-offs Accepted:** Two systems to keep in sync. In exchange we get RAGAS’s standard RAG metrics running on real production traces captured by LangSmith — so evals reflect what users actually experience, not a synthetic harness. TruLens overlaps with RAGAS without unique value here. Manual labeling is retained for the small golden set only.

**Decision Impact:** Top-3 hit rate from RAGAS becomes the regression gate. Eval runs in CI on every PR that touches retrieval logic.

---

## 6. HIPAA Compliance Coverage

This section maps the HIPAA Security and Privacy Rule requirements relevant to this system onto what we implement, partially cover, and what is out of scope at intern scale. The goal is "HIPAA-aware architecture," not certified compliance.

| HIPAA Requirement | Coverage | How We Implement It |
|---|---|---|
| Encryption at rest | Full | S3 with SSE-KMS for source PDFs; Postgres and OpenSearch volumes encrypted; KMS customer-managed keys with rotation. |
| Encryption in transit | Full | TLS 1.2+ on all API endpoints; OpenSearch/Postgres connections over TLS; KMS for key delivery. |
| Access control (per-document) | Full | ACL field on every OpenSearch chunk; pre-filter applied at retrieval — users physically cannot retrieve chunks outside their ACL. |
| Authentication | Full | Session-based auth via fastapi-sessions; role stored server-side in Postgres; role claim required on every request; immediate revocation on logout. |
| Audit logging (access tracking) | Full | Append-only Postgres table with DB-level immutability (no UPDATE/DELETE grants); every query logs user, role, timestamp, query_hash (SHA-256 only — raw query text never stored), document IDs returned, masking applied. PHI never appears in audit log. |
| PHI identification (18 identifiers) | Full | Microsoft Presidio with custom medical recognizers; PHI spans stored as chunk metadata. |
| Minimum-necessary / role-based disclosure | Full | Response-time masking by role; non-treating roles see direct identifiers masked; auditors see fully redacted text. |
| Breach detection support | Partial | Audit log supports forensic query but no automated anomaly detection (e.g., unusual access patterns) — out of scope at this stage. |
| Data backup / disaster recovery | Partial | S3 versioning + Postgres backups; no documented DR drill at this stage. |
| De-identification (Safe Harbor) | Partial | Presidio handles detection; full Safe-Harbor de-id (date shifting, zip-code generalization to first three digits) is a future hardening item. |
| Logging immutability beyond DB | Partial | DB-level append-only enforced; no WORM storage tier or off-system log shipping yet. |
| Workforce training, BAAs, physical safeguards | Out of scope | Out of scope — prototype only. BAA is a signed legal contract between an organisation and a vendor (AWS, Anthropic, etc.) confirming HIPAA obligations. Requires: (a) real organisation with legal standing, (b) actual PHI in production. This build uses synthetic records only. For real deployment: AWS BAA must be explicitly enabled per account; Anthropic BAA requires an enterprise agreement. Documented as a known gap — mandatory before any real patient data is processed. |

**Summary:** the system implements the technical safeguards that map cleanly to architecture choices — encryption, access control, audit logging, PHI detection, and role-based disclosure. The audit log deliberately excludes raw query text and document content; only query_hash, document IDs, and access metadata are stored — PHI never appears in the audit log under any role or condition. The partial and out-of-scope items are organizational or operational requirements (workforce training, BAAs, DR drills) and deeper de-identification work that belong to a real production deployment rather than this build.

---

## 7. Success Criteria & Benchmarks

| Metric | Target | How Measured |
|---|---|---|
| Top-3 retrieval accuracy | ≥ 90% | RAGAS context-precision over 50-query golden set; regression gate on PRs. |
| OCR success rate (scanned) | ≥ 95% | Pages where OCR yields ≥ 50 chars of clean text without manual re-routing. |
| Query latency (P95, end-to-end) | ≤ 1500 ms | Includes retrieval + rerank + masking; measured via LangSmith traces. |
| Audit log completeness | 100% | Every query writes one row; verified by reconciling LangSmith traces vs. audit rows. |
| PII masking correctness | 100% on test set | Manual audit of masked responses for each role on the golden set. |

**End of design document.**

## 8. User Roles and System Scope

This system is a clinician-facing search tool. Patients do not interact with it directly. The three roles are:

**treating_clinician** — The doctor directly responsible for the patient. Sees full unmasked PHI. Access scoped to their department’s patients.

**non_treating_clinician** — Other clinical staff, researchers, quality teams. Sees condition and treatment details but direct identifiers (NAME, MRN, DOB, ADDRESS, PHONE) are masked as <TYPE_REDACTED>.

**administrator** — Records and compliance admin. Sees audit metadata only (who searched, when, result count). Cannot see document content or PHI.

**Why patients are not a role:** patients have separate access pathways (patient portals, formal records requests) governed by different regulatory frameworks. Adding patients as a search role would require a completely different ACL model, consent-tracking, and audit surface. Out of scope for this build.

## 9. RAGAS-Gated Upgrade Decisions

All primary decisions ship with the simplest, cheapest option. Upgrades are triggered only when RAGAS metrics prove the current approach is the bottleneck. Run the 50-query golden eval set after initial deployment before considering any upgrade. Rule: never upgrade based on assumption — only the metric can trigger it.

| Decision | Primary (ship now) | Upgrade trigger | Upgrade to | Upgrade cost |
|---|---|---|---|---|
| Chunking | Adaptive type-aware chunking (atomic / row-serialized / parent-child) — ₹0 | Context Precision < 90% | Iterative Builder / Claude 3.5 Haiku | ₹1,680–2,520 one-time |
| Embeddings | OpenAI 3-small — ₹25 one-time | Context Recall < 85% | ClinicalBERT (91–95%) | 2–3 hrs + GPU infra |
| OCR handwritten | PaddleOCR PP-OCRv5 — free | OCR success < 85% | AWS Textract | ₹84–840/month |
| OCR scanned | Tesseract 5 + preprocessing — free | OCR success < 95% | PaddleOCR or Textract | Free or ₹84–840/month |
| Ingestion pipeline | Synchronous 45 sec/doc — free | Scale to 10k+ docs or user wait complaints | Celery + Redis async queue | 4–8 hrs + ₹840–4200/month |
| Reranker | BGE-reranker-base local CPU — free | nDCG@10 < 0.77 or P95 > 1500 ms | BGE-reranker-large | GPU or per-call API cost |
| PHI detection | Presidio on-prem — free | PII masking correctness < 99% | AWS Comprehend Medical | ₹0–4200/month |