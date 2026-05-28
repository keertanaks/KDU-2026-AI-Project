import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent.parent / "config" / ".env")


def get_storage_service():
    """Return LocalStorageService or S3Service based on USE_LOCAL_STORAGE env var."""
    if os.getenv("USE_LOCAL_STORAGE", "true").lower() == "true":
        from app.storage.local_storage_service import LocalStorageService
        return LocalStorageService()
    from app.storage.s3_service import S3Service
    return S3Service()
