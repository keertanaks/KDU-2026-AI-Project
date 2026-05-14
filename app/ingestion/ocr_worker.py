import base64
import logging
import os
import time
import pytesseract
import numpy as np
import fitz
import cv2
from openai import OpenAI, RateLimitError
from app.ingestion.classifier import DocType
from app.ingestion.preprocessor import PreprocessingPipeline

logger = logging.getLogger(__name__)

# Set tesseract binary path from env (needed on Windows)
_tess_cmd = os.getenv("TESSERACT_CMD", "")
if _tess_cmd:
    pytesseract.pytesseract.tesseract_cmd = _tess_cmd


class OCRWorker:
    def __init__(self):
        self._openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        self._openrouter_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        self._openrouter_model = os.getenv("OCR_MODEL", "baidu/qianfan-ocr-fast:free")

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
        """Handwritten OCR via OpenRouter Qianfan, falling back to Tesseract."""
        if self._openrouter_key and "placeholder" not in self._openrouter_key:
            try:
                return self._extract_handwritten_openrouter(pdf_path)
            except Exception as exc:
                # Fall back to Tesseract so ingestion can continue when the remote
                # OCR API is unavailable or misconfigured.
                logger.warning("OpenRouter OCR failed, falling back to Tesseract: %s", exc)

        return self._extract_handwritten_tesseract(pdf_path)

    def _extract_handwritten_tesseract(self, pdf_path: str) -> dict:
        doc = fitz.open(pdf_path)
        full_text = ""
        all_lines = []
        for page_num in range(len(doc)):
            img = PreprocessingPipeline.preprocess(pdf_path, page_num)
            text = pytesseract.image_to_string(img, config="--oem 1 --psm 3")
            for line in text.splitlines():
                if line.strip():
                    all_lines.append({"text": line.strip(), "confidence": 0.0})
            full_text += text + "\n"
        doc.close()
        return {
            "text": full_text,
            "lines": all_lines,
            "doc_type": DocType.HANDWRITTEN,
            "success_rate": 0.0,
            "method": "Tesseract 5 (handwritten fallback)",
        }

    def _encode_image_to_data_url(self, img: np.ndarray) -> str:
        _, buffer = cv2.imencode(".png", img)
        return "data:image/png;base64," + base64.b64encode(buffer).decode("utf-8")

    def _extract_handwritten_openrouter(self, pdf_path: str) -> dict:
        doc = fitz.open(pdf_path)
        full_text = ""
        all_lines = []

        client = OpenAI(
            api_key=self._openrouter_key,
            base_url=self._openrouter_url,
        )

        for page_num in range(len(doc)):
            img = PreprocessingPipeline.preprocess(pdf_path, page_num)
            image_data_url = self._encode_image_to_data_url(img)

            max_retries = 5
            for attempt in range(max_retries):
                try:
                    response = client.chat.completions.create(
                        model=self._openrouter_model,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": (
                                            "Extract all handwritten text from the supplied image. "
                                            "Return only the recognized text, preserving line breaks. "
                                            "Do not add any extra explanation or metadata."
                                        ),
                                    },
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": image_data_url,
                                        },
                                    },
                                ],
                            }
                        ],
                        max_tokens=2048,
                        temperature=0.0,
                    )
                    break
                except RateLimitError as e:
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        logger.info("Rate limit on page %d, retrying in %ds (attempt %d/%d)", page_num, wait_time, attempt + 1, max_retries)
                        time.sleep(wait_time)
                    else:
                        raise

            choice = response.choices[0]
            message = getattr(choice, "message", None) or choice.get("message", {})
            content = getattr(message, "content", None) or message.get("content", "")
            if isinstance(content, list):
                page_text = "\n".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            else:
                page_text = str(content or "")

            page_text = page_text.strip()
            if page_text:
                for line in page_text.splitlines():
                    if line.strip():
                        all_lines.append({"text": line.strip(), "confidence": 1.0})
                full_text += page_text + "\n"

        doc.close()
        return {
            "text": full_text,
            "lines": all_lines,
            "doc_type": DocType.HANDWRITTEN,
            "success_rate": round(
                sum(l["confidence"] for l in all_lines) / len(all_lines)
                if all_lines else 0.0,
                4,
            ),
            "method": f"OpenRouter {self._openrouter_model}",
        }
