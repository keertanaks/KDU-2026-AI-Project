from fastapi import Request
from fastapi.responses import JSONResponse
from app.database import SessionLocal
from app.auth.service import AuthService

# Paths that do not require authentication
_PUBLIC_PATHS = {"/health", "/api/auth/login", "/api/auth/logout"}


async def session_middleware(request: Request, call_next):
    """Validate session cookie for all /api/ paths except public ones."""
    path = request.url.path

    if path in _PUBLIC_PATHS or not path.startswith("/api/"):
        return await call_next(request)

    session_id = request.cookies.get("session_id")
    if not session_id:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    db = SessionLocal()
    try:
        session_data = AuthService.validate_session(db, session_id)
    finally:
        db.close()

    if not session_data:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    request.state.user = session_data
    return await call_next(request)
