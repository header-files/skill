"""Anthropic Messages protocol adapter."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

from llm.errors import LLMError
from llm.protocols.base import ProtocolAdapter
from llm.protocols.common import (
    iter_sse_data_lines,
    join_url,
    map_finish_reason,
    parse_json_object,
    parse_usage_tokens,
    raise_from_http_body,
)
from llm.protocols.tool_helpers import (
    arguments_to_wire_string,
    build_tool_call,
    normalize_tool_calls,
    resolve_finish_reason,
)
from llm.types import ChatRequest, ChatResponse, Message, StreamChunk, ToolCall


def _split_system_and_messages(
    messages: list[Message],
) -> tuple[str | None, list[dict[str, Any]]]:
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    pending_tool_results: list[dict[str, Any]] = []

    def flush_tool_results() -> None:
        nonlocal pending_tool_results
        if pending_tool_results:
            converted.append({"role": "user", "content": pending_tool_results})
            pending_tool_results = []

    for msg in messages:
        if msg.role == "system":
            flush_tool_results()
            system_parts.append(msg.content or "")
            continue
        if msg.role == "tool":
            pending_tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id,
                    "content": msg.content if msg.content is not None else "",
                }
            )
            continue
        flush_tool_results()
        if msg.role == "assistant" and msg.tool_calls:
            blocks: list[dict[str, Any]] = []
            if msg.content:
                blocks.append({"type": "text", "text": msg.content})
            for call in msg.tool_calls:
                if call.arguments is not None:
                    parsed: dict[str, Any] = call.arguments
                else:
                    try:
                        value = json.loads(arguments_to_wire_string(call) or "{}")
                    except json.JSONDecodeError:
                        value = {}
                    parsed = value if isinstance(value, dict) else {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": parsed,
                    }
                )
            converted.append({"role": "assistant", "content": blocks})
            continue
        converted.append(
            {
                "role": msg.role,
                "content": msg.content if msg.content is not None else "",
            }
        )
    flush_tool_results()
    system = "\n\n".join(system_parts) if system_parts else None
    return system, converted


def _extract_content_and_tools(
    content: Any,
) -> tuple[str, str | None, list[ToolCall] | None]:
    if isinstance(content, str):
        return content, None, None
    texts: list[str] = []
    reasoning: list[str] = []
    calls: list[ToolCall] = []
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                texts.append(str(block.get("text") or ""))
            elif btype in ("thinking", "redacted_thinking"):
                thinking = block.get("thinking") or block.get("data") or ""
                if thinking:
                    reasoning.append(str(thinking))
            elif btype == "tool_use":
                inp = block.get("input")
                if isinstance(inp, dict):
                    arguments_raw = json.dumps(
                        inp, ensure_ascii=False, separators=(",", ":")
                    )
                    call = build_tool_call(
                        id=str(block.get("id") or ""),
                        name=str(block.get("name") or ""),
                        arguments_raw=arguments_raw,
                    )
                    call.arguments = inp
                    call.arguments_parse_error = None
                else:
                    call = build_tool_call(
                        id=str(block.get("id") or ""),
                        name=str(block.get("name") or ""),
                        arguments_raw=str(inp) if inp is not None else "",
                    )
                calls.append(call)
    return (
        "".join(texts),
        ("".join(reasoning) or None),
        normalize_tool_calls(calls),
    )


class AnthropicMessagesAdapter(ProtocolAdapter):
    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.config.api_key,
            "anthropic-version": self.config.anthropic_version,
            "Content-Type": "application/json",
        }

    def _url(self) -> str:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/messages"):
            return base
        if base.endswith("/v1"):
            return join_url(base, "/messages")
        return join_url(base, "/v1/messages")

    def _build_body(self, request: ChatRequest, *, stream: bool) -> dict[str, Any]:
        system, messages = _split_system_and_messages(request.messages)
        body: dict[str, Any] = {
            "model": self.config.name,
            "messages": messages,
            "stream": stream,
            "max_tokens": request.max_output_tokens
            if request.max_output_tokens is not None
            else 4096,
        }
        if system:
            body["system"] = system
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.stop is not None:
            body["stop_sequences"] = request.stop
        if request.tools:
            body["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                }
                for t in request.tools
            ]
            if request.tool_choice == "auto":
                body["tool_choice"] = {"type": "auto"}
            elif request.tool_choice == "none":
                body["tool_choice"] = {"type": "none"}
            elif request.tool_choice == "required":
                body["tool_choice"] = {"type": "any"}
            # null choice: omit
        # no effective tools: omit tools and tool_choice (validated upstream)
        return body

    def _parse_response(self, data: dict[str, Any]) -> ChatResponse:
        content, reasoning, tool_calls = _extract_content_and_tools(data.get("content"))
        finish = map_finish_reason(data.get("stop_reason"))
        finish = resolve_finish_reason(finish, tool_calls)
        return ChatResponse(
            content=content,
            reasoning=reasoning,
            tool_calls=tool_calls,
            finish_reason=finish,
            model=data.get("model") or self.config.name,
            usage=parse_usage_tokens(data.get("usage")),
        )

    def chat(self, request: ChatRequest) -> ChatResponse:
        response = self.transport.request(
            "POST",
            self._url(),
            headers=self._headers(),
            json=self._build_body(request, stream=False),
        )
        if response.status_code >= 400:
            raise_from_http_body(
                response.status_code, response.text, protocol="anthropic-messages"
            )
        data = response.json()
        if not isinstance(data, dict):
            raise LLMError(type="api_error", message="Invalid JSON response")
        return self._parse_response(data)

    async def achat(self, request: ChatRequest) -> ChatResponse:
        response = await self.transport.arequest(
            "POST",
            self._url(),
            headers=self._headers(),
            json=self._build_body(request, stream=False),
        )
        if response.status_code >= 400:
            raise_from_http_body(
                response.status_code, response.text, protocol="anthropic-messages"
            )
        data = response.json()
        if not isinstance(data, dict):
            raise LLMError(type="api_error", message="Invalid JSON response")
        return self._parse_response(data)

    def _iter_chunks(self, lines: Iterator[str]) -> Iterator[StreamChunk]:
        last_model: str | None = None
        last_usage = None
        last_finish = None
        # index -> aggregation state for tool_use blocks
        blocks: dict[int, dict[str, Any]] = {}
        current_index: int | None = None
        stream_aborted = False
        try:
            for data_line in iter_sse_data_lines(lines):
                payload = parse_json_object(data_line)
                if not payload:
                    continue
                event_type = payload.get("type")
                if event_type == "message_start":
                    message = payload.get("message") or {}
                    last_model = message.get("model") or last_model
                    usage = parse_usage_tokens(message.get("usage"))
                    if usage:
                        last_usage = usage
                elif event_type == "content_block_start":
                    index = int(payload.get("index") or 0)
                    current_index = index
                    block = payload.get("content_block") or {}
                    btype = block.get("type")
                    if btype == "thinking" and block.get("thinking"):
                        yield StreamChunk(
                            type="reasoning", delta=str(block["thinking"])
                        )
                    if btype == "text" and block.get("text"):
                        yield StreamChunk(type="content", delta=str(block["text"]))
                    if btype == "tool_use":
                        blocks[index] = {
                            "id": str(block.get("id") or ""),
                            "name": str(block.get("name") or ""),
                            "arguments": "",
                            "stopped": False,
                        }
                elif event_type == "content_block_delta":
                    index = int(
                        payload["index"]
                        if payload.get("index") is not None
                        else (current_index or 0)
                    )
                    delta = payload.get("delta") or {}
                    dtype = delta.get("type")
                    if dtype == "thinking_delta":
                        text = delta.get("thinking") or delta.get("text")
                        if text:
                            yield StreamChunk(type="reasoning", delta=str(text))
                    elif dtype == "text_delta":
                        text = delta.get("text")
                        if text:
                            yield StreamChunk(type="content", delta=str(text))
                    elif dtype == "input_json_delta":
                        partial = delta.get("partial_json")
                        if partial is None:
                            partial = delta.get("text") or ""
                        slot = blocks.get(index)
                        if slot is not None:
                            slot["arguments"] += str(partial)
                elif event_type == "content_block_stop":
                    index = int(
                        payload["index"]
                        if payload.get("index") is not None
                        else (current_index or 0)
                    )
                    if index in blocks:
                        blocks[index]["stopped"] = True
                    current_index = None
                elif event_type == "message_delta":
                    delta = payload.get("delta") or {}
                    last_finish = map_finish_reason(delta.get("stop_reason"))
                    usage = parse_usage_tokens(payload.get("usage"))
                    if usage:
                        if last_usage and usage.input_tokens is None:
                            usage.input_tokens = last_usage.input_tokens
                        last_usage = usage
                elif event_type == "message_stop":
                    pass
                elif event_type == "error":
                    stream_aborted = True
                    err = payload.get("error") or {}
                    raise LLMError(
                        type="stream_error",
                        message=str(err.get("message") or payload),
                        provider_code=str(err["type"]) if err.get("type") else None,
                        retryable=None,
                    )

            tool_calls: list[ToolCall] | None = None
            if blocks:
                calls: list[ToolCall] = []
                for index in sorted(blocks):
                    slot = blocks[index]
                    truncated = (not slot["stopped"]) or (
                        last_finish == "length" and not slot["stopped"]
                    )
                    if not slot["stopped"]:
                        truncated = True
                    calls.append(
                        build_tool_call(
                            id=slot["id"],
                            name=slot["name"],
                            arguments_raw=slot["arguments"],
                            truncated=truncated,
                        )
                    )
                tool_calls = normalize_tool_calls(calls)
            last_finish = resolve_finish_reason(last_finish, tool_calls)
            if not stream_aborted:
                yield StreamChunk(
                    type="finish",
                    delta="",
                    finish_reason=last_finish,
                    model=last_model or self.config.name,
                    usage=last_usage,
                    tool_calls=tool_calls,
                )
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise LLMError(
                type="stream_error",
                message=str(exc) or "Stream parsing failed",
                retryable=None,
            ) from exc

    def chat_stream(self, request: ChatRequest) -> Iterator[StreamChunk]:
        lines = self.transport.stream(
            "POST",
            self._url(),
            headers=self._headers(),
            json=self._build_body(request, stream=True),
        )
        yield from self._iter_chunks(lines)

    async def achat_stream(self, request: ChatRequest) -> AsyncIterator[StreamChunk]:
        lines_iter = self.transport.astream(
            "POST",
            self._url(),
            headers=self._headers(),
            json=self._build_body(request, stream=True),
        )
        buffer: list[str] = []
        async for line in lines_iter:
            buffer.append(line)
        for chunk in self._iter_chunks(iter(buffer)):
            yield chunk
