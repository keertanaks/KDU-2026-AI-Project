from pydantic import BaseModel
from typing import List, Optional


class AuditLogEntry(BaseModel):
    audit_id: str
    user_id: str
    role: str
    timestamp: str
    query_hash: str
    document_ids_returned: List[str]
    masking_applied: Optional[str] = None
    result_count: int
    latency_ms: Optional[int] = None
