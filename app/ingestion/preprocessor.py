import cv2
import numpy as np
import fitz


class PreprocessingPipeline:
    """Preprocessing for scanned/handwritten pages before OCR."""

    @staticmethod
    def preprocess(pdf_path: str, page_num: int = 0, dpi: int = 300) -> np.ndarray:
        """
        Pipeline:
        1. Render at 300 DPI
        2. Crop bounding box
        3. Grayscale
        4. CLAHE contrast
        5. Sharpen
        6. Safe deskew
        """
        doc = fitz.open(pdf_path)
        page = doc[page_num]
        matrix = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=matrix, alpha=False)

        img = np.frombuffer(pix.samples, dtype=np.uint8)
        img = img.reshape((pix.height, pix.width, pix.n))
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        doc.close()

        img = PreprocessingPipeline._crop_bounding_box(img)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
        sharpened = cv2.filter2D(enhanced, -1, kernel)

        angle = PreprocessingPipeline._detect_skew(sharpened)
        if abs(angle) > 5:
            rows, cols = sharpened.shape
            M = cv2.getRotationMatrix2D((cols / 2, rows / 2), angle, 1)
            sharpened = cv2.warpAffine(sharpened, M, (cols, rows))

        return sharpened

    @staticmethod
    def _crop_bounding_box(img: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return img

        x, y, w, h = cv2.boundingRect(max(contours, key=cv2.contourArea))
        return img[
            max(0, y - 10) : min(img.shape[0], y + h + 10),
            max(0, x - 10) : min(img.shape[1], x + w + 10),
        ]

    @staticmethod
    def _detect_skew(img: np.ndarray) -> float:
        edges = cv2.Canny(img, 50, 150)
        lines = cv2.HoughLines(edges, 1, np.pi / 180, 100)

        if lines is None:
            return 0.0

        angles = [line[0][1] * 180 / np.pi - 90 for line in lines[:20]]
        return float(np.median(angles))
