import logging
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from langsmith.client import Client

from app.config import LANGSMITH_API_KEY, LANGCHAIN_PROJECT, LANGSMITH_ENDPOINT

logger = logging.getLogger(__name__)

_UNSAFE_TRACE_KEYS = {
    "answer",
    "chunk",
    "chunk_text",
    "chunks",
    "clean_text",
    "cleaned_text",
    "context",
    "file_content",
    "file_contents",
    "generated_answer",
    "mrn",
    "normalized_text",
    "ocr_text",
    "patient_name",
    "phi",
    "phi_span",
    "phi_spans",
    "placeholder_mapping",
    "prompt",
    "query",
    "query_text",
    "raw_query",
    "raw_text",
    "restored_phi",
}
_SAFE_METRIC_CONTAINERS = {"phi_type_counts", "step_timings_ms"}


def hash_text(value: str) -> str:
    """Stable SHA-256 hash for sensitive text values."""
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def hash_filename(filename: str) -> str:
    """Hash only the basename so no path or patient-bearing filename is traced."""
    return hash_text(Path(filename or "").name.lower())


def safe_error_category(exc: BaseException | str | None) -> str:
    """Return an error class/category without exception text or PHI-bearing detail."""
    if exc is None:
        return "unknown_error"
    if isinstance(exc, str):
        return exc
    status_code = getattr(exc, "status_code", None)
    if status_code:
        return f"http_{status_code}"
    return exc.__class__.__name__


def _int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_dict(mapping: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not mapping:
        return {}
    cleaned: Dict[str, Any] = {}
    for key, value in mapping.items():
        safe_key = str(key)
        if safe_key.lower() in _UNSAFE_TRACE_KEYS:
            raise ValueError(f"Unsafe LangSmith trace key: {safe_key}")
        if isinstance(value, (str, int, float, bool)) or value is None:
            cleaned[safe_key] = value
        elif isinstance(value, Mapping):
            cleaned[safe_key] = _clean_dict(value)
        else:
            cleaned[safe_key] = str(value)
    return cleaned


def _clean_metric_dict(mapping: Optional[Mapping[str, Any]]) -> Dict[str, int]:
    if not mapping:
        return {}
    cleaned: Dict[str, int] = {}
    for key, value in mapping.items():
        safe_value = _int_or_none(value)
        if safe_value is not None:
            cleaned[str(key)] = safe_value
    return cleaned


def _assert_safe_inputs(inputs: Mapping[str, Any], parent_key: Optional[str] = None) -> None:
    for key, value in inputs.items():
        safe_key = str(key).lower()
        if safe_key in _UNSAFE_TRACE_KEYS and parent_key not in _SAFE_METRIC_CONTAINERS:
            raise ValueError(f"Unsafe LangSmith trace key: {key}")
        if isinstance(value, Mapping):
            _assert_safe_inputs(value, safe_key)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, Mapping):
                    _assert_safe_inputs(item, safe_key)


class LangSmithTracer:
    def __init__(self, client: Optional[Client] = None, enabled: Optional[bool] = None):
        self.enabled = (
            enabled
            if enabled is not None
            else bool(LANGSMITH_API_KEY and "placeholder" not in LANGSMITH_API_KEY)
        )
        self.client: Optional[Client] = client
        if self.enabled and self.client is None:
            try:
                self.client = Client(
                    api_key=LANGSMITH_API_KEY,
                    api_url=LANGSMITH_ENDPOINT,
                    auto_batch_tracing=False,
                )
            except Exception as exc:
                logger.warning("LangSmith tracer initialization failed: %s", exc)
                self.enabled = False

    def _create_run(self, name: str, inputs: Mapping[str, Any]) -> None:
        _assert_safe_inputs(inputs)
        if not self.enabled or self.client is None:
            return

        try:
            self.client.create_run(
                name=name,
                inputs=dict(inputs),
                run_type="chain",
                project_name=LANGCHAIN_PROJECT,
            )
        except Exception as exc:
            logger.warning("LangSmith trace submission failed: %s", exc)

    def trace_search(
        self,
        query_text: str,
        role: str,
        doc_ids: List[str],
        masking_applied: str,
        result_count: int,
        search_latency_ms: int,
        answer_latency_ms: int,
        total_latency_ms: int,
        answer_status: str,
        candidate_count: Optional[int] = None,
        reranked_count: Optional[int] = None,
        masked_result_count: Optional[int] = None,
        acl_label_count: Optional[int] = None,
        step_timings_ms: Optional[Mapping[str, Any]] = None,
        error_category: Optional[str] = None,
    ) -> None:
        inputs = {
            "query_hash": hash_text(query_text),
            "role": role,
            "masking_applied": masking_applied,
            "result_count": _int_or_none(result_count),
            "source_doc_ids": [str(doc_id) for doc_id in doc_ids if doc_id],
            "search_latency_ms": _int_or_none(search_latency_ms),
            "answer_latency_ms": _int_or_none(answer_latency_ms),
            "latency_ms": _int_or_none(total_latency_ms),
            "answer_generation_status": answer_status,
            "candidate_count": _int_or_none(candidate_count),
            "reranked_count": _int_or_none(reranked_count),
            "masked_result_count": _int_or_none(masked_result_count),
            "acl_label_count": _int_or_none(acl_label_count),
            "step_timings_ms": _clean_metric_dict(step_timings_ms),
        }
        if error_category:
            inputs["error_category"] = safe_error_category(error_category)

        self._create_run("search_pipeline", inputs)

    def trace_ingest(
        self,
        filename: str,
        doc_id: Optional[str],
        doc_type: Optional[str],
        ocr_method: Optional[str],
        ocr_success_rate: Optional[float],
        raw_char_count: Optional[int],
        cleaned_char_count: Optional[int],
        normalization_applied: Optional[bool],
        quality_score: Optional[float],
        needs_review: Optional[bool],
        table_count: Optional[int],
        chunk_count: Optional[int],
        chunk_char_min: Optional[int],
        chunk_char_max: Optional[int],
        chunk_char_avg: Optional[float],
        phi_span_count: Optional[int],
        phi_type_counts: Optional[Mapping[str, int]],
        indexed_count: Optional[int],
        latency_ms: int,
        step_timings_ms: Optional[Mapping[str, Any]] = None,
        error_category: Optional[str] = None,
    ) -> None:
        inputs = {
            "filename_hash": hash_filename(filename),
            "doc_id": doc_id,
            "doc_type": doc_type,
            "ocr_method": ocr_method,
            "ocr_success_rate": _float_or_none(ocr_success_rate),
            "raw_char_count": _int_or_none(raw_char_count),
            "cleaned_char_count": _int_or_none(cleaned_char_count),
            "normalization_applied": normalization_applied,
            "quality_score": _float_or_none(quality_score),
            "needs_review": needs_review,
            "table_count": _int_or_none(table_count),
            "chunk_count": _int_or_none(chunk_count),
            "chunk_char_min": _int_or_none(chunk_char_min),
            "chunk_char_max": _int_or_none(chunk_char_max),
            "chunk_char_avg": _float_or_none(chunk_char_avg),
            "phi_span_count": _int_or_none(phi_span_count),
            "phi_type_counts": _clean_metric_dict(phi_type_counts),
            "indexed_count": _int_or_none(indexed_count),
            "latency_ms": _int_or_none(latency_ms),
            "step_timings_ms": _clean_metric_dict(step_timings_ms),
        }
        if error_category:
            inputs["error_category"] = safe_error_category(error_category)

        self._create_run("ingest_pipeline", inputs)
