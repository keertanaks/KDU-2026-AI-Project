"""
Phase 2.2 Search endpoint — updated in Phase 3/4.

POST /api/search
    Body: {"query": "<text>"}
    Auth: session cookie required (set by login endpoint)
    Returns: generated_answer, answer_generation_status, masked_chunks, sources,
             latency_ms, user_role

Phase 3 change: administrator role returns 403 before any pipeline execution.
Phase 4 change: response includes generated_answer and sources from AnswerGenerator.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.observability.langsmith_tracer import hash_text
from app.schemas.query import SearchRequest, SearchResponse, SearchResult

logger = logging.getLogger(__name__)

router = APIRouter()

# Module-level SearchGraph singleton — loaded once on first request.
_search_graph = None


def _get_search_graph():
    global _search_graph
    if _search_graph is None:
        from app.search.graph import SearchGraph
        _search_graph = SearchGraph()
    return _search_graph


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/api/search", response_model=SearchResponse)
async def search(
    payload: SearchRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Execute hybrid search pipeline for the authenticated session user.

    The session middleware (app/auth/middleware.py) validates the session_id
    cookie and attaches request.state.user with user_id and role before this
    handler runs.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_id = user["user_id"]
    role = user["role"]
    role_str = role.value if hasattr(role, "value") else str(role)

    # Phase 3: administrator role is blocked from content search.
    if role_str == "administrator":
        raise HTTPException(
            status_code=403,
            detail="Administrator role cannot perform searches.",
        )

    logger.info(
        "search request user=%s role=%s query_hash=%s",
        user_id,
        role_str,
        hash_text(payload.query),
    )

    graph = _get_search_graph()

    try:
        result = graph.invoke(
            query_text=payload.query,
            user_id=user_id,
            role=role_str,
            db=db,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Search pipeline error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Search failed: {exc}")

    masked_chunks = [
        SearchResult(
            text=r["text"],
            doc_id=r["doc_id"],
            score=r["score"],
        )
        for r in result.get("masked_results", [])
    ]

    return SearchResponse(
        generated_answer=result.get("generated_answer", ""),
        answer_generation_status=result.get("answer_generation_status", "skipped"),
        masked_chunks=masked_chunks,
        sources=result.get("sources", []),
        latency_ms=result.get("latency_ms", 0),
        search_latency_ms=result.get("search_latency_ms", 0),
        answer_latency_ms=result.get("answer_latency_ms", 0),
        user_role=role_str,
    )
