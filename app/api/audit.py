import json
from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.auth.models import AuditLog, UserRole
from app.database import SessionLocal
from app.schemas.audit import AuditLogEntry

router = APIRouter()


@router.get("/api/audit", response_model=list[AuditLogEntry])
async def list_audit_logs(request: Request, limit: int = Query(100, ge=1, le=500)):
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    role = user["role"]
    role_value = role.value if hasattr(role, "value") else str(role)
    if role_value != UserRole.ADMINISTRATOR.value:
        raise HTTPException(status_code=403, detail="Administrator access required")

    db: Session = SessionLocal()
    try:
        rows = (
            db.query(AuditLog)
            .order_by(AuditLog.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [
            AuditLogEntry(
                audit_id=row.audit_id,
                user_id=row.user_id,
                role=row.role.value if hasattr(row.role, "value") else str(row.role),
                timestamp=row.timestamp.isoformat(),
                query_hash=row.query_hash,
                document_ids_returned=json.loads(row.document_ids_returned or "[]"),
                masking_applied=row.masking_applied,
                result_count=row.result_count,
                latency_ms=row.latency_ms,
            )
            for row in rows
        ]
    finally:
        db.close()
