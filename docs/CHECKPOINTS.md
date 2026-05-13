# Implementation Checkpoints

Append a new entry at the end of each completed phase before opening a PR.

---

## Phase 0 — Setup & Infrastructure

**Date:** 2026-05-13
**Branch:** `feature/phase-0-1-foundation`
**Commit:** `d468e8c9898623a91693165d42e12195dbdf325d`

### Completed Work
- Docker Compose: OpenSearch 2.11.0 + PostgreSQL 15-alpine
- Project structure scaffolded (all module stubs created)
- `app/config.py` — dotenv-based environment config
- `app/database.py` — SQLAlchemy engine + SessionLocal
- `scripts/init_opensearch.py` — creates `healthcare_chunks` index
- `scripts/init_db.py` — creates DB tables via Base.metadata
- `requirements.txt`, `pyproject.toml`, `.flake8`, `pytest.ini`
- `config/.env.example` — template for all required env vars

### Architectural Decisions
- OpenSearch index uses `nmslib` HNSW engine, NOT `lucene`. OpenSearch 2.11 Lucene HNSW is hard-capped at 1024 dimensions; `text-embedding-3-small` produces 1536 dimensions. `nmslib` has no such cap.
- PostgreSQL via SQLAlchemy 2.x ORM + Alembic for migrations (production-style, not ad-hoc DDL).

### Deviations from Guide
- Python 3.10.11 used instead of the guide-specified 3.11+. All current phase code is compatible.

### Issues Encountered
- None.

### Exit Criteria
| Check | Result |
|-------|--------|
| docker-compose up completes | PASS |
| OpenSearch + Postgres containers running | PASS |
| curl localhost:9200 returns cluster info | PASS |
| psql connection succeeds | PASS |
| `import app` succeeds | PASS |
| Node/npm installed | PASS |
| config/.env vars set | PASS |
| init_opensearch.py creates index | PASS |
| init_db.py creates tables | PASS |
| pytest imports succeed | PASS |

### Blocked Items
- None.

### Safe to Proceed
Yes.

---

## Phase 1 — Authentication & Database

**Date:** 2026-05-13
**Branch:** `feature/phase-0-1-foundation`
**Commit:** `d468e8c9898623a91693165d42e12195dbdf325d` (same commit as Phase 0 — both shipped together)
**Merged to dev via PR #1**

### Completed Work
- `app/auth/models.py` — `UserRole` enum, `User`, `Session`, `AuditLog` SQLAlchemy models
- `app/auth/service.py` — `AuthService`: bcrypt hash/verify (rounds=12), create/validate/revoke session, 8-hour TTL
- `app/auth/middleware.py` — ASGI session middleware; protects all `/api/*` except `/api/auth/login`, `/api/auth/logout`, `/health`
- `app/main.py` — login, logout, search stub, health endpoints; CORS middleware wired correctly
- `alembic/versions/001_initial_schema.py` — raw SQL migration: `userrole` ENUM, `users`, `sessions`, `audit_logs` tables + indexes
- `alembic/env.py` — configured with `Base.metadata` for autogenerate
- `alembic/alembic.ini` — added `[loggers]`, `[handlers]`, `[formatters]` sections
- `scripts/seed_users.py` — seeds 3 users (one per role)

### Architectural Decisions
- **No JWT.** Server-side sessions stored in PostgreSQL `sessions` table. Session IDs are UUIDs.
- **bcrypt rounds=12.** Matches guide and HIPAA best practice.
- **CORS middleware ordering:** `session_middleware` registered first (`app.middleware("http")`), `CORSMiddleware` added second (`app.add_middleware`). Both prepend to Starlette's middleware list; last registration becomes outermost. CORS must be outermost to handle OPTIONS preflight before auth runs.
- **Alembic as primary schema path.** Tables always created via `alembic upgrade head`, not `Base.metadata.create_all`. The `init_db.py` script is a fallback only.
- **Raw SQL DDL in migration.** SQLAlchemy 2.x `_on_table_create` hook ignores `create_type=False` on `sa.Enum`, causing duplicate-type errors. Workaround: use `op.execute("CREATE TYPE ...")` for all DDL.
- **PostgreSQL ENUM values are UPPERCASE** (`TREATING_CLINICIAN`, not `treating_clinician`). SQLAlchemy serialises enum members by `.name` (uppercase), not `.value` (lowercase). The DB type must match.
- **`secure=False` on session cookie** for local HTTP dev. Must be `True` behind TLS in production.

### Deviations from Guide
- None. Alembic migration approach is a deliberate production-style addition, not a simplification.

### Issues Encountered
1. `alembic.ini` missing `[loggers]`/`[handlers]`/`[formatters]` sections — `fileConfig()` raised `KeyError`. Fixed by adding standard logging config.
2. `sa.Enum create_type=False` ignored by SQLAlchemy 2.x `_on_table_create` hook — caused `DuplicateObject` error. Fixed by switching to pure `op.execute()` DDL.
3. PostgreSQL ENUM rejected lowercase values from seeder. Fixed by recreating ENUM with UPPERCASE names.
4. `gh` CLI not installed — PR created manually on GitHub.

### Exit Criteria
| Check | Result |
|-------|--------|
| User in DB (SELECT username, role) | PASS |
| Login endpoint returns 200/401 | PASS |
| Session cookie set on login | PASS |
| Valid sessions in DB (is_valid=true) | PASS |
| Logout sets is_valid=false | PASS |
| Role matches user's role in sessions | PASS |
| Unauth request returns 401 | PASS |
| Auth request accepted | PASS |
| Password hash is bcrypt (not plaintext) | PASS |

### Blocked Items
- None.

### Safe to Proceed
Yes.

---

## Phase 1.6 — Frontend (React + Vite + Tailwind)

**Date:** 2026-05-13
**Branch:** `feature/phase-1.6-frontend`
**Commit:** `20d67c99958aaad8c67392b7542d9124bf4a36ad`
**Merged to dev via PR #2**

### Completed Work
- Vite React app scaffolded under `frontend/`
- Tailwind CSS v3 configured (`tailwind.config.js`, `postcss.config.js`, `@tailwind` directives in `index.css`)
- `frontend/src/services/api.js` — axios client with `withCredentials: true`; `authAPI`, `searchAPI`
- `frontend/src/services/auth.js` — thin wrappers
- Pages: `LoginPage`, `SearchPage`, `AdminDashboard`
- Components: `SearchBar`, `ResultsList`, `MaskingIndicator`, `AuditDashboard` (Phase 3 placeholder)
- `App.jsx` — state-based page switching (no React Router)
- `app/main.py` — added `CORSMiddleware` to allow cross-origin cookie requests from `http://localhost:5173`

### Architectural Decisions
- **No React Router.** Simple `useState` page switcher. Guide does not require routing; avoids over-engineering.
- **`withCredentials: true`** on all axios requests — required for the browser to send `session_id` cookie on cross-origin requests.
- **Tailwind v3 not v4.** npm resolves `tailwindcss@latest` to v4, which has a completely different config API (CSS-first, no `tailwindcss init -p`). Guide specifies v3; pinned to `tailwindcss@3`.

### Deviations from Guide
- React 19 + Vite 8 used (latest at scaffold time) instead of the React 18 / Vite 4 pinned in the guide's `package.json`. Fully compatible; no behavior change.

### Issues Encountered
1. `npm install -D tailwindcss` resolved to v4 which has no `tailwindcss init -p` command. Downgraded to `tailwindcss@3`.
2. CORS headers absent on responses — session middleware was outermost (registered last) and short-circuited unauthorized requests before CORS ran. Fixed by reversing middleware registration order.

### Exit Criteria
| Check | Result |
|-------|--------|
| `npm run build` succeeds, creates dist/ | PASS |
| Vite dev server starts on :5173 | PASS |
| dist/assets/index-*.css contains Tailwind output | PASS |
| `import axios` in api.js | PASS |
| `withCredentials: true` in api.js | PASS |
| "Healthcare Semantic Search" heading renders | PASS |
| Search form accepts input, no console errors | PASS |

### Blocked Items
- None.

### Safe to Proceed
Yes.

---

## Phase 2.1 — Ingestion Pipeline

**Date:** 2026-05-13
**Branch:** `feature/phase-2.1-ingestion`
**Commit:** `ad97abdde64012707087a73f5f1f162450ddfab5`

### Completed Work
- `app/ingestion/classifier.py` — `DocumentClassifier.classify()`: PyMuPDF text probe (TYPED if >100 chars), OpenCV heuristics (contrast+edge density) for SCANNED vs HANDWRITTEN
- `app/ingestion/preprocessor.py` — `PreprocessingPipeline.preprocess()`: 300 DPI render, bounding-box crop, CLAHE, sharpen kernel, safe deskew via Hough lines
- `app/ingestion/ocr_worker.py` — `OCRWorker`: PyMuPDF (typed, 99%+), Tesseract 5 (scanned, ~93%), PaddleOCR v2 PP-OCRv4 (handwritten, ~87%); lazy-loads PaddleOCR to avoid slow startup
- `app/ingestion/text_cleaner.py` — `TextCleaner.clean()`: strips non-printable chars, normalises unicode dashes/quotes, collapses whitespace
- `app/ingestion/chunker.py` — `AdaptiveChunker`: prescription (atomic), lab report (line-per-chunk), form (section-per-chunk), clinical note (RecursiveCharacterTextSplitter 512/50)
- `app/ingestion/phi_tagger.py` — `PhiTagger`: Presidio `AnalyzerEngine`, detects 18 HIPAA identifier types
- `app/ingestion/embedder.py` — `Embedder`: OpenAI `text-embedding-3-small`, 1536 dims, batch via single API call
- `app/ingestion/indexer.py` — `Indexer.ensure_index()` creates nmslib HNSW mapping; `index_chunks()` bulk-indexes via opensearchpy helpers
- `app/storage/local_storage_service.py` — `LocalStorageService`: stores PDFs under `uploads/` on disk
- `app/storage/s3_service.py` — `S3Service`: boto3 `put_object` with `ServerSideEncryption=aws:kms`
- `app/storage/__init__.py` — `get_storage_service()`: returns `LocalStorageService` if `USE_LOCAL_STORAGE=true`, else `S3Service`
- `app/api/documents.py` — `POST /api/ingest`: full synchronous pipeline (upload → classify → OCR → clean → chunk → PHI tag → embed → index); module-level singletons for OCR/PHI/embedder/indexer
- `app/schemas/document.py` — `IngestResponse`, `ChunkMeta` Pydantic models
- `app/main.py` — `include_router(documents_router)`
- `scripts/verify_s3_kms.py` — standalone S3+KMS checklist; outputs PASS/FAIL/BLOCKED per credential
- `config/.env.example` — added `USE_LOCAL_STORAGE`, `TESSERACT_CMD`
- `requirements.txt` — pinned `paddleocr==2.9.1`, `paddlepaddle==2.6.2`; added `langchain-text-splitters`, `onnxruntime`
- `sample_data/scanned/`, `sample_data/raw_zip/` directories created

### Architectural Decisions
- **Storage abstraction.** `get_storage_service()` factory decouples the pipeline from storage backend. `USE_LOCAL_STORAGE=true` (default) uses local disk; `false` routes to S3+KMS. The ingest endpoint calls `get_local_path()` on the local service to avoid re-downloading files for processing.
- **nmslib engine preserved.** `Indexer.ensure_index()` creates the index with `"engine": "nmslib"`. This is the carry-forward constraint from Phase 0.
- **Module-level singletons in ingest endpoint.** OCR worker, PHI tagger, embedder, and indexer are instantiated once per worker process. PaddleOCR model load (~3s) only happens on first handwritten document.
- **ACL assigned at ingest time** from session role. Treating clinicians get `dept_cardiology` (placeholder; Phase 3 wires department-based ACL from DB). Non-treating get `research_allowed`. Admins get `admin_only`.
- **PHI spans stored as JSON string** in the `phi_spans` field (type: `text` in OpenSearch). The masker in Phase 2.2 deserialises this per-chunk at query time.
- **langchain import changed.** Guide imports from `langchain.text_splitter`; the installed `langchain-text-splitters` package exposes `langchain_text_splitters`. Used the correct import path.

### Deviations from Guide
- **PaddleOCR pinned to v2.9.1 / paddlepaddle==2.6.2.** PaddleOCR v3 requires paddlepaddle 3.x. paddlepaddle 3.3.1 on Windows raises `NotImplementedError: ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]` in the oneDNN instruction executor during inference. PaddleOCR v2.9.1 uses the identical API (`PaddleOCR(use_angle_cls=True, lang='en')` + `.ocr(img, cls=True)`) specified in the guide's exit criteria and works correctly on Windows.
- **Tesseract installed via winget** (`winget install UB-Mannheim.TesseractOCR`) and path set via `TESSERACT_CMD` env var. The guide assumes Linux/PATH; Windows requires explicit binary path.

### Issues Encountered
1. PaddleOCR v3 (latest from pip) failed inference on Windows with oneDNN error. Downgraded to v2.9.1 + paddlepaddle==2.6.2.
2. `langchain.text_splitter.RecursiveCharacterTextSplitter` not available — correct import is `langchain_text_splitters`. Updated chunker accordingly.
3. Tesseract not in PATH on Windows — added `TESSERACT_CMD` env var; `ocr_worker.py` reads it at module load.
4. OpenAI API key in `config/.env` returns HTTP 401 — embedder and full end-to-end ingest are blocked until a valid key is provided.
5. AWS credentials placeholder — S3/KMS live checks blocked until Section 0.3.1 setup is complete.

### Exit Criteria
| Check | Result |
|-------|--------|
| Classifier imports and executes | PASS |
| TYPED PDF classified correctly | PASS (confidence=0.99) |
| SCANNED PDF classified correctly | PASS (heuristic) |
| HANDWRITTEN PDF classified correctly | PASS (all 4 sample PDFs) |
| Preprocessor returns image shape | PASS (365×2268 @ 300 DPI) |
| PyMuPDF extraction > 100 chars | PASS (957 chars) |
| Tesseract 5 lists languages | PASS (eng, osd — v5.4.0) |
| PaddleOCR init + inference | PASS (v2.9.1, 508 chars from HandWritten_D3) |
| Prescription → 1 atomic chunk | PASS |
| Clinical note → multiple chunks, parent_text intact | PASS (5 chunks) |
| PHI tagger detects identifiers | PASS (PERSON, DATE_TIME, ID detected) |
| Embedder batches 2 texts → 1536-dim each | BLOCKED — OpenAI key returns 401 |
| S3Service boto3 client initialises | PASS |
| OpenSearch chunk indexed with correct fields | PASS (doc_id, phi_spans, acl, doc_type verified) |
| nmslib engine confirmed in mapping | PASS |
| Real AWS S3 + KMS setup | BLOCKED — credentials not configured |
| /api/ingest endpoint registered | PASS (200/401 depending on auth) |
| Full pipeline stages execute (mock embeddings) | PASS (classify→OCR→clean→chunk→PHI→index all work) |

### Blocked Items
1. **OpenAI API key** — key in `config/.env` returns HTTP 401. Obtain valid key from `platform.openai.com/api-keys`, update `config/.env`. Embedder and end-to-end ingest will then work.
2. **AWS S3 + KMS** — complete Section 0.3.1 of IMPLEMENTATION_GUIDE.md (bucket creation, KMS key, IAM user, env vars). Then run `python scripts/verify_s3_kms.py` and confirm all PASS before setting `USE_LOCAL_STORAGE=false`.

### Safe to Proceed
Yes — all pipeline stages verified. Resolve blocked items before end-to-end ingest test with real documents.
