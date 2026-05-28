"""
pdfplumber-based table extractor for typed PDFs.

Returns a list of tables, where each table is a list of rows,
and each row is a list of cell strings (None for empty cells).

Falls back gracefully to [] if pdfplumber is not installed or the PDF
has no detectable table grid lines.
"""


class LayoutExtractor:
    """Extract tables from a typed PDF using pdfplumber."""

    @staticmethod
    def extract_tables(pdf_path: str) -> list:
        """
        Returns list[list[list[str|None]]] — one entry per table found across
        all pages.  Returns [] on any error or if pdfplumber is unavailable.
        """
        try:
            import pdfplumber  # noqa: PLC0415
        except ImportError:
            return []

        all_tables: list = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables()
                    if tables:
                        all_tables.extend(tables)
        except Exception:
            return []

        return all_tables
