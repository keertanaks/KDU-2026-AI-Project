"""
Phase 2.2 Search Pipeline — LangGraph state machine.

Node sequence:
    normalize_query → resolve_acl → embed_query → retrieve
    → rerank → mask → respond → END

State is a plain TypedDict; each node receives the full state and
returns an updated copy.  The 'db' key holds a live SQLAlchemy session
that is opened by the caller and closed after invoke() returns.
"""

import logging
import time
from typing import Any, Dict, List

from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from app.compliance.acl_resolver import ACLResolver
from app.compliance.audit_logger import AuditLogger
from app.ingestion.embedder import Embedder
from app.search.masker import ResponseMasker
from app.search.reranker import Reranker
from app.search.retriever import HybridRetriever

logger = logging.getLogger(__name__)


class SearchState(TypedDict):
    query_text: str
    user_id: str
    role: str
    db: Any                    # SQLAlchemy Session — not serialisable, passed by ref
    normalized_query: str
    user_acl: List[str]
    query_embedding: List[float]
    candidates: List[Dict]
    reranked: List[Dict]
    masked_results: List[Dict]
    latency_ms: int
    start_time: float


class SearchGraph:
    """
    Compiled LangGraph workflow for the search pipeline.

    Components (embedder, retriever, reranker) are singletons instantiated
    at construction time so model weights are loaded only once per process.
    """

    def __init__(self):
        self.embedder = Embedder()
        self.retriever = HybridRetriever()
        self.reranker = Reranker()
        self._graph = self._build_graph()
        logger.info("SearchGraph ready (provider=%s)", self.embedder.provider)

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def _build_graph(self):
        wf = StateGraph(SearchState)

        wf.add_node("normalize_query", self._normalize_query)
        wf.add_node("resolve_acl", self._resolve_acl)
        wf.add_node("embed_query", self._embed_query)
        wf.add_node("retrieve", self._retrieve)
        wf.add_node("rerank", self._rerank)
        wf.add_node("mask", self._mask)
        wf.add_node("respond", self._respond)

        wf.set_entry_point("normalize_query")
        wf.add_edge("normalize_query", "resolve_acl")
        wf.add_edge("resolve_acl", "embed_query")
        wf.add_edge("embed_query", "retrieve")
        wf.add_edge("retrieve", "rerank")
        wf.add_edge("rerank", "mask")
        wf.add_edge("mask", "respond")
        wf.add_edge("respond", END)

        return wf.compile()

    # ------------------------------------------------------------------
    # Node implementations
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_query(state: SearchState) -> Dict:
        normalized = state["query_text"].strip().lower()
        logger.debug("normalize_query: '%s' → '%s'", state["query_text"], normalized)
        return {"normalized_query": normalized}

    @staticmethod
    def _resolve_acl(state: SearchState) -> Dict:
        acl = ACLResolver.resolve_acl(state["db"], state["user_id"])
        logger.debug("resolve_acl user=%s role=%s acl=%s", state["user_id"], state["role"], acl)
        return {"user_acl": acl}

    def _embed_query(self, state: SearchState) -> Dict:
        embedding = self.embedder.embed_batch([state["normalized_query"]])[0]
        logger.debug("embed_query: %d-dim vector", len(embedding))
        return {"query_embedding": embedding}

    def _retrieve(self, state: SearchState) -> Dict:
        candidates = self.retriever.retrieve(
            state["query_embedding"],
            state["normalized_query"],
            filters={"acl": state["user_acl"]},
            k=50,
        )
        logger.debug("retrieve: %d candidates", len(candidates))
        for i, c in enumerate(candidates[:3]):
            logger.debug(
                "  candidate[%d] id=%s rrf=%.5f text_preview=%s",
                i, c["_id"], c.get("rrf_score", 0),
                c.get("_source", {}).get("text", "")[:80].replace("\n", " "),
            )
        return {"candidates": candidates}

    def _rerank(self, state: SearchState) -> Dict:
        reranked = self.reranker.rerank(
            state["normalized_query"],
            state["candidates"],
            top_n=5,
        )
        logger.debug("rerank: top scores %s", [f"{r['rerank_score']:.4f}" for r in reranked])
        return {"reranked": reranked}

    @staticmethod
    def _mask(state: SearchState) -> Dict:
        masked_results = []
        for chunk in state["reranked"]:
            src = chunk.get("_source", {})
            phi_spans = src.get("phi_spans", [])
            text = src.get("text", "")
            masked_text = ResponseMasker.mask(text, phi_spans, state["role"])
            masked_results.append({
                "text": masked_text,
                "doc_id": src.get("doc_id", ""),
                "score": chunk.get("rerank_score", 0.0),
            })
        logger.debug("mask: %d results, role=%s", len(masked_results), state["role"])
        return {"masked_results": masked_results}

    @staticmethod
    def _respond(state: SearchState) -> Dict:
        latency_ms = int((time.time() - state["start_time"]) * 1000)
        doc_ids = [r["doc_id"] for r in state["masked_results"]]
        masking_label = (
            "none"
            if state["role"] == "treating_clinician"
            else "applied"
        )

        try:
            AuditLogger.log_query(
                state["db"],
                state["user_id"],
                state["role"],
                state["query_text"],
                doc_ids,
                masking_label,
                latency_ms,
            )
        except Exception as exc:
            logger.warning("Audit log failed (non-fatal): %s", exc)

        logger.info(
            "search done query='%s' role=%s results=%d latency=%dms",
            state["query_text"][:60],
            state["role"],
            len(doc_ids),
            latency_ms,
        )
        return {"latency_ms": latency_ms}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def invoke(self, query_text: str, user_id: str, role: str, db: Any) -> Dict:
        """Execute the full search pipeline and return the final SearchState."""
        initial: SearchState = {
            "query_text": query_text,
            "user_id": user_id,
            "role": role,
            "db": db,
            "normalized_query": "",
            "user_acl": [],
            "query_embedding": [],
            "candidates": [],
            "reranked": [],
            "masked_results": [],
            "latency_ms": 0,
            "start_time": time.time(),
        }
        return self._graph.invoke(initial)
