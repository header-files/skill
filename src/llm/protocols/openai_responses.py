"""OpenAI Responses API protocol adapter."""

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


def _build_input_items(messages: list[Message]) -> tuple[str | None, list[dict[str, Any]]]:
    system_parts: list[str] = []
    input_items: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == "system":
            system_parts.append(msg.content or "")
            continue
        if msg.role == "tool":
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": msg.tool_call_id,
                    "output": msg.content if msg.content is not None else "",
                }
            )
            continue
        if msg.role == "assistant" and msg.tool_calls:
            if msg.content:
                input_items.append(
                    {
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": msg.content}],
                    }
                )
            for call in msg.tool_calls:
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": call.id,
                        "name": call.name,
                        "arguments": arguments_to_wire_string(call),
                    }
                )
            continue
        role = "user" if msg.role == "user" else "assistant"
        text = msg.content if msg.content is not None else ""
        input_items.append(
            {
                "role": role,
                "content": [{"type": "input_text", "text": text}]
                if role == "user"
                else [{"type": "output_text", "text": text}],
            }
        )
    instructions = "\n\n".join(system_parts) if system_parts else None
    return instructions, input_items


def _extract_text_from_output(output: list[Any]) -> tuple[str, str | None]:
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "reasoning":
            for part in item.get("summary") or item.get("content") or []:
                if isinstance(part, dict):
                    text = part.get("text")
                    if text:
                        reasoning_parts.append(str(text))
                elif isinstance(part, str):
                    reasoning_parts.append(part)
            continue
        if item_type in ("message", None):
            for part in item.get("content") or []:
                if not isinstance(part, dict):
                    continue
                ptype = part.get("type")
                text = part.get("text")
                if text is None:
                    continue
                if ptype in ("output_text", "text"):
                    content_parts.append(str(text))
                elif ptype in ("reasoning", "reasoning_text"):
                    reasoning_parts.append(str(text))
    content = "".join(content_parts)
    reasoning = "".join(reasoning_parts) or None
    return content, reasoning


def _extract_tool_calls_from_output(output: list[Any]) -> list[ToolCall] | None:
    calls: list[ToolCall] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") not in ("function_call", "function_call_item"):
            continue
        call_id = item.get("call_id")
        if not call_id:
            calls.append(
                build_tool_call(
                    id="",
                    name=str(item.get("name") or ""),
                    arguments_raw=str(item.get("arguments") or ""),
                    truncated=True,
                )
            )
            continue
        arguments_raw = item.get("arguments")
        if arguments_raw is None:
            arguments_raw = ""
        elif isinstance(arguments_raw, dict):
            arguments_raw = json.dumps(
                arguments_raw, ensure_ascii=False, separators=(",", ":")
            )
        else:
            arguments_raw = str(arguments_raw)
        calls.append(
            build_tool_call(
                id=str(call_id),
                name=str(item.get("name") or ""),
                arguments_raw=arguments_raw,
            )
        )
    return normalize_tool_calls(calls)


class OpenAIResponsesAdapter(ProtocolAdapter):
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def _url(self) -> str:
        base = self.config.base_url
        if base.endswith("/responses"):
            return base
        return join_url(base, "/responses")

    def _build_body(self, request: ChatRequest, *, stream: bool) -> dict[str, Any]:
        instructions, input_items = _build_input_items(request.messages)
        body: dict[str, Any] = {
            "model": self.config.name,
            "input": input_items,
            "stream": stream,
        }
        if instructions:
            body["instructions"] = instructions
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            body["max_output_tokens"] = request.max_output_tokens
        if request.stop is not None:
            body["stop"] = request.stop
        if request.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                }
                for t in request.tools
            ]
            if request.tool_choice is not None:
                # Responses API accepts string tool_choice similarly for auto/none/required
                body["tool_choice"] = request.tool_choice
        return body

    def _parse_response(self, data: dict[str, Any]) -> ChatResponse:
        output = data.get("output") or []
        content, reasoning = _extract_text_from_output(output)
        tool_calls = _extract_tool_calls_from_output(output)
        status = data.get("status")
        finish = None
        if status == "completed":
            finish = "stop"
        elif status == "incomplete":
            reason = (data.get("incomplete_details") or {}).get("reason")
            finish = map_finish_reason(reason) or "length"
        if tool_calls and finish == "stop":
            finish = "tool_calls"
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
                response.status_code, response.text, protocol="openai-responses"
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
                response.status_code, response.text, protocol="openai-responses"
            )
        data = response.json()
        if not isinstance(data, dict):
            raise LLMError(type="api_error", message="Invalid JSON response")
        return self._parse_response(data)

    def _iter_chunks(self, lines: Iterator[str]) -> Iterator[StreamChunk]:
        last_model: str | None = None
        last_usage = None
        last_finish: str | None = None
        # Aggregate function_call by call_id or output_index
        pending: dict[str, dict[str, Any]] = {}
        completed_output: list[Any] = []
        try:
            for data_line in iter_sse_data_lines(lines):
                payload = parse_json_object(data_line)
                if not payload:
                    continue
                event_type = payload.get("type") or ""
                if payload.get("model"):
                    last_model = payload["model"]

                response_obj = payload.get("response")
                if isinstance(response_obj, dict):
                    if response_obj.get("model"):
                        last_model = response_obj["model"]
                    usage = parse_usage_tokens(response_obj.get("usage"))
                    if usage:
                        last_usage = usage
                    if event_type == "response.completed" and response_obj.get("output"):
                        completed_output = list(response_obj["output"])

                if event_type in (
                    "response.output_text.delta",
                    "response.content_part.delta",
                ):
                    delta = payload.get("delta")
                    if isinstance(delta, str) and delta:
                        yield StreamChunk(type="content", delta=delta)
                    elif isinstance(delta, dict):
                        text = delta.get("text") or delta.get("value")
                        if text:
                            yield StreamChunk(type="content", delta=str(text))
                elif event_type in (
                    "response.reasoning_text.delta",
                    "response.reasoning.delta",
                ):
                    delta = payload.get("delta")
                    if isinstance(delta, str) and delta:
                        yield StreamChunk(type="reasoning", delta=delta)
                    elif isinstance(delta, dict) and delta.get("text"):
                        yield StreamChunk(type="reasoning", delta=str(delta["text"]))
                elif event_type in (
                    "response.function_call_arguments.delta",
                    "response.output_item.added",
                ):
                    item = payload.get("item") or {}
                    if event_type == "response.output_item.added" and item.get("type") in (
                        "function_call",
                        "function_call_item",
                    ):
                        call_id = str(item.get("call_id") or "")
                        key = call_id or f"idx:{payload.get('output_index', 0)}"
                        pending[key] = {
                            "id": call_id,
                            "name": str(item.get("name") or ""),
                            "arguments": str(item.get("arguments") or ""),
                            "done": False,
                        }
                    elif event_type == "response.function_call_arguments.delta":
                        call_id = str(
                            payload.get("call_id")
                            or (payload.get("item") or {}).get("call_id")
                            or ""
                        )
                        key = call_id or f"idx:{payload.get('output_index', 0)}"
                        slot = pending.setdefault(
                            key,
                            {
                                "id": call_id,
                                "name": "",
                                "arguments": "",
                                "done": False,
                            },
                        )
                        delta = payload.get("delta")
                        if isinstance(delta, str):
                            slot["arguments"] += delta
                        elif isinstance(delta, dict):
                            slot["arguments"] += str(
                                delta.get("arguments") or delta.get("text") or ""
                            )
                elif event_type == "response.function_call_arguments.done":
                    call_id = str(payload.get("call_id") or "")
                    key = call_id or f"idx:{payload.get('output_index', 0)}"
                    slot = pending.setdefault(
                        key,
                        {"id": call_id, "name": "", "arguments": "", "done": False},
                    )
                    if payload.get("arguments") is not None:
                        slot["arguments"] = str(payload["arguments"])
                    if payload.get("name"):
                        slot["name"] = str(payload["name"])
                    if call_id:
                        slot["id"] = call_id
                    slot["done"] = True
                elif event_type == "response.output_item.done":
                    item = payload.get("item") or {}
                    if item.get("type") in ("function_call", "function_call_item"):
                        call_id = str(item.get("call_id") or "")
                        key = call_id or f"idx:{payload.get('output_index', 0)}"
                        slot = pending.setdefault(
                            key,
                            {
                                "id": call_id,
                                "name": str(item.get("name") or ""),
                                "arguments": "",
                                "done": False,
                            },
                        )
                        if item.get("name"):
                            slot["name"] = str(item["name"])
                        if item.get("arguments") is not None:
                            args = item["arguments"]
                            slot["arguments"] = (
                                json.dumps(args, ensure_ascii=False, separators=(",", ":"))
                                if isinstance(args, dict)
                                else str(args)
                            )
                        if call_id:
                            slot["id"] = call_id
                        slot["done"] = True
                elif event_type == "response.completed":
                    last_finish = "stop"
                    if isinstance(response_obj, dict):
                        last_usage = (
                            parse_usage_tokens(response_obj.get("usage")) or last_usage
                        )
                elif event_type == "response.incomplete":
                    last_finish = "length"
                elif event_type == "error":
                    raise LLMError(
                        type="stream_error",
                        message=str(payload.get("message") or payload),
                        retryable=None,
                    )

            tool_calls: list[ToolCall] | None = None
            if completed_output:
                tool_calls = _extract_tool_calls_from_output(completed_output)
            elif pending:
                calls: list[ToolCall] = []
                for key in sorted(pending):
                    slot = pending[key]
                    truncated = not slot.get("done") or not slot.get("id")
                    if last_finish == "length" and not slot.get("done"):
                        truncated = True
                    calls.append(
                        build_tool_call(
                            id=str(slot.get("id") or ""),
                            name=str(slot.get("name") or ""),
                            arguments_raw=str(slot.get("arguments") or ""),
                            truncated=truncated,
                        )
                    )
                tool_calls = normalize_tool_calls(calls)

            if tool_calls and last_finish == "stop":
                last_finish = "tool_calls"
            last_finish = resolve_finish_reason(
                last_finish,  # type: ignore[arg-type]
                tool_calls,
            )
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
