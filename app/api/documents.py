import hashlib
import io
import json
import os
import tempfile
import time
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request, UploadFile, File

load_dotenv(Path(__file__).parent.parent.parent / "config" / ".env")

from app.auth.models import DocumentHash
from app.database import SessionLocal
from app.ingestion.classifier import DocumentClassifier, DocType
from app.ingestion.ocr_worker import OCRWorker
from app.ingestion.text_cleaner import TextCleaner
from app.ingestion.chunker import AdaptiveChunker, ChunkDocType
from app.ingestion.phi_tagger import PhiTagger
from app.ingestion.embedder import Embedder
from app.ingestion.extractor import ClinicalExtractor
from app.ingestion.indexer import Indexer
from app.ingestion.extraction_validator import ExtractionValidator
from app.ingestion.layout_extractor import LayoutExtractor
from app.ingestion.normalizer import MedicalDocumentNormalizer
from app.observability.langsmith_tracer import LangSmithTracer, safe_error_category
from app.storage import get_storage_service
from app.schemas.document import IngestResponse

router = APIRouter()
_tracer = LangSmithTracer()

# Debug output root — created once at import time; dev-only, never committed
_DEBUG_ROOT = Path(__file__).parent.parent.parent / "debug_outputs"
for _sub in ("ocr", "chunks", "phi", "cleaned", "normalized"):
    (_DEBUG_ROOT / _sub).mkdir(parents=True, exist_ok=True)

_ocr = None
_phi = None
_embedder = None
_indexer = None
_extractor = None


def _get_ocr():
    global _ocr
    if _ocr is None:
        _ocr = OCRWorker()
    return _ocr


def _get_phi():
    global _phi
    if _phi is None:
        _phi = PhiTagger()
    return _phi


def _get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder


def _get_indexer():
    global _indexer
    if _indexer is None:
        _indexer = Indexer()
        _indexer.ensure_index()
    return _indexer


def _get_extractor():
    """Lazy singleton for the Project 3 clinical extractor.

    Returns the same ClinicalExtractor instance for the lifetime of the process.
    Model weights are only loaded on first .extract() call, not here — so the
    first call after a fresh process may take ~30-60s while the LoRA adapter
    materializes; subsequent calls are fast.
    """
    global _extractor
    if _extractor is None:
        _extractor = ClinicalExtractor.get()
    return _extractor


def _resolve_acl(request: Request) -> list:
    user = getattr(request.state, "user", None)
    if not user:
        return ["public"]
    role = str(user.get("role", "")).upper()
    if role == "TREATING_CLINICIAN":
        return ["dept_cardiology"]
    elif role == "NON_TREATING_CLINICIAN":
        return ["research_allowed"]
    else:
        return ["admin_only"]


def _chunk_char_stats(chunks: list) -> tuple:
    lengths = [len(getattr(chunk, "child_text", "") or "") for chunk in chunks]
    if not lengths:
        return None, None, None
    return min(lengths), max(lengths), round(sum(lengths) / len(lengths), 2)


def _phi_type_counts(spans: list) -> dict:
    counts = Counter()
    for span in spans:
        span_type = getattr(span, "span_type", None)
        if not span_type and isinstance(span, dict):
            span_type = span.get("type")
        counts[str(span_type or "UNKNOWN")] += 1
    return dict(counts)


@router.post("/api/ingest", response_model=IngestResponse)
async def ingest_document(request: Request, file: UploadFile = File(...)):
    """
    Ingestion pipeline:
    upload → classify → OCR/extract → clean
    → validate raw extraction
    → layout/table extraction (typed PDFs only)
    → normalize to Markdown (prescription/form, or when tables found)
    → validate normalized text; keep whichever scores higher
    → chunk → PHI tag → embed → index
    """
    trace_started_at = time.time()
    step_started_at = trace_started_at
    step_timings_ms = {}

    def mark_step(step_name: str):
        nonlocal step_started_at
        now = time.time()
        step_timings_ms[step_name] = int((now - step_started_at) * 1000)
        step_started_at = now

    def elapsed_ms() -> int:
        return int((time.time() - trace_started_at) * 1000)

    if not file.filename.lower().endswith(".pdf"):
        _tracer.trace_ingest(
            filename=file.filename or "",
            doc_id=None,
            doc_type=None,
            ocr_method=None,
            ocr_success_rate=None,
            raw_char_count=None,
            cleaned_char_count=None,
            normalization_applied=None,
            quality_score=None,
            needs_review=None,
            table_count=None,
            chunk_count=None,
            chunk_char_min=None,
            chunk_char_max=None,
            chunk_char_avg=None,
            phi_span_count=None,
            phi_type_counts=None,
            indexed_count=None,
            latency_ms=elapsed_ms(),
            step_timings_ms=step_timings_ms,
            error_category="invalid_file_type",
        )
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # --- Layer 1: file fingerprint deduplication ---
    file_bytes = await file.read()
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    mark_step("read_upload")

    db = SessionLocal()
    try:
        existing = db.query(DocumentHash).filter_by(file_hash=file_hash).first()
        if existing:
            mark_step("duplicate_check")
            _tracer.trace_ingest(
                filename=file.filename or "",
                doc_id=existing.doc_id,
                doc_type=None,
                ocr_method=None,
                ocr_success_rate=None,
                raw_char_count=None,
                cleaned_char_count=None,
                normalization_applied=None,
                quality_score=None,
                needs_review=None,
                table_count=None,
                chunk_count=None,
                chunk_char_min=None,
                chunk_char_max=None,
                chunk_char_avg=None,
                phi_span_count=None,
                phi_type_counts=None,
                indexed_count=None,
                latency_ms=elapsed_ms(),
                step_timings_ms=step_timings_ms,
                error_category="duplicate_document",
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "duplicate_document",
                    "message": "This file has already been ingested.",
                    "existing_doc_id": existing.doc_id,
                    "filename": existing.filename,
                    "ingested_at": existing.ingested_at.isoformat(),
                },
            )
        mark_step("duplicate_check")
    finally:
        db.close()

    doc_id = str(uuid.uuid4())
    doc_type = None
    raw_text = ""
    clean_text = ""
    ocr_result = {}
    tables = []
    chunks = []
    all_phi_spans = []
    raw_validation = {}
    normalization_applied = False
    indexed_count = None

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    mark_step("write_temp_file")

    try:
        storage = get_storage_service()
        storage_uri = storage.upload_pdf(io.BytesIO(file_bytes), doc_id)

        if hasattr(storage, "get_local_path"):
            process_path = storage.get_local_path(doc_id)
        else:
            process_path = tmp_path
        mark_step("storage_upload")

        # --- Classify (physical format: typed/scanned/handwritten) ----------
        doc_type, _meta = DocumentClassifier.classify(process_path)
        mark_step("classify")

        # --- OCR / text extraction ------------------------------------------
        ocr_result = _get_ocr().extract_text(process_path, doc_type)
        raw_text = ocr_result["text"]
        ocr_lines = ocr_result.get("lines")
        if ocr_lines:
            ocr_debug = "\n".join(
                f"[conf={l['confidence']:.2f}] {l['text']}" for l in ocr_lines
            )
            ocr_debug += f"\n\n--- avg confidence: {ocr_result['success_rate']:.4f} ---"
        else:
            ocr_debug = raw_text
        (_DEBUG_ROOT / "ocr" / f"{doc_id}.txt").write_text(ocr_debug, encoding="utf-8")
        mark_step("ocr_extract")

        # --- Clean -------------------------------------------------------------
        clean_text = TextCleaner.clean(raw_text)
        (_DEBUG_ROOT / "cleaned" / f"{doc_id}.txt").write_text(clean_text, encoding="utf-8")
        mark_step("clean_text")

        # --- Detect content type (prescription / lab / form / clinical note) --
        detected_chunk_type = AdaptiveChunker.detect_doc_type(clean_text)
        chunk_type_str = detected_chunk_type.value
        mark_step("detect_content_type")

        # --- Validate raw extraction ------------------------------------------
        raw_validation = ExtractionValidator.validate(clean_text, chunk_type_str)
        mark_step("validate_raw_extraction")

        # --- Layout / table extraction (typed PDFs only) ---------------------
        should_normalize = detected_chunk_type in (
            ChunkDocType.PRESCRIPTION, ChunkDocType.FORM
        )
        tables: list = []
        if doc_type == DocType.TYPED:
            tables = LayoutExtractor.extract_tables(process_path)
            if tables:
                should_normalize = True  # pdfplumber found tables → always normalize

        mark_step("layout_extraction")

        # --- Normalization ---------------------------------------------------
        norm_result: dict = {
            "normalized_text": clean_text,
            "normalized_format": "plain",
            "structured_fields": {},
            "normalization_applied": False,
        }
        normalization_applied = False

        if should_normalize:
            candidate = MedicalDocumentNormalizer.normalize(
                clean_text, chunk_type_str, tables
            )
            if candidate["normalization_applied"]:
                norm_text = candidate["normalized_text"]
                norm_validation = ExtractionValidator.validate(norm_text, chunk_type_str)

                # Keep normalized if quality is at least as good as raw
                if norm_validation["quality_score"] >= raw_validation["quality_score"]:
                    norm_result = candidate
                    normalization_applied = True
                else:
                    # Store norm result for debugging but index raw text
                    norm_result = candidate
                    normalization_applied = False

        mark_step("normalize")

        final_text = norm_result["normalized_text"] if normalization_applied else clean_text

        (_DEBUG_ROOT / "normalized" / f"{doc_id}.txt").write_text(
            norm_result["normalized_text"], encoding="utf-8"
        )

        # --- PHI tagging (on final text) -------------------------------------
        phi_tagger = _get_phi()
        all_phi_spans = phi_tagger.tag(final_text)
        phi_span_count = len(all_phi_spans)
        phi_spans_json = json.dumps([s.to_dict() for s in all_phi_spans])
        (_DEBUG_ROOT / "phi" / f"{doc_id}.json").write_text(
            json.dumps([s.to_dict() for s in all_phi_spans], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        mark_step("phi_tag")

        # --- Chunk final text -------------------------------------------------
        chunks = AdaptiveChunker.chunk(final_text, detected_chunk_type)
        mark_step("chunk")

        # --- Embed ------------------------------------------------------------
        embedder = _get_embedder()
        child_texts = [c.child_text for c in chunks]
        embeddings = embedder.embed_batch(child_texts)
        mark_step("embed")

        # --- Clinical structured extraction (Project 3) ----------------------
        # Runs on the UNMASKED chunk text — source_span offsets stay valid
        # against chunk.child_text (D-35). Per-chunk so the model sees a window
        # within its training distribution (~256 tokens).
        # extractor.extract() never raises: on any failure path it returns an
        # ExtractionResult with all validation flags False and error_reason set,
        # so the ingestion pipeline keeps running even if the LoRA adapter is
        # absent, OOMs, or the model emits unparseable text.
        extractor = _get_extractor()
        chunk_extractions = []
        for i, chunk in enumerate(chunks):
            chunk_id = hashlib.sha256(f"{file_hash}:{i}".encode()).hexdigest()[:32]
            result = extractor.extract(chunk.child_text, record_id=chunk_id)
            chunk_extractions.append(result)
        extraction_model_version = extractor.adapter_version()
        mark_step("extract")

        # --- Build index documents -------------------------------------------
        acl = _resolve_acl(request)
        structured_fields_json = json.dumps(
            norm_result.get("structured_fields", {}), ensure_ascii=False
        )
        extraction_issues_json = json.dumps(raw_validation["issues"])

        def _meds(result):
            return [
                {
                    "mention": e.mention,
                    "dosage": e.dosage,
                    "evidence": e.evidence,
                    "start_char": e.source_span.start_char,
                    "end_char": e.source_span.end_char,
                }
                for e in result.entities
                if e.entity_type == "medication"
            ]

        def _ades(result):
            return [
                {
                    "mention": e.mention,
                    "linked_medication": e.linked_medication,
                    "evidence": e.evidence,
                    "start_char": e.source_span.start_char,
                    "end_char": e.source_span.end_char,
                }
                for e in result.entities
                if e.entity_type == "adverse_event"
            ]

        def _relations(result):
            # Build from ae.linked_medication — NOT the cartesian product of
            # all medications × all adverse_events in the chunk. The model
            # populates linked_medication on each ADE to indicate which drug
            # it is tied to; a cartesian product would invent wrong pairs in
            # any chunk containing multiple drugs or multiple ADEs.
            if result.relation_status != "related":
                return []
            return [
                {
                    "drug": e.linked_medication,
                    "adverse_event": e.mention,
                    "status": "related",
                    "evidence": e.evidence,
                }
                for e in result.entities
                if e.entity_type == "adverse_event" and e.linked_medication
            ]

        index_docs = [
            {
                # Deterministic chunk ID: same file → same IDs → overwrites not duplicates
                "chunk_id": hashlib.sha256(f"{file_hash}:{i}".encode()).hexdigest()[:32],
                "doc_id": doc_id,
                # text is always what gets searched — full cleaned text preserves all content
                "text": clean_text,
                "raw_text": clean_text,
                "normalized_text": norm_result["normalized_text"],
                "normalized_format": norm_result.get("normalized_format", "plain"),
                "extraction_quality_score": raw_validation["quality_score"],
                "extraction_issues": extraction_issues_json,
                "needs_review": raw_validation["needs_review"],
                "normalization_applied": normalization_applied,
                "structured_fields": structured_fields_json,
                "embedding": embedding,
                "doc_type": str(doc_type.value),
                "phi_spans": phi_spans_json,
                "acl": acl,
                # Project 3 — structured clinical extraction outputs
                "medications": _meds(chunk_extractions[i]),
                "adverse_events": _ades(chunk_extractions[i]),
                "relations": _relations(chunk_extractions[i]),
                "extraction_model_version": extraction_model_version,
            }
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings))
        ]
        mark_step("build_index_documents")

        (_DEBUG_ROOT / "chunks" / f"{doc_id}.json").write_text(
            json.dumps(
                [
                    {
                        "chunk_id": doc["chunk_id"],
                        "child_text": doc["text"],
                        "parent_text": chunks[i].parent_text,
                        "doc_type": doc["doc_type"],
                        "normalization_applied": doc["normalization_applied"],
                        "extraction_quality_score": doc["extraction_quality_score"],
                        "needs_review": doc["needs_review"],
                    }
                    for i, doc in enumerate(index_docs)
                ],
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        indexed_count = _get_indexer().index_chunks(index_docs)
        mark_step("index")

        # --- Record fingerprint (only after successful indexing) -------------
        db = SessionLocal()
        try:
            db.add(DocumentHash(
                file_hash=file_hash,
                doc_id=doc_id,
                filename=file.filename,
                ingested_at=datetime.utcnow(),
            ))
            db.commit()
        finally:
            db.close()
        mark_step("record_fingerprint")

        chunk_char_min, chunk_char_max, chunk_char_avg = _chunk_char_stats(chunks)
        _tracer.trace_ingest(
            filename=file.filename or "",
            doc_id=doc_id,
            doc_type=str(doc_type.value) if doc_type else None,
            ocr_method=ocr_result.get("method"),
            ocr_success_rate=ocr_result.get("success_rate"),
            raw_char_count=len(raw_text),
            cleaned_char_count=len(clean_text),
            normalization_applied=normalization_applied,
            quality_score=raw_validation.get("quality_score"),
            needs_review=raw_validation.get("needs_review"),
            table_count=len(tables),
            chunk_count=len(chunks),
            chunk_char_min=chunk_char_min,
            chunk_char_max=chunk_char_max,
            chunk_char_avg=chunk_char_avg,
            phi_span_count=len(all_phi_spans),
            phi_type_counts=_phi_type_counts(all_phi_spans),
            indexed_count=indexed_count,
            latency_ms=elapsed_ms(),
            step_timings_ms=step_timings_ms,
        )

    except Exception as exc:
        chunk_char_min, chunk_char_max, chunk_char_avg = _chunk_char_stats(chunks)
        _tracer.trace_ingest(
            filename=file.filename or "",
            doc_id=doc_id,
            doc_type=str(doc_type.value) if doc_type else None,
            ocr_method=ocr_result.get("method"),
            ocr_success_rate=ocr_result.get("success_rate"),
            raw_char_count=len(raw_text) if raw_text else None,
            cleaned_char_count=len(clean_text) if clean_text else None,
            normalization_applied=normalization_applied,
            quality_score=raw_validation.get("quality_score"),
            needs_review=raw_validation.get("needs_review"),
            table_count=len(tables),
            chunk_count=len(chunks),
            chunk_char_min=chunk_char_min,
            chunk_char_max=chunk_char_max,
            chunk_char_avg=chunk_char_avg,
            phi_span_count=len(all_phi_spans),
            phi_type_counts=_phi_type_counts(all_phi_spans),
            indexed_count=indexed_count,
            latency_ms=elapsed_ms(),
            step_timings_ms=step_timings_ms,
            error_category=safe_error_category(exc),
        )
        raise

    finally:
        os.unlink(tmp_path)

    return IngestResponse(
        doc_id=doc_id,
        filename=file.filename,
        doc_type=str(doc_type.value),
        chunk_count=len(chunks),
        indexed_count=indexed_count,
        storage_uri=storage_uri,
        phi_span_count=phi_span_count,
        quality_score=raw_validation["quality_score"],
        needs_review=raw_validation["needs_review"],
        normalization_applied=normalization_applied,
    )
