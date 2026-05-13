from pydantic import BaseModel
from typing import List, Optional


class IngestResponse(BaseModel):
    doc_id: str
    filename: str
    doc_type: str
    chunk_count: int
    indexed_count: int
    storage_uri: str
    phi_span_count: int


class ChunkMeta(BaseModel):
    chunk_id: str
    doc_id: str
    doc_type: str
    acl: List[str]
    phi_spans: str
    text: str
    score: Optional[float] = None
