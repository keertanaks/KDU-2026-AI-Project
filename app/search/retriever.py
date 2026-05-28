import logging
import os
from typing import Dict, List

from opensearchpy import OpenSearch

logger = logging.getLogger(__name__)

# Carry-forward: index name driven by EMBEDDING_PROVIDER env var
_PRODUCTION_INDEX = "healthcare_chunks"
_LOCAL_INDEX = "healthcare_chunks_local"


class HybridRetriever:
    """
    BM25 + kNN dual search with Reciprocal Rank Fusion (RRF).

    Index selection mirrors Indexer — same EMBEDDING_PROVIDER env var:
        openai  →  healthcare_chunks        (1536-d)
        local   →  healthcare_chunks_local  (384-d)
    """

    def __init__(self):
        provider = os.getenv("EMBEDDING_PROVIDER", "openai").lower()
        self.index_name = _LOCAL_INDEX if provider == "local" else _PRODUCTION_INDEX

        self.client = OpenSearch(
            hosts=[{
                "host": os.getenv("OPENSEARCH_HOST", "localhost"),
                "port": int(os.getenv("OPENSEARCH_PORT", "9200")),
            }],
            http_auth=None,
            use_ssl=False,
            verify_certs=False,
        )

        logger.info("HybridRetriever index: %s", self.index_name)

    def retrieve(
        self,
        query_embedding: List[float],
        query_text: str,
        filters: Dict,
        k: int = 50,
    ) -> List[Dict]:
        """
        Run BM25 and kNN searches independently, fuse with RRF, return top-k.

        filters dict:
            acl  (List[str]) — pre-filter; only docs whose 'acl' field matches
                               at least one value in the list are returned.
        """
        must_filter: List[Dict] = []
        acl_values = filters.get("acl", [])
        if acl_values:
            must_filter.append({"terms": {"acl": acl_values}})

        bm25_hits = self._bm25_search(query_text, must_filter, k)
        knn_hits = self._knn_search(query_embedding, must_filter, k)

        logger.debug("BM25 hits: %d  kNN hits: %d", len(bm25_hits), len(knn_hits))

        return self._rrf_fuse(bm25_hits, knn_hits, k)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _bm25_search(self, query_text: str, must_filter: List[Dict], k: int) -> List[Dict]:
        body = {
            "query": {
                "bool": {
                    "must": [{"multi_match": {"query": query_text, "fields": ["text"]}}],
                    "filter": must_filter,
                }
            },
            "size": k,
        }
        try:
            resp = self.client.search(index=self.index_name, body=body)
            return resp["hits"]["hits"]
        except Exception as exc:
            logger.warning("BM25 search error: %s", exc)
            return []

    def _knn_search(
        self, query_embedding: List[float], must_filter: List[Dict], k: int
    ) -> List[Dict]:
        body: Dict = {
            "query": {
                "bool": {
                    "must": [{"knn": {"embedding": {"vector": query_embedding, "k": k}}}],
                    "filter": must_filter,
                }
            },
            "size": k,
        }
        try:
            resp = self.client.search(index=self.index_name, body=body)
            return resp["hits"]["hits"]
        except Exception as exc:
            logger.warning("kNN search error: %s", exc)
            return []

    @staticmethod
    def _rrf_fuse(
        bm25_hits: List[Dict], knn_hits: List[Dict], k: int, rrf_k: int = 60
    ) -> List[Dict]:
        """Reciprocal Rank Fusion — standard RRF with k=60."""
        scores: Dict[str, float] = {}
        all_hits: Dict[str, Dict] = {}

        for rank, hit in enumerate(bm25_hits):
            cid = hit["_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (rank + rrf_k)
            all_hits[cid] = hit

        for rank, hit in enumerate(knn_hits):
            cid = hit["_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (rank + rrf_k)
            all_hits.setdefault(cid, hit)

        sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
        result = []
        for cid in sorted_ids[:k]:
            hit = all_hits[cid]
            hit["rrf_score"] = scores[cid]
            result.append(hit)

        return result
