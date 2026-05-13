import logging

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app.auth.models import Base, User, UserRole
from app.auth.service import AuthService
from app.auth.middleware import session_middleware
from app.api.documents import router as documents_router
from app.api.search import router as search_router, _get_search_graph

logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Healthcare Semantic Search")
app.include_router(documents_router)
app.include_router(search_router)


@app.on_event("startup")
async def warmup_models():
    """
    Pre-load the SearchGraph singleton (and its reranker cross-encoder) so the
    first real query does not pay the cold-start cost.

    Uses the same _get_search_graph() factory that the search endpoint uses,
    ensuring the warmed instance is the one that handles live requests.
    """
    try:
        graph = _get_search_graph()
        # Trigger cross-encoder model load by running a minimal rerank pass.
        graph.reranker.rerank(
            "warmup",
            [{"_source": {"text": "warmup"}}],
            top_n=1,
        )
        logger.info("Startup warmup complete — reranker model loaded.")
    except Exception as exc:
        logger.warning("Startup warmup failed (non-fatal): %s", exc)

# session_middleware registered first so it becomes inner in the stack
app.middleware("http")(session_middleware)

# CORSMiddleware registered second — add_middleware inserts at index 0,
# making it outermost so it processes OPTIONS preflight before auth runs.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
async def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Login endpoint — sets session_id cookie on success."""
    user = db.query(User).filter_by(username=payload.username).first()

    if not user or not AuthService.verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    session_id = AuthService.create_session(db, user.user_id, user.role)
    response = JSONResponse({"status": "success"})
    # secure=False for local HTTP dev (set True behind TLS in production)
    response.set_cookie("session_id", session_id, httponly=True, secure=False)
    return response


@app.post("/api/auth/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    """Logout endpoint — revokes session cookie."""
    session_id = request.cookies.get("session_id")
    if session_id:
        AuthService.revoke_session(db, session_id)
    return {"status": "success"}


@app.get("/health")
async def health():
    return {"status": "ok"}
