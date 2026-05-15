from pydantic import BaseModel, Field
from typing import List


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)


class SearchResult(BaseModel):
    text: str
    doc_id: str
    score: float


class SearchResponse(BaseModel):
    query: str
    masked_results: List[SearchResult]
    latency_ms: int
    role: str
