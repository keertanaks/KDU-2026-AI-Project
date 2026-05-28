"""
Batch ingest typed PDFs through the full normalization pipeline.

Usage:
    python scripts/batch_ingest.py [pdf1 pdf2 ...]

If no paths are given, ingests the default set of 4 typed PDFs.
Prints a full per-PDF debug summary (same stages as debug_extraction_quality.py).
"""

import sys
import hashlib
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "config" / ".env")

from app.ingestion.classifier import DocumentClassifier, DocType
from app.ingestion.ocr_worker import OCRWorker
from app.ingestion.text_cleaner import TextCleaner
from app.ingestion.chunker import AdaptiveChunker, ChunkDocType
from app.ingestion.extraction_validator import ExtractionValidator
from app.ingestion.layout_extractor import LayoutExtractor
from app.ingestion.normalizer import MedicalDocumentNormalizer

DEFAULT_PDFS = [
    "sample_data/Typed/Mercy_General_Hospital/Emily_Moore-David_Thompson-Mercy_General_Hospital-MRN100003.pdf",
    "sample_data/Typed/Mercy_General_Hospital/Samuel_King-Michael_Rodriguez-Mercy_General_Hospital-MRN100002.pdf",
    "sample_data/Typed/St_Marys_Medical_Center/Charlotte_Brown-Robert_Johnson-St_Marys_Medical_Center-MRN100011.pdf",
    "sample_data/Typed/Johns_Hopkins_Regional/David_Hall-Steven_Clark-Johns_Hopkins_Regional-MRN100024.pdf",
]


def _sep(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print('=' * 70)


def process_pdf(pdf_path: str) -> None:
    path = Path(pdf_path)
    if not path.exists():
        print(f"  ERROR: not found: {pdf_path}")
        return

    print(f"\n{'#' * 70}")
    print(f"  FILE: {path.name}")
    print(f"{'#' * 70}")

    # 1. Classify
    doc_type, meta = DocumentClassifier.classify(str(path))
    print(f"\n  [1] doc_type={doc_type.value}  metadata={meta}")

    # 2. Extract raw text
    ocr = OCRWorker()
    ocr_result = ocr.extract_text(str(path), doc_type)
    raw_text = ocr_result["text"]
    clean_text = TextCleaner.clean(raw_text)

    # 3. Detect content type
    detected_chunk_type = AdaptiveChunker.detect_doc_type(clean_text)
    chunk_type_str = detected_chunk_type.value

    # 4. Raw quality
    raw_val = ExtractionValidator.validate(clean_text, chunk_type_str)
    print(f"  [2] chunk_type={chunk_type_str}")
    print(f"  [3] raw_quality={raw_val['quality_score']:.2f}  "
          f"needs_review={raw_val['needs_review']}  "
          f"issues={raw_val['issues']}")

    # 5. pdfplumber tables
    tables = []
    if doc_type == DocType.TYPED:
        tables = LayoutExtractor.extract_tables(str(path))
    print(f"  [4] tables_found={len(tables)}")
    for t_idx, table in enumerate(tables):
        print(f"      Table {t_idx + 1}: {len(table)} rows")
        for row in table:
            print(f"        {row}")

    # 6. Normalize
    should_normalize = (
        detected_chunk_type in (ChunkDocType.PRESCRIPTION, ChunkDocType.FORM)
        or len(tables) > 0
    )
    norm_result = MedicalDocumentNormalizer.normalize(clean_text, chunk_type_str, tables)

    normalization_applied = False
    if norm_result["normalization_applied"]:
        norm_val = ExtractionValidator.validate(norm_result["normalized_text"], chunk_type_str)
        normalization_applied = norm_val["quality_score"] >= raw_val["quality_score"]
        print(f"  [5] norm_quality={norm_val['quality_score']:.2f}  "
              f"normalization_applied={normalization_applied}")
    else:
        print(f"  [5] normalization not applicable for doc_type={chunk_type_str}")

    # 7. Normalized Markdown
    if norm_result["normalization_applied"]:
        _sep("NORMALIZED MARKDOWN")
        print(norm_result["normalized_text"])

    # 8. Structured fields
    sf = norm_result.get("structured_fields", {})
    if sf:
        _sep("STRUCTURED FIELDS")
        for k, v in sf.items():
            if k == "medications":
                print(f"  medications ({len(v)} items):")
                for med in v:
                    print(f"    - {med}")
            elif k == "instructions":
                print(f"  instructions ({len(v)} items):")
                for instr in v:
                    print(f"    - {instr}")
            else:
                print(f"  {k}: {v}")

    # 9. Final text decision
    final_text = norm_result["normalized_text"] if normalization_applied else clean_text
    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    print(f"\n  [FINAL] file_hash={file_hash[:16]}...  "
          f"final_format={'markdown' if normalization_applied else 'plain'}")


def main() -> None:
    paths = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_PDFS
    root = Path(__file__).parent.parent
    for p in paths:
        full = root / p if not Path(p).is_absolute() else Path(p)
        process_pdf(str(full))
    print(f"\n\nDone — processed {len(paths)} file(s).")


if __name__ == "__main__":
    main()
