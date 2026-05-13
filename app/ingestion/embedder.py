import os
from typing import List
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent.parent / "config" / ".env")


class Embedder:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = "text-embedding-3-small"
        self.dimensions = 1536

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple texts using OpenAI text-embedding-3-small."""
        if not texts:
            return []

        response = self.client.embeddings.create(
            model=self.model,
            input=texts,
            dimensions=self.dimensions,
        )

        embeddings = sorted(response.data, key=lambda x: x.index)
        return [e.embedding for e in embeddings]
