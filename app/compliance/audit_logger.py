import hashlib
import json
import uuid
from datetime import datetime
from typing import List

from sqlalchemy.orm import Session as DBSession

from app.auth.models import AuditLog, UserRole


class AuditLogger:
    """Append-only query audit log.  Raw query text is NEVER stored."""

    @staticmethod
    def log_query(
        db: DBSession,
        user_id: str,
        role: UserRole,
        query_text: str,
        doc_ids: List[str],
        masking_applied: str,
        latency_ms: int,
    ) -> str:
        query_hash = hashlib.sha256(query_text.encode()).hexdigest()

        row = AuditLog(
            audit_id=str(uuid.uuid4()),
            user_id=user_id,
            role=role,
            timestamp=datetime.utcnow(),
            query_hash=query_hash,
            document_ids_returned=json.dumps(doc_ids),
            masking_applied=masking_applied,
            result_count=len(doc_ids),
            latency_ms=latency_ms,
        )

        db.add(row)
        db.commit()
        return row.audit_id
