from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app.auth.models import Base, User, UserRole
from app.auth.service import AuthService
from app.auth.middleware import session_middleware

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Healthcare Semantic Search")

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


@app.get("/api/search")
async def search(request: Request, q: str = None):
    """Protected search stub — Phase 2 implements full pipeline."""
    if q is None:
        raise HTTPException(status_code=400, detail="Query parameter 'q' required")
    return {"results": [], "query": q}


@app.get("/health")
async def health():
    return {"status": "ok"}
