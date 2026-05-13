"""
Phase 2.2 Search Pipeline — LangGraph state machine.
Phase 3/4 additions: administrator 403 guard, grounded answer generation.

Node sequence:
    normalize_query → resolve_acl → embed_query → retrieve
    → rerank → mask → generate_answer → respond → END

State is a plain TypedDict; each node receives the full state and
returns an updated copy.  The 'db' key holds a live SQLAlchemy session
that is opened by the caller and closed after invoke() returns.
"""

import logging
import time
from typing import Any, Dict, List

from fastapi import HTTPException
from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from app.auth.models import UserRole
from app.compliance.acl_resolver import ACLResolver
from app.compliance.audit_logger import AuditLogger
from app.ingestion.embedder import Embedder
from app.search.answer_generator import AnswerGenerator
from app.search.masker import ResponseMasker
from app.search.reranker import Reranker
from app.search.retriever import HybridRetriever

logger = logging.getLogger(__name__)


class SearchState(TypedDict):
    query_text: str
    user_id: str
    role: str
    db: Any                     # SQLAlchemy Session — not serialisable, passed by ref
    normalized_query: str
    user_acl: List[str]
    query_embedding: List[float]
    candidates: List[Dict]
    reranked: List[Dict]
    masked_results: List[Dict]
    generated_answer: str
    answer_generation_status: str   # "success" | "skipped" | "failed"
    sources: List[str]
    latency_ms: int
    search_latency_ms: int      # retrieval + rerank + masking only
    answer_latency_ms: int      # answer generation only
    start_time: float


class SearchGraph:
    """
    Compiled LangGraph workflow for the search pipeline.

    Components (embedder, retriever, reranker, answer_generator) are singletons
    instantiated at construction time so model weights are loaded only once.
    """

    def __init__(self):
        self.embedder = Embedder()
        self.retriever = HybridRetriever()
        self.reranker = Reranker()
        self.answer_generator = AnswerGenerator()
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
        wf.add_node("generate_answer", self._generate_answer)
        wf.add_node("respond", self._respond)

        wf.set_entry_point("normalize_query")
        wf.add_edge("normalize_query", "resolve_acl")
        wf.add_edge("resolve_acl", "embed_query")
        wf.add_edge("embed_query", "retrieve")
        wf.add_edge("retrieve", "rerank")
        wf.add_edge("rerank", "mask")
        wf.add_edge("mask", "generate_answer")
        wf.add_edge("generate_answer", "respond")
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
        # Phase 3: administrators are blocked from content search.
        role_val = state["role"]
        try:
            role_enum = UserRole(role_val)
        except ValueError:
            role_enum = None

        if role_enum == UserRole.ADMINISTRATOR or role_val == "administrator":
            raise HTTPException(
                status_code=403,
                detail="Administrator role cannot perform searches.",
            )

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

    def _generate_answer(self, state: SearchState) -> Dict:
        """
        Calls AnswerGenerator with the reranked (pre-masking) chunks so it can
        build its own reversible placeholder context.  The masked_results
        (containing <TYPE_REDACTED> tokens) are for UI display only and are
        NOT sent to the LLM.

        search_latency_ms is captured here — just before the LLM call — so it
        measures retrieval + rerank + masking only, excluding answer generation.
        """
        search_latency_ms = int((time.time() - state["start_time"]) * 1000)

        answer, status, sources = self.answer_generator.generate(
            state["normalized_query"],
            state["reranked"],
            state["role"],
        )
        logger.debug("generate_answer: status=%s sources=%s", status, sources)
        return {
            "generated_answer": answer,
            "answer_generation_status": status,
            "sources": sources,
            "search_latency_ms": search_latency_ms,
        }

    @staticmethod
    def _respond(state: SearchState) -> Dict:
        latency_ms = int((time.time() - state["start_time"]) * 1000)
        search_latency_ms = state.get("search_latency_ms", latency_ms)
        answer_latency_ms = max(0, latency_ms - search_latency_ms)

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
            "search done query='%s' role=%s results=%d answer=%s "
            "search=%dms answer=%dms total=%dms",
            state["query_text"][:60],
            state["role"],
            len(doc_ids),
            state.get("answer_generation_status", "skipped"),
            search_latency_ms,
            answer_latency_ms,
            latency_ms,
        )
        return {
            "latency_ms": latency_ms,
            "search_latency_ms": search_latency_ms,
            "answer_latency_ms": answer_latency_ms,
        }

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
            "generated_answer": "",
            "answer_generation_status": "skipped",
            "sources": [],
            "latency_ms": 0,
            "search_latency_ms": 0,
            "answer_latency_ms": 0,
            "start_time": time.time(),
        }
        return self._graph.invoke(initial)
