import os
import shutil
from pathlib import Path
from typing import BinaryIO


class LocalStorageService:
    """File-system backed storage for local development."""

    def __init__(self):
        self.base_dir = Path(os.getcwd()) / "uploads"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def upload_pdf(self, file_obj: BinaryIO, doc_id: str) -> str:
        dest = self.base_dir / f"{doc_id}.pdf"
        with open(dest, "wb") as f:
            shutil.copyfileobj(file_obj, f)
        return f"local://{dest}"

    def download_pdf(self, doc_id: str) -> bytes:
        path = self.base_dir / f"{doc_id}.pdf"
        return path.read_bytes()

    def delete_pdf(self, doc_id: str) -> None:
        path = self.base_dir / f"{doc_id}.pdf"
        if path.exists():
            path.unlink()

    def get_local_path(self, doc_id: str) -> str:
        return str(self.base_dir / f"{doc_id}.pdf")
