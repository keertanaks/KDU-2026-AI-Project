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
from app.observability.langsmith_tracer import LangSmithTracer, hash_text, safe_error_category
from app.search.answer_generator import AnswerGenerator
from app.search.masker import ResponseMasker
from app.search.reranker import Reranker
from app.search.retriever import HybridRetriever

logger = logging.getLogger(__name__)
_tracer = LangSmithTracer()

MIN_RERANK_SCORE = 0.20


def _record_step(state: Dict, step_name: str) -> Dict:
    now = time.time()
    previous = state.get("step_started_at", state.get("start_time", now))
    timings = dict(state.get("step_timings_ms", {}))
    timings[step_name] = int((now - previous) * 1000)
    return {
        "step_timings_ms": timings,
        "step_started_at": now,
    }


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
    step_started_at: float
    step_timings_ms: Dict[str, int]
    candidate_count: int
    reranked_count: int
    masked_result_count: int
    acl_label_count: int


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
        logger.debug(
            "normalize_query: query_hash=%s length=%d",
            hash_text(state["query_text"]),
            len(state["query_text"]),
        )
        return {"normalized_query": normalized, **_record_step(state, "normalize_query")}

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
        return {
            "user_acl": acl,
            "acl_label_count": len(acl),
            **_record_step(state, "resolve_acl"),
        }

    def _embed_query(self, state: SearchState) -> Dict:
        embedding = self.embedder.embed_batch([state["normalized_query"]])[0]
        logger.debug("embed_query: %d-dim vector", len(embedding))
        return {"query_embedding": embedding, **_record_step(state, "embed_query")}

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
                "  candidate[%d] id=%s rrf=%.5f",
                i, c["_id"], c.get("rrf_score", 0),
            )
        return {
            "candidates": candidates,
            "candidate_count": len(candidates),
            **_record_step(state, "retrieve"),
        }

    def _rerank(self, state: SearchState) -> Dict:
        reranked = self.reranker.rerank(
            state["normalized_query"],
            state["candidates"],
            top_n=5,
        )
        logger.debug("rerank: top scores %s", [f"{r['rerank_score']:.4f}" for r in reranked])
        
        # Apply threshold filter
        filtered = [r for r in reranked if r.get("rerank_score", 0) >= MIN_RERANK_SCORE]
        if not filtered:
            filtered = reranked[:1]  # Fallback to top 1 if none pass threshold
        
        logger.info(
            "rerank threshold: kept %d/%d chunks (threshold=%.2f)",
            len(filtered),
            len(reranked),
            MIN_RERANK_SCORE,
        )
        
        return {
            "reranked": filtered,
            "reranked_count": len(filtered),
            **_record_step(state, "rerank"),
        }

    @staticmethod
    def _mask(state: SearchState) -> Dict:
        masked_results = []
        for chunk in state["reranked"]:
            src = chunk.get("_source", {})
            phi_spans = src.get("phi_spans", [])
            # Use normalized_text for cleaner display if available; fall back to raw text
            display_text = src.get("normalized_text") or src.get("text", "")
            masked_text = ResponseMasker.mask(display_text, phi_spans, state["role"])
            masked_results.append({
                "text": masked_text,
                "doc_id": src.get("doc_id", ""),
                "score": chunk.get("rerank_score", 0.0),
            })
        logger.debug("mask: %d results, role=%s", len(masked_results), state["role"])
        return {
            "masked_results": masked_results,
            "masked_result_count": len(masked_results),
            **_record_step(state, "mask"),
        }

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
            **_record_step(state, "generate_answer"),
        }

    @staticmethod
    def _respond(state: SearchState) -> Dict:
        respond_step = _record_step(state, "respond")
        step_timings_ms = respond_step["step_timings_ms"]
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

        try:
            _tracer.trace_search(
                query_text=state["query_text"],
                role=state["role"],
                doc_ids=doc_ids,
                masking_applied=masking_label,
                result_count=len(doc_ids),
                search_latency_ms=search_latency_ms,
                answer_latency_ms=answer_latency_ms,
                total_latency_ms=latency_ms,
                answer_status=state.get("answer_generation_status", "skipped"),
                candidate_count=state.get("candidate_count", 0),
                reranked_count=state.get("reranked_count", 0),
                masked_result_count=state.get("masked_result_count", len(doc_ids)),
                acl_label_count=state.get("acl_label_count", 0),
                step_timings_ms=step_timings_ms,
            )
        except Exception as exc:
            logger.warning("LangSmith trace failed (non-fatal): %s", exc)

        logger.info(
            "search done query_hash=%s role=%s results=%d answer=%s "
            "search=%dms answer=%dms total=%dms",
            hash_text(state["query_text"]),
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
            **respond_step,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def invoke(self, query_text: str, user_id: str, role: str, db: Any) -> Dict:
        """Execute the full search pipeline and return the final SearchState."""
        start_time = time.time()
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
            "start_time": start_time,
            "step_started_at": start_time,
            "step_timings_ms": {},
            "candidate_count": 0,
            "reranked_count": 0,
            "masked_result_count": 0,
            "acl_label_count": 0,
        }
        try:
            return self._graph.invoke(initial)
        except Exception as exc:
            latency_ms = int((time.time() - start_time) * 1000)
            _tracer.trace_search(
                query_text=query_text,
                role=role,
                doc_ids=[],
                masking_applied="unknown",
                result_count=0,
                search_latency_ms=latency_ms,
                answer_latency_ms=0,
                total_latency_ms=latency_ms,
                answer_status="failed",
                candidate_count=0,
                reranked_count=0,
                masked_result_count=0,
                acl_label_count=0,
                step_timings_ms=initial.get("step_timings_ms", {}),
                error_category=safe_error_category(exc),
            )
            raise
