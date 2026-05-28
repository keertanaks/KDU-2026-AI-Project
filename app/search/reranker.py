import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class Reranker:
    """
    Cross-encoder reranker using BAAI/bge-reranker-base.

    Loaded lazily on first use so the FastAPI worker starts quickly.
    Model is downloaded from HuggingFace on first invocation (~250 MB).
    """

    _model = None  # class-level singleton

    def _load_model(self):
        if Reranker._model is None:
            from sentence_transformers import CrossEncoder
            logger.info("Loading BAAI/bge-reranker-base cross-encoder …")
            Reranker._model = CrossEncoder("BAAI/bge-reranker-base")
            logger.info("Cross-encoder loaded.")
        return Reranker._model

    def rerank(self, query: str, candidates: List[Dict], top_n: int = 5) -> List[Dict]:
        """
        Score each candidate with the cross-encoder and return top_n.

        Each candidate dict is expected to have a '_source' sub-dict with a 'text' key
        (standard OpenSearch hit format).
        """
        if not candidates:
            return []

        model = self._load_model()

        pairs = [[query, cand.get("_source", {}).get("text", "")] for cand in candidates]
        scores = model.predict(pairs)

        for cand, score in zip(candidates, scores):
            cand["rerank_score"] = float(score)

        candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
        logger.debug(
            "Reranked %d candidates; top score=%.4f", len(candidates), candidates[0]["rerank_score"]
        )
        return candidates[:top_n]
