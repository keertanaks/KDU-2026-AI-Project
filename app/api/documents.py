import hashlib
import io
import json
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request, UploadFile, File

load_dotenv(Path(__file__).parent.parent.parent / "config" / ".env")

from app.auth.models import DocumentHash
from app.database import SessionLocal
from app.ingestion.classifier import DocumentClassifier
from app.ingestion.ocr_worker import OCRWorker
from app.ingestion.text_cleaner import TextCleaner
from app.ingestion.chunker import AdaptiveChunker
from app.ingestion.phi_tagger import PhiTagger
from app.ingestion.embedder import Embedder
from app.ingestion.indexer import Indexer
from app.storage import get_storage_service
from app.schemas.document import IngestResponse

router = APIRouter()

# Debug output root — created once at import time; dev-only, never committed
_DEBUG_ROOT = Path(__file__).parent.parent.parent / "debug_outputs"
for _sub in ("ocr", "chunks", "phi", "cleaned"):
    (_DEBUG_ROOT / _sub).mkdir(parents=True, exist_ok=True)

_ocr = None
_phi = None
_embedder = None
_indexer = None


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


@router.post("/api/ingest", response_model=IngestResponse)
async def ingest_document(request: Request, file: UploadFile = File(...)):
    """
    Synchronous ingestion pipeline:
    upload -> storage -> classify -> OCR/extract -> clean -> chunk -> PHI tag -> embed -> index
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # --- Layer 1: file fingerprint deduplication ---
    file_bytes = await file.read()
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    db = SessionLocal()
    try:
        existing = db.query(DocumentHash).filter_by(file_hash=file_hash).first()
        if existing:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "duplicate_document",
                    "message": f"This file has already been ingested.",
                    "existing_doc_id": existing.doc_id,
                    "filename": existing.filename,
                    "ingested_at": existing.ingested_at.isoformat(),
                },
            )
    finally:
        db.close()

    doc_id = str(uuid.uuid4())

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        storage = get_storage_service()
        storage_uri = storage.upload_pdf(io.BytesIO(file_bytes), doc_id)

        if hasattr(storage, "get_local_path"):
            process_path = storage.get_local_path(doc_id)
        else:
            process_path = tmp_path

        doc_type, _meta = DocumentClassifier.classify(process_path)

        ocr_result = _get_ocr().extract_text(process_path, doc_type)
        raw_text = ocr_result["text"]
        ocr_lines = ocr_result.get("lines")  # only present for handwritten
        if ocr_lines:
            # Write per-line confidence so low-quality lines are immediately visible
            ocr_debug = "\n".join(
                f"[conf={l['confidence']:.2f}] {l['text']}" for l in ocr_lines
            )
            ocr_debug += f"\n\n--- avg confidence: {ocr_result['success_rate']:.4f} ---"
        else:
            ocr_debug = raw_text
        (_DEBUG_ROOT / "ocr" / f"{doc_id}.txt").write_text(ocr_debug, encoding="utf-8")

        clean_text = TextCleaner.clean(raw_text)
        (_DEBUG_ROOT / "cleaned" / f"{doc_id}.txt").write_text(clean_text, encoding="utf-8")

        chunks = AdaptiveChunker.chunk(clean_text)

        phi_tagger = _get_phi()
        all_phi_spans = phi_tagger.tag(clean_text)
        phi_span_count = len(all_phi_spans)
        phi_spans_json = json.dumps([s.to_dict() for s in all_phi_spans])
        (_DEBUG_ROOT / "phi" / f"{doc_id}.json").write_text(
            json.dumps([s.to_dict() for s in all_phi_spans], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        embedder = _get_embedder()
        child_texts = [c.child_text for c in chunks]
        embeddings = embedder.embed_batch(child_texts)

        acl = _resolve_acl(request)
        index_docs = [
            {
                # Deterministic chunk ID: same file always produces the same IDs,
                # so re-indexing overwrites rather than duplicates in OpenSearch.
                "chunk_id": hashlib.sha256(f"{file_hash}:{i}".encode()).hexdigest()[:32],
                "doc_id": doc_id,
                "text": chunk.child_text,
                "embedding": embedding,
                "doc_type": str(doc_type.value),
                "phi_spans": phi_spans_json,
                "acl": acl,
            }
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings))
        ]
        (_DEBUG_ROOT / "chunks" / f"{doc_id}.json").write_text(
            json.dumps(
                [
                    {
                        "chunk_id": doc["chunk_id"],
                        "child_text": doc["text"],
                        "parent_text": chunks[i].parent_text,
                        "doc_type": doc["doc_type"],
                    }
                    for i, doc in enumerate(index_docs)
                ],
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        indexed_count = _get_indexer().index_chunks(index_docs)

        # Layer 1: record fingerprint so re-upload of same file is rejected
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
    )
