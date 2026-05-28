import os
from opensearchpy import OpenSearch
from opensearchpy.helpers import bulk


# Production index: 1536-d OpenAI embeddings (nmslib HNSW)
_PRODUCTION_INDEX = "healthcare_chunks"
_PRODUCTION_DIMS = 1536

# Development-only index: 384-d local sentence-transformer embeddings
# Kept strictly separate from production index to avoid dimension mismatch.
_LOCAL_INDEX = "healthcare_chunks_local"
_LOCAL_DIMS = 384


class Indexer:
    """
    OpenSearch indexer.  Selects the correct index and vector dimension based
    on EMBEDDING_PROVIDER:

      openai (default)  →  healthcare_chunks       (1536-d, production)
      local             →  healthcare_chunks_local  (384-d, dev only)

    The two indices are NEVER mixed.  384-d local vectors must not be written
    to the 1536-d production index and vice-versa.
    """

    def __init__(self):
        provider = os.getenv("EMBEDDING_PROVIDER", "openai").lower()

        if provider == "local":
            self.index_name = _LOCAL_INDEX
            self._dimensions = _LOCAL_DIMS
        else:
            self.index_name = _PRODUCTION_INDEX
            self._dimensions = _PRODUCTION_DIMS

        self.client = OpenSearch(
            hosts=[{
                "host": os.getenv("OPENSEARCH_HOST", "localhost"),
                "port": int(os.getenv("OPENSEARCH_PORT", "9200")),
            }],
            http_auth=None,
            use_ssl=False,
            verify_certs=False,
        )

    def ensure_index(self) -> None:
        """Create index with nmslib HNSW mapping if it doesn't exist."""
        if self.client.indices.exists(index=self.index_name):
            return

        mapping = {
            "settings": {
                "index.knn": True,
                "number_of_shards": 1,
                "number_of_replicas": 0,
            },
            "mappings": {
                "properties": {
                    "chunk_id": {"type": "keyword"},
                    "doc_id": {"type": "keyword"},
                    "text": {"type": "text"},
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": self._dimensions,
                        "method": {
                            "name": "hnsw",
                            "space_type": "l2",
                            "engine": "nmslib",
                            "parameters": {"ef_construction": 256, "m": 16},
                        },
                    },
                    "doc_type": {"type": "keyword"},
                    "date": {"type": "date"},
                    "phi_spans": {"type": "text"},
                    "acl": {"type": "keyword"},
                },
            },
        }

        self.client.indices.create(index=self.index_name, body=mapping)

    def index_chunks(self, chunks: list) -> int:
        """Bulk index chunks. Returns number of successfully indexed documents."""
        if not chunks:
            return 0

        actions = [
            {
                "_index": self.index_name,
                "_id": chunk["chunk_id"],
                "_source": chunk,
            }
            for chunk in chunks
        ]

        success_count, errors = bulk(self.client, actions, raise_on_error=False)

        if errors:
            print(f"Indexing errors: {errors}")

        return success_count
