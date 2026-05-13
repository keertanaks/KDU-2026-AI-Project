"""
Phase 2.2 Search endpoint.

POST /api/search
    Body: {"query": "<text>"}
    Auth: session cookie required (set by login endpoint)
    Returns: masked_results with text, doc_id, score
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import SessionLocal
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
    # Normalise role to string value (enum or str both accepted)
    role_str = role.value if hasattr(role, "value") else str(role)

    logger.info("search request user=%s role=%s query='%s'", user_id, role_str, payload.query[:80])

    graph = _get_search_graph()

    try:
        result = graph.invoke(
            query_text=payload.query,
            user_id=user_id,
            role=role_str,
            db=db,
        )
    except Exception as exc:
        logger.exception("Search pipeline error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Search failed: {exc}")

    masked_results = [
        SearchResult(
            text=r["text"],
            doc_id=r["doc_id"],
            score=r["score"],
        )
        for r in result.get("masked_results", [])
    ]

    return SearchResponse(
        query=payload.query,
        masked_results=masked_results,
        latency_ms=result.get("latency_ms", 0),
        role=role_str,
    )
