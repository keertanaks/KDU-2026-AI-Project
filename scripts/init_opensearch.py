"""Initialize OpenSearch — create healthcare_chunks index with HNSW mapping."""
import sys
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "config" / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent))

from opensearchpy import OpenSearch

INDEX_NAME = "healthcare_chunks"

MAPPING = {
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
        }
    },
}


def init_opensearch():
    host = os.getenv("OPENSEARCH_HOST", "localhost")
    port = int(os.getenv("OPENSEARCH_PORT", "9200"))

    client = OpenSearch(
        hosts=[{"host": host, "port": port}],
        http_auth=("admin", "admin"),
        use_ssl=False,
        verify_certs=False,
    )

    info = client.info()
    print(f"✅ Connected to OpenSearch: {info['version']['number']}")

    if client.indices.exists(index=INDEX_NAME):
        print(f"ℹ️  Index '{INDEX_NAME}' already exists — skipping creation.")
    else:
        client.indices.create(index=INDEX_NAME, body=MAPPING)
        print(f"✅ Index '{INDEX_NAME}' created with HNSW + BM25 mapping.")

    mapping_info = client.indices.get_mapping(index=INDEX_NAME)
    props = mapping_info[INDEX_NAME]["mappings"]["properties"]
    print(f"   Fields: {list(props.keys())}")


if __name__ == "__main__":
    init_opensearch()
