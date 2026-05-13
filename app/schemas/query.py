from typing import List

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)


class SearchResult(BaseModel):
    text: str
    doc_id: str
    score: float


class SearchResponse(BaseModel):
    generated_answer: str
    answer_generation_status: str   # "success" | "skipped" | "failed"
    masked_chunks: List[SearchResult]
    sources: List[str]
    latency_ms: int
    user_role: str
