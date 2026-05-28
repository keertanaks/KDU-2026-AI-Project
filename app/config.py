import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / "config" / ".env")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_USER = os.getenv("DB_USER", "healthcare_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "secure_password")
DB_NAME = os.getenv("DB_NAME", "healthcare_rag")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", "9200"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# OpenRouter OCR configuration for handwritten documents.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OCR_MODEL = os.getenv("OCR_MODEL", "baidu/qianfan-ocr-fast:free")

# LangSmith — wire into the env vars LangGraph/LangChain look for automatically.
# Automatic LangChain tracing remains disabled; manual PHI-safe traces use the
# LangSmith client directly.
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "")
LANGCHAIN_PROJECT = os.getenv("LANGCHAIN_PROJECT", "healthcare-rag")
LANGSMITH_ENDPOINT = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
os.environ["LANGCHAIN_TRACING_V2"] = "false"

AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "healthcare-rag-docs")
KMS_KEY_ID = os.getenv("KMS_KEY_ID", "")

USE_LOCAL_STORAGE = os.getenv("USE_LOCAL_STORAGE", "true").lower() == "true"
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "")

# Embedding provider: "openai" (production) or "local" (dev only, no API key needed)
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "openai")
LOCAL_EMBEDDING_MODEL = os.getenv("LOCAL_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

# Environment & security configuration
APP_ENV = os.getenv("APP_ENV", "development")  # "development" or "production"
IS_HTTPS = os.getenv("IS_HTTPS", "false").lower() == "true"
