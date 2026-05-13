import os
import pytesseract
import numpy as np
import fitz
from app.ingestion.classifier import DocType
from app.ingestion.preprocessor import PreprocessingPipeline

# Set tesseract binary path from env (needed on Windows)
_tess_cmd = os.getenv("TESSERACT_CMD", "")
if _tess_cmd:
    pytesseract.pytesseract.tesseract_cmd = _tess_cmd


class OCRWorker:
    def __init__(self):
        # Lazy-load PaddleOCR to avoid slow import on startup
        self._paddle = None

    def _get_paddle(self):
        if self._paddle is None:
            from paddleocr import PaddleOCR
            self._paddle = PaddleOCR(use_angle_cls=True, lang="en")
        return self._paddle

    def extract_text(self, pdf_path: str, doc_type: DocType) -> dict:
        """Route OCR based on document type."""
        if doc_type == DocType.TYPED:
            return self._extract_typed(pdf_path)
        elif doc_type == DocType.SCANNED:
            return self._extract_scanned(pdf_path)
        else:
            return self._extract_handwritten(pdf_path)

    def _extract_typed(self, pdf_path: str) -> dict:
        """PyMuPDF extraction (99%+ accuracy)."""
        doc = fitz.open(pdf_path)
        full_text = "".join(page.get_text() + "\n" for page in doc)
        doc.close()
        return {
            "text": full_text,
            "doc_type": DocType.TYPED,
            "success_rate": 0.99,
            "method": "PyMuPDF",
        }

    def _extract_scanned(self, pdf_path: str) -> dict:
        """Tesseract OCR (92-95% accuracy)."""
        doc = fitz.open(pdf_path)
        full_text = ""
        for page_num in range(len(doc)):
            img = PreprocessingPipeline.preprocess(pdf_path, page_num)
            text = pytesseract.image_to_string(img, config="--oem 1 --psm 3")
            full_text += text + "\n"
        doc.close()
        return {
            "text": full_text,
            "doc_type": DocType.SCANNED,
            "success_rate": 0.93,
            "method": "Tesseract 5",
        }

    def _extract_handwritten(self, pdf_path: str) -> dict:
        """PaddleOCR (85-90% accuracy)."""
        paddle = self._get_paddle()
        doc = fitz.open(pdf_path)
        full_text = ""
        all_lines = []  # [{text, confidence}] across all pages
        for page_num in range(len(doc)):
            img = PreprocessingPipeline.preprocess(pdf_path, page_num)
            results = paddle.ocr(img, cls=True)
            if results and results[0]:
                for line in results[0]:
                    text, confidence = line[1][0], float(line[1][1])
                    all_lines.append({"text": text, "confidence": confidence})
                    full_text += text + "\n"
        doc.close()
        avg_confidence = (
            sum(l["confidence"] for l in all_lines) / len(all_lines)
            if all_lines else 0.0
        )
        return {
            "text": full_text,
            "lines": all_lines,
            "doc_type": DocType.HANDWRITTEN,
            "success_rate": round(avg_confidence, 4),
            "method": "PaddleOCR PP-OCRv5",
        }
