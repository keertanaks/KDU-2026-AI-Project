"""OpenRouter compatibility shim for the Anthropic SDK.

OpenRouter exposes an OpenAI-compatible API at https://openrouter.ai/api/v1/chat/completions.
It does NOT expose an Anthropic-compatible /messages endpoint.

This module provides ``OpenRouterCompat`` — a drop-in replacement for
``anthropic.Anthropic`` that translates the Anthropic Messages API surface
(as used by this project's agents) into OpenAI chat-completions calls.

Only the subset actually used by the four agents is implemented:
  client.messages.create(
      model, max_tokens, system, messages, tools, tool_choice, **kwargs
  )

Response attributes surfaced:
  .content  — list of ContentBlock with .type / .text / .name / .input / .id
  .stop_reason — "end_turn" | "tool_use"
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------


def _system_to_str(system: Any) -> str | None:
    """Normalise Anthropic ``system`` (str OR list of text blocks) to plain str."""
    if system is None:
        return None
    if isinstance(system, str):
        return system
    # List of blocks — collect text content, ignore cache_control
    parts: list[str] = []
    for block in system:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            if text:
                parts.append(text)
    return "\n\n".join(parts) if parts else None


def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anthropic tool schema → OpenAI function tool schema.

    Anthropic uses ``input_schema`` as the JSON Schema;
    OpenAI uses ``parameters`` inside a nested ``function`` dict.
    """
    result: list[dict[str, Any]] = []
    for t in tools:
        result.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            }
        )
    return result


def _convert_tool_choice(tool_choice: dict[str, Any] | None) -> Any:
    """Anthropic tool_choice → OpenAI tool_choice."""
    if tool_choice is None:
        return None
    tc_type = tool_choice.get("type", "")
    if tc_type == "auto":
        return "auto"
    if tc_type == "any":
        return "required"
    if tc_type == "tool":
        name = tool_choice.get("name", "")
        return {"type": "function", "function": {"name": name}}
    return None


def _convert_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Anthropic messages list → OpenAI messages list.

    Handles:
    - Plain string content
    - List of content blocks (text, tool_use, tool_result)
    - Tool-result messages (converts to role=tool)
    """
    out: list[dict[str, Any]] = []

    for msg in messages:
        role: str = msg["role"]
        content = msg["content"]

        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        if isinstance(content, list):
            text_parts: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type", "")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_result":
                    # Flush any accumulated text first
                    if text_parts:
                        out.append({"role": role, "content": "\n".join(text_parts)})
                        text_parts = []
                    result_content = block.get("content", "")
                    if isinstance(result_content, list):
                        result_content = "\n".join(
                            b.get("text", "")
                            for b in result_content
                            if isinstance(b, dict) and b.get("type") == "text"
                        )
                    out.append(
                        {
                            "role": "tool",
                            "content": str(result_content),
                            "tool_call_id": block.get("tool_use_id", "call_0"),
                        }
                    )
            if text_parts:
                out.append({"role": role, "content": "\n".join(text_parts)})
        else:
            out.append({"role": role, "content": str(content)})

    return out


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


class _ContentBlock:
    """Minimal mimic of ``anthropic.types.ContentBlock``."""

    __slots__ = ("id", "input", "name", "text", "type")

    def __init__(
        self,
        *,
        type: str,
        text: str | None = None,
        id: str | None = None,
        name: str | None = None,
        input: dict[str, Any] | None = None,
    ) -> None:
        self.type = type
        self.text = text
        self.id = id
        self.name = name
        self.input = input or {}


class _Message:
    """Minimal mimic of ``anthropic.types.Message``."""

    __slots__ = ("content", "stop_reason")

    def __init__(self, *, content: list[_ContentBlock], stop_reason: str) -> None:
        self.content = content
        self.stop_reason = stop_reason


def _convert_response(openai_response: Any) -> _Message:
    """OpenAI ChatCompletion → Anthropic Message mimic."""
    choice = openai_response.choices[0]
    msg = choice.message

    content: list[_ContentBlock] = []

    if msg.tool_calls:
        stop_reason = "tool_use"
        for tc in msg.tool_calls:
            try:
                inp: dict[str, Any] = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                inp = {}
            content.append(
                _ContentBlock(
                    type="tool_use",
                    id=tc.id,
                    name=tc.function.name,
                    input=inp,
                )
            )
    else:
        stop_reason = "end_turn"
        text_content = getattr(msg, "content", None) or ""
        content.append(_ContentBlock(type="text", text=str(text_content)))

    return _Message(content=content, stop_reason=stop_reason)


# ---------------------------------------------------------------------------
# Main public class
# ---------------------------------------------------------------------------


class _MessagesResource:
    """Drop-in for ``anthropic.Anthropic().messages``."""

    def __init__(self, openai_client: Any) -> None:
        self._client = openai_client

    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: list[dict[str, Any]],
        system: Any = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> _Message:
        """Translate Anthropic create() call → OpenAI chat.completions.create()."""
        openai_msgs: list[dict[str, Any]] = []

        # System prompt (Anthropic top-level param → OpenAI system message)
        sys_text = _system_to_str(system)
        if sys_text:
            openai_msgs.append({"role": "system", "content": sys_text})

        openai_msgs.extend(_convert_messages(messages))

        call_kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": openai_msgs,
        }
        if tools:
            call_kwargs["tools"] = _convert_tools(tools)
            tc = _convert_tool_choice(tool_choice)
            if tc is not None:
                call_kwargs["tool_choice"] = tc

        logger.debug(
            "OpenRouter call: model=%s msgs=%d tools=%s",
            model,
            len(openai_msgs),
            [t["function"]["name"] for t in call_kwargs.get("tools", [])],
        )

        response = self._client.chat.completions.create(**call_kwargs)
        return _convert_response(response)


class OpenRouterCompat:
    """Drop-in replacement for ``anthropic.Anthropic`` using OpenRouter.

    Usage::

        client = OpenRouterCompat(api_key=os.environ["OPENROUTER_API_KEY"])
        # Then use exactly like anthropic.Anthropic():
        resp = client.messages.create(model="anthropic/claude-3-haiku-20240307", ...)
    """

    def __init__(self, api_key: str) -> None:
        from openai import OpenAI  # imported here — only needed when OpenRouter is active

        _client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        self.messages = _MessagesResource(_client)
