#!/usr/bin/env python3
"""
One-time cleanup script for duplicate chunks in OpenSearch index.

Usage:
    python scripts/cleanup_duplicate_chunks.py --dry-run
    python scripts/cleanup_duplicate_chunks.py --apply

This script:
- Connects to the active OpenSearch index (based on EMBEDDING_PROVIDER)
- Groups chunks by normalized text fingerprint
- For each duplicate group, keeps the best copy and deletes others
- Supports dry-run mode to preview changes
"""

import argparse
import hashlib
import logging
import os
import re
import sys
from collections import defaultdict
from typing import Dict, List, Tuple

from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError

# Add app to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Load environment variables from config/.env
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', 'config', '.env'))

from app.ingestion.indexer import Indexer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def normalize_text(text: str) -> str:
    """Normalize text for fingerprinting: lowercase, strip whitespace, normalize spaces."""
    if not text:
        return ""
    # Convert to lowercase
    text = text.lower()
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text.strip())
    # Remove common OCR artifacts
    text = re.sub(r'[^\w\s.,;:!?()-]', '', text)
    return text


def compute_text_hash(text: str) -> str:
    """Compute SHA256 hash of normalized text."""
    normalized = normalize_text(text)
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def assess_chunk_quality(doc: Dict) -> Tuple[int, str]:
    """
    Assess chunk quality for tie-breaking.
    Returns (quality_score, tiebreaker_string)

    Higher quality_score is better.
    Quality factors:
    - Text length (longer = better OCR)
    - Word count (more words = more complete)
    - Presence of common medical terms (rough heuristic)
    """
    source = doc.get('_source', {})
    text = source.get('text', '')

    # Quality score
    text_len = len(text)
    word_count = len(text.split())
    medical_terms = len(re.findall(r'\b(dose|mg|tablet|patient|diagnosis|treatment)\b', text.lower()))

    quality_score = text_len + word_count * 10 + medical_terms * 50

    # Tiebreaker: prefer smaller chunk_id alphabetically
    chunk_id = source.get('chunk_id', '')

    return quality_score, chunk_id


def find_duplicates(client: OpenSearch, index_name: str) -> Dict[str, List[Dict]]:
    """Find duplicate chunks by normalized text hash."""
    duplicates = defaultdict(list)

    # Scroll through all documents
    query = {
        "query": {"match_all": {}},
        "_source": ["chunk_id", "doc_id", "text", "doc_type", "date"],
        "size": 1000
    }

    response = client.search(index=index_name, body=query, scroll='5m')
    scroll_id = response['_scroll_id']
    hits = response['hits']['hits']

    while hits:
        for hit in hits:
            doc_id = hit['_id']
            source = hit.get('_source', {})
            text = source.get('text', '')

            # Check if fingerprint exists (newer docs)
            fingerprint = source.get('fingerprint') or source.get('content_hash') or source.get('text_hash')
            if fingerprint:
                group_key = fingerprint
            else:
                # Use normalized text hash for older docs
                group_key = compute_text_hash(text)

            duplicates[group_key].append({
                '_id': doc_id,
                '_source': source,
                'quality_score': assess_chunk_quality(hit)[0],
                'tiebreaker': assess_chunk_quality(hit)[1]
            })

        # Get next batch
        response = client.scroll(scroll_id=scroll_id, scroll='5m')
        scroll_id = response['_scroll_id']
        hits = response['hits']['hits']

    # Clear scroll
    client.clear_scroll(scroll_id=scroll_id)

    # Filter to only groups with duplicates
    return {k: v for k, v in duplicates.items() if len(v) > 1}


def select_best_chunk(chunks: List[Dict]) -> Tuple[Dict, List[Dict]]:
    """Select the best chunk to keep, return (keep, delete_list)."""
    if len(chunks) == 1:
        return chunks[0], []

    # Sort by quality_score desc, then tiebreaker asc
    sorted_chunks = sorted(
        chunks,
        key=lambda x: (-x['quality_score'], x['tiebreaker'])
    )

    keep = sorted_chunks[0]
    delete = sorted_chunks[1:]

    return keep, delete


def main():
    parser = argparse.ArgumentParser(description='Clean up duplicate chunks in OpenSearch')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--apply', action='store_true', help='Actually apply the changes')
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("Must specify --dry-run or --apply")
        sys.exit(1)

    if args.dry_run and args.apply:
        print("Cannot specify both --dry-run and --apply")
        sys.exit(1)

    # Get indexer to determine index name
    indexer = Indexer()
    index_name = indexer.index_name
    client = indexer.client

    logger.info(f"Using OpenSearch index: {index_name}")

    # Check if index exists
    if not client.indices.exists(index=index_name):
        logger.error(f"Index {index_name} does not exist")
        sys.exit(1)

    # Find duplicates
    logger.info("Scanning for duplicate chunks...")
    duplicates = find_duplicates(client, index_name)

    if not duplicates:
        logger.info("No duplicate chunks found")
        return

    total_groups = len(duplicates)
    total_duplicates = sum(len(chunks) - 1 for chunks in duplicates.values())

    logger.info(f"Found {total_groups} duplicate groups with {total_duplicates} total duplicates")

    # Process each group
    to_delete = []
    kept_count = 0

    for group_key, chunks in duplicates.items():
        keep, delete = select_best_chunk(chunks)

        kept_count += 1
        to_delete.extend(delete)

        if args.dry_run:
            print(f"\nGroup {group_key[:16]}...: {len(chunks)} chunks")
            print(f"  KEEP: {keep['_id']} (score: {keep['quality_score']})")
            for d in delete:
                print(f"  DELETE: {d['_id']} (score: {d['quality_score']})")

    # Summary
    print(f"\nSummary:")
    print(f"  Duplicate groups: {total_groups}")
    print(f"  Chunks to keep: {kept_count}")
    print(f"  Chunks to delete: {len(to_delete)}")

    if not args.apply:
        print("\nThis was a dry run. Use --apply to actually delete duplicates.")
        return

    # Apply changes
    if not to_delete:
        logger.info("No chunks to delete")
        return

    logger.info(f"Deleting {len(to_delete)} duplicate chunks...")

    # Delete in batches
    batch_size = 100
    deleted_count = 0

    for i in range(0, len(to_delete), batch_size):
        batch = to_delete[i:i + batch_size]

        bulk_body = []
        for chunk in batch:
            bulk_body.append({"delete": {"_index": index_name, "_id": chunk['_id']}})

        try:
            response = client.bulk(body=bulk_body)
            if response.get('errors'):
                logger.warning(f"Some deletions failed in batch {i//batch_size + 1}")
            else:
                deleted_count += len(batch)
                logger.info(f"Deleted batch {i//batch_size + 1}: {len(batch)} chunks")
        except Exception as e:
            logger.error(f"Failed to delete batch {i//batch_size + 1}: {e}")

    logger.info(f"Cleanup complete. Deleted {deleted_count} duplicate chunks.")

    # Verify specific Emily Moore chunks
    emily_ids = [
        'f7438918-0656-45a8-b521-f9c7a008760a',
        '8eb439b4-2d17-427b-9daf-bb6c64983e34',
        '54499712-a2d5-4b49-81f9-40922d36f44c'
    ]

    remaining_emily = 0
    for eid in emily_ids:
        try:
            client.get(index=index_name, id=eid)
            remaining_emily += 1
        except NotFoundError:
            pass

    if remaining_emily > 1:
        logger.warning(f"Emily Moore still has {remaining_emily} chunks remaining - manual review needed")
    elif remaining_emily == 1:
        logger.info("Emily Moore deduplication successful - 1 chunk remaining")
    else:
        logger.warning("Emily Moore chunks all deleted - this shouldn't happen")


if __name__ == '__main__':
    main()