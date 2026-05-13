"""
Debug script: run every stage of the new extraction quality pipeline on a PDF.

Usage:
    python scripts/debug_extraction_quality.py <path/to/file.pdf>

Prints:
  1. Classifier result (typed / scanned / handwritten)
  2. Raw extracted text
  3. Raw quality score and issues
  4. pdfplumber table rows (if any)
  5. Normalized Markdown text
  6. Normalized quality score and issues
  7. Final text that would be indexed
"""

import sys
from pathlib import Path

# Make sure app/ is importable
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


def _sep(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print('=' * 70)


def main(pdf_path: str) -> None:
    path = Path(pdf_path)
    if not path.exists():
        print(f"ERROR: file not found: {pdf_path}")
        sys.exit(1)

    # 1. Classify
    _sep("1. CLASSIFIER")
    doc_type, meta = DocumentClassifier.classify(str(path))
    print(f"  doc_type : {doc_type.value}")
    print(f"  metadata : {meta}")

    # 2. Extract raw text
    _sep("2. RAW EXTRACTED TEXT")
    ocr = OCRWorker()
    ocr_result = ocr.extract_text(str(path), doc_type)
    raw_text = ocr_result["text"]
    print(raw_text)

    # 3. Clean
    clean_text = TextCleaner.clean(raw_text)

    # 4. Detect content type
    detected_chunk_type = AdaptiveChunker.detect_doc_type(clean_text)
    chunk_type_str = detected_chunk_type.value

    _sep("3. RAW EXTRACTION QUALITY")
    raw_val = ExtractionValidator.validate(clean_text, chunk_type_str)
    print(f"  quality_score       : {raw_val['quality_score']}")
    print(f"  needs_review        : {raw_val['needs_review']}")
    print(f"  issues              : {raw_val['issues']}")
    print(f"  recommended_fallback: {raw_val['recommended_fallback']}")
    print(f"  detected_chunk_type : {chunk_type_str}")

    # 5. pdfplumber tables
    tables: list = []
    if doc_type == DocType.TYPED:
        tables = LayoutExtractor.extract_tables(str(path))
    _sep("4. PDFPLUMBER TABLE ROWS")
    if tables:
        for t_idx, table in enumerate(tables):
            print(f"\n  Table {t_idx + 1}:")
            for row in table:
                print(f"    {row}")
    else:
        print("  (no tables found)")

    # 6. Normalize
    should_normalize = (
        detected_chunk_type in (ChunkDocType.PRESCRIPTION, ChunkDocType.FORM)
        or len(tables) > 0
    )
    norm_result = MedicalDocumentNormalizer.normalize(clean_text, chunk_type_str, tables)

    _sep("5. NORMALIZED TEXT (Markdown)")
    if norm_result["normalization_applied"]:
        print(norm_result["normalized_text"])
    else:
        print("  (normalization not applied for this doc type)")

    # 7. Normalized quality
    _sep("6. NORMALIZED EXTRACTION QUALITY")
    if norm_result["normalization_applied"]:
        norm_val = ExtractionValidator.validate(norm_result["normalized_text"], chunk_type_str)
        print(f"  quality_score : {norm_val['quality_score']}")
        print(f"  needs_review  : {norm_val['needs_review']}")
        print(f"  issues        : {norm_val['issues']}")
    else:
        print("  (skipped — normalization not applied)")

    # 8. Final decision
    _sep("7. FINAL INDEXED TEXT")
    normalization_applied = False
    if norm_result["normalization_applied"]:
        norm_val = ExtractionValidator.validate(norm_result["normalized_text"], chunk_type_str)
        normalization_applied = norm_val["quality_score"] >= raw_val["quality_score"]

    final_text = norm_result["normalized_text"] if normalization_applied else clean_text
    print(f"  normalization_applied : {normalization_applied}")
    print(f"  raw quality_score     : {raw_val['quality_score']}")
    if norm_result["normalization_applied"]:
        norm_val2 = ExtractionValidator.validate(norm_result["normalized_text"], chunk_type_str)
        print(f"  normalized quality    : {norm_val2['quality_score']}")
    print()
    print(final_text)

    # 9. Structured fields
    _sep("8. STRUCTURED FIELDS")
    sf = norm_result.get("structured_fields", {})
    if sf:
        for k, v in sf.items():
            if k != "medications":
                print(f"  {k}: {v}")
        if "medications" in sf:
            print("  medications:")
            for med in sf["medications"]:
                print(f"    - {med}")
    else:
        print("  (none)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/debug_extraction_quality.py <path/to/file.pdf>")
        sys.exit(1)
    main(sys.argv[1])
