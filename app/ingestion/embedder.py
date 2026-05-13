"""
Embedding abstraction supporting two providers:

  EMBEDDING_PROVIDER=openai  (default / production)
      Uses OpenAI text-embedding-3-small, 1536 dimensions.
      Requires a valid OPENAI_API_KEY.
      Writes to OpenSearch index: healthcare_chunks

  EMBEDDING_PROVIDER=local  (development only)
      Uses sentence-transformers/all-MiniLM-L6-v2, 384 dimensions.
      No API key required.
      Writes to a SEPARATE OpenSearch index: healthcare_chunks_local
      384-d local vectors must NEVER be mixed into the 1536-d production index.

Switch provider via config/.env:
    EMBEDDING_PROVIDER=local
    LOCAL_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
"""

import os
from typing import List
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent.parent / "config" / ".env")


class Embedder:
    """
    Provider-aware embedder.  Instantiate once; provider is fixed at construction.
    """

    # Dimensions per provider — used by Indexer to pick the right index/mapping.
    DIMENSIONS = {
        "openai": 1536,
        "local": 384,
    }

    def __init__(self):
        self.provider = os.getenv("EMBEDDING_PROVIDER", "openai").lower()

        if self.provider == "openai":
            from openai import OpenAI
            self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            self.model = "text-embedding-3-small"
            self.dimensions = 1536
        elif self.provider == "local":
            # Deferred import — sentence-transformers is a heavy dependency.
            from sentence_transformers import SentenceTransformer
            model_name = os.getenv(
                "LOCAL_EMBEDDING_MODEL",
                "sentence-transformers/all-MiniLM-L6-v2",
            )
            self._st_model = SentenceTransformer(model_name)
            self.model = model_name
            self.dimensions = 384
        else:
            raise ValueError(
                f"Unknown EMBEDDING_PROVIDER '{self.provider}'. "
                "Set to 'openai' (production) or 'local' (dev only)."
            )

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Embed a list of texts.  Returns List[List[float]] matching input order.
        Provider is selected at construction time via EMBEDDING_PROVIDER env var.
        """
        if not texts:
            return []

        if self.provider == "openai":
            return self._embed_openai(texts)
        return self._embed_local(texts)

    def _embed_openai(self, texts: List[str]) -> List[List[float]]:
        """OpenAI text-embedding-3-small — production path."""
        response = self.client.embeddings.create(
            model=self.model,
            input=texts,
            dimensions=self.dimensions,
        )
        embeddings = sorted(response.data, key=lambda x: x.index)
        return [e.embedding for e in embeddings]

    def _embed_local(self, texts: List[str]) -> List[List[float]]:
        """sentence-transformers all-MiniLM-L6-v2 — local development only."""
        vectors = self._st_model.encode(texts, normalize_embeddings=True)
        return [v.tolist() for v in vectors]
