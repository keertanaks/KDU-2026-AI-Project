"""
Re-tag phi_spans for all existing chunks in OpenSearch using the current
PhiTagger (with medication allowlist and date false-positive filter).

Updates phi_spans in-place — no re-chunking or re-embedding needed.

Usage:
    python scripts/retag_phi_spans.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "config" / ".env")

from opensearchpy import OpenSearch
from opensearchpy.helpers import bulk, scan

from app.ingestion.phi_tagger import PhiTagger
from app.ingestion.indexer import Indexer


def main() -> None:
    indexer = Indexer()
    client = indexer.client
    index = indexer.index_name

    print(f"Index: {index}")

    phi = PhiTagger()

    docs = list(scan(client, index=index, query={"query": {"match_all": {}}}))
    print(f"Found {len(docs)} chunks to re-tag")

    actions = []
    span_counts = []
    for doc in docs:
        text = doc["_source"].get("text", "")
        spans = phi.tag(text)
        span_counts.append(len(spans))
        actions.append({
            "_op_type": "update",
            "_index": doc["_index"],
            "_id": doc["_id"],
            "doc": {"phi_spans": json.dumps([s.to_dict() for s in spans])},
        })

    if not actions:
        print("Nothing to update.")
        return

    success, errors = bulk(client, actions, raise_on_error=False)
    print(f"Updated: {success}  Errors: {len(errors) if errors else 0}")
    print(f"Avg spans per chunk: {sum(span_counts) / len(span_counts):.1f}")
    if errors:
        for e in errors[:5]:
            print(f"  Error: {e}")


if __name__ == "__main__":
    main()
