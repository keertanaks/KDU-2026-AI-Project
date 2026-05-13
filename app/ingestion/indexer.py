import os
from opensearchpy import OpenSearch
from opensearchpy.helpers import bulk


class Indexer:
    def __init__(self):
        self.client = OpenSearch(
            hosts=[{
                "host": os.getenv("OPENSEARCH_HOST", "localhost"),
                "port": int(os.getenv("OPENSEARCH_PORT", "9200")),
            }],
            http_auth=None,
            use_ssl=False,
            verify_certs=False,
        )
        self.index_name = "healthcare_chunks"

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
                        "dimension": 1536,
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
