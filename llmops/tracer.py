"""LLM span tracer — standalone production-ready tracing utility.

Not wired into live agents yet. Use create_span() + TraceWriter.write_span()
when integrating into agent code in a future pass.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import logging

_log = logging.getLogger(__name__)

TRACE_DIR_DEFAULT = "eval_results/traces"


@dataclass
class LLMSpan:
    span_id: str
    request_id: str
    agent_name: str
    model: str | None
    prompt_version: str | None
    started_at: str
    ended_at: str | None
    latency_ms: float | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    status: str
    error: str | None


def create_span(
    agent_name: str,
    request_id: str,
    model: str | None = None,
    prompt_version: str | None = None,
) -> LLMSpan:
    """Create a new span with current UTC timestamp and a fresh UUID."""
    return LLMSpan(
        span_id=str(uuid.uuid4()),
        request_id=request_id,
        agent_name=agent_name,
        model=model,
        prompt_version=prompt_version,
        started_at=datetime.now(timezone.utc).isoformat(),
        ended_at=None,
        latency_ms=None,
        input_tokens=None,
        output_tokens=None,
        cache_read_tokens=None,
        cache_write_tokens=None,
        status="started",
        error=None,
    )


class TraceWriter:
    """Write and read LLMSpan records to date-partitioned JSONL files."""

    def write_span(self, span: LLMSpan, output_dir: str = TRACE_DIR_DEFAULT) -> None:
        """Append span to eval_results/traces/YYYY-MM-DD.jsonl."""
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        file_path = out_path / f"{date_str}.jsonl"
        try:
            with file_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(span)) + "\n")
        except OSError as exc:
            _log.error("TraceWriter.write_span failed: %s", exc)

    def read_spans(self, trace_dir: str = TRACE_DIR_DEFAULT) -> list[LLMSpan]:
        """Read all spans from all JSONL files in trace_dir."""
        spans: list[LLMSpan] = []
        dir_path = Path(trace_dir)
        if not dir_path.exists():
            return spans
        for jsonl_file in sorted(dir_path.glob("*.jsonl")):
            try:
                with jsonl_file.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        data: dict[str, Any] = json.loads(line)
                        spans.append(LLMSpan(**{k: data.get(k) for k in LLMSpan.__dataclass_fields__}))
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                _log.warning("Failed to read trace file %s: %s", jsonl_file, exc)
        return spans
