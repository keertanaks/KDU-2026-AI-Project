import fitz
import cv2
import numpy as np
from enum import Enum


class DocType(str, Enum):
    TYPED = "typed"
    SCANNED = "scanned"
    HANDWRITTEN = "handwritten"


class DocumentClassifier:
    @staticmethod
    def classify(pdf_path: str) -> tuple:
        """
        Classify as TYPED, SCANNED, or HANDWRITTEN.
        Step 1: PyMuPDF text probe → TYPED if >100 chars
        Step 2: Contrast + edges + density → SCANNED vs HANDWRITTEN
        """
        doc = fitz.open(pdf_path)
        page = doc[0]

        text = page.get_text()
        if len(text.strip()) > 100:
            doc.close()
            return DocType.TYPED, {"confidence": 0.99}

        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img_array = np.frombuffer(pix.samples, dtype=np.uint8)
        img_array = img_array.reshape((pix.height, pix.width, pix.n))

        if pix.n == 4:
            img_rgb = cv2.cvtColor(img_array, cv2.COLOR_RGBA2BGR)
        else:
            img_rgb = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)

        scores = DocumentClassifier._compute_heuristics(img_rgb)
        doc.close()

        doc_type = DocType.SCANNED if scores["is_scanned"] else DocType.HANDWRITTEN
        return doc_type, scores

    @staticmethod
    def _compute_heuristics(img: np.ndarray) -> dict:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        contrast = float(np.std(gray))
        edges = cv2.Canny(gray, 50, 150)
        edge_density = float(np.sum(edges) / edges.size)

        _, binary = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)
        text_density = float(np.sum(binary) / binary.size)

        is_scanned = (contrast > 30) and (edge_density < 0.05)

        return {
            "contrast_std": contrast,
            "edge_density": edge_density,
            "text_density": text_density,
            "is_scanned": is_scanned,
            "confidence": 0.85 if is_scanned else 0.90,
        }
