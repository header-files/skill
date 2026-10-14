"""OpenAI Chat Completions protocol adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

from llm.errors import LLMError
from llm.protocols.base import ProtocolAdapter
from llm.protocols.common import (
    iter_sse_data_lines,
    join_url,
    map_finish_reason,
    parse_json_object,
    parse_usage_openai_chat,
    raise_from_http_body,
)
from llm.protocols.tool_helpers import (
    arguments_to_wire_string,
    build_tool_call,
    normalize_tool_calls,
    resolve_finish_reason,
)
from llm.types import ChatRequest, ChatResponse, Message, StreamChunk, ToolCall


def _encode_messages(messages: list[Message]) -> list[dict[str, Any]]:
    encoded: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == "tool":
            item: dict[str, Any] = {
                "role": "tool",
                "tool_call_id": msg.tool_call_id,
                "content": msg.content if msg.content is not None else "",
            }
            if msg.name:
                item["name"] = msg.name
            encoded.append(item)
            continue
        if msg.role == "assistant" and msg.tool_calls:
            item = {
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": arguments_to_wire_string(call),
                        },
                    }
                    for call in msg.tool_calls
                ],
            }
            encoded.append(item)
            continue
        encoded.append(
            {
                "role": msg.role,
                "content": msg.content if msg.content is not None else "",
            }
        )
    return encoded


def _parse_tool_calls_from_message(message: dict[str, Any]) -> list[ToolCall] | None:
    raw_calls = message.get("tool_calls") or []
    if not raw_calls:
        return None
    calls: list[ToolCall] = []
    for item in raw_calls:
        if not isinstance(item, dict):
            continue
        fn = item.get("function") or {}
        cid = str(item.get("id") or "")
        name = str(fn.get("name") or "")
        arguments_raw = fn.get("arguments")
        if arguments_raw is None:
            arguments_raw = ""
        elif not isinstance(arguments_raw, str):
            arguments_raw = str(arguments_raw)
        calls.append(
            build_tool_call(id=cid, name=name, arguments_raw=arguments_raw)
        )
    return normalize_tool_calls(calls)


class OpenAICompletionsAdapter(ProtocolAdapter):
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def _url(self) -> str:
        base = self.config.base_url
        if base.endswith("/chat/completions"):
            return base
        return join_url(base, "/chat/completions")

    def _build_body(self, request: ChatRequest, *, stream: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.config.name,
            "messages": _encode_messages(request.messages),
            "stream": stream,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            body["max_tokens"] = request.max_output_tokens
        if request.stop is not None:
            body["stop"] = request.stop
        if request.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in request.tools
            ]
            if request.tool_choice is not None:
                body["tool_choice"] = request.tool_choice
        if stream:
            body["stream_options"] = {"include_usage": True}
        return body

    def _parse_response(self, data: dict[str, Any]) -> ChatResponse:
        choices = data.get("choices") or []
        content = ""
        reasoning: str | None = None
        finish_reason = None
        tool_calls: list[ToolCall] | None = None
        if choices:
            choice = choices[0]
            message = choice.get("message") or {}
            raw_content = message.get("content")
            content = "" if raw_content is None else (
                raw_content if isinstance(raw_content, str) else str(raw_content)
            )
            reasoning = message.get("reasoning_content") or message.get("reasoning")
            if reasoning is not None:
                reasoning = str(reasoning)
            tool_calls = _parse_tool_calls_from_message(message)
            finish_reason = map_finish_reason(choice.get("finish_reason"))
            finish_reason = resolve_finish_reason(finish_reason, tool_calls)
        return ChatResponse(
            content=content,
            reasoning=reasoning,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            model=data.get("model") or self.config.name,
            usage=parse_usage_openai_chat(data.get("usage")),
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
                response.status_code, response.text, protocol="openai-completions"
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
                response.status_code, response.text, protocol="openai-completions"
            )
        data = response.json()
        if not isinstance(data, dict):
            raise LLMError(type="api_error", message="Invalid JSON response")
        return self._parse_response(data)

    def _iter_chunks(self, lines: Iterator[str]) -> Iterator[StreamChunk]:
        saw_finish = False
        last_model: str | None = None
        last_usage = None
        last_finish = None
        # index -> partial tool call aggregation
        pending: dict[int, dict[str, str]] = {}
        stream_truncated = False
        try:
            for data_line in iter_sse_data_lines(lines):
                payload = parse_json_object(data_line)
                if not payload:
                    continue
                if payload.get("model"):
                    last_model = payload["model"]
                usage = parse_usage_openai_chat(payload.get("usage"))
                if usage:
                    last_usage = usage
                for choice in payload.get("choices") or []:
                    delta = choice.get("delta") or {}
                    reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                    if reasoning:
                        yield StreamChunk(type="reasoning", delta=str(reasoning))
                    text = delta.get("content")
                    if text:
                        yield StreamChunk(type="content", delta=str(text))
                    for tc in delta.get("tool_calls") or []:
                        if not isinstance(tc, dict):
                            continue
                        idx = int(tc.get("index") or 0)
                        slot = pending.setdefault(
                            idx, {"id": "", "name": "", "arguments": ""}
                        )
                        if tc.get("id"):
                            slot["id"] = str(tc["id"])
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = str(fn["name"])
                        if fn.get("arguments"):
                            slot["arguments"] += str(fn["arguments"])
                    fr = map_finish_reason(choice.get("finish_reason"))
                    if fr is not None:
                        last_finish = fr
                        if fr == "length":
                            stream_truncated = True
            tool_calls: list[ToolCall] | None = None
            if pending:
                calls: list[ToolCall] = []
                for idx in sorted(pending):
                    slot = pending[idx]
                    truncated = stream_truncated and last_finish == "length"
                    # If finish is length, mark incomplete when args not parseable
                    call = build_tool_call(
                        id=slot["id"],
                        name=slot["name"],
                        arguments_raw=slot["arguments"],
                        truncated=False,
                    )
                    if truncated and call.arguments is None:
                        call = build_tool_call(
                            id=slot["id"],
                            name=slot["name"],
                            arguments_raw=slot["arguments"],
                            truncated=True,
                        )
                    elif truncated:
                        # length finish with parseable args still complete if id/name ok
                        pass
                    if not slot["id"] or not slot["name"]:
                        call = build_tool_call(
                            id=slot["id"],
                            name=slot["name"],
                            arguments_raw=slot["arguments"],
                            truncated=True,
                        )
                    calls.append(call)
                tool_calls = normalize_tool_calls(calls)
            last_finish = resolve_finish_reason(last_finish, tool_calls)
            saw_finish = True
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
        finally:
            if not saw_finish:
                pass

    def chat_stream(self, request: ChatRequest) -> Iterator[StreamChunk]:
        lines = self.transport.stream(
            "POST",
            self._url(),
            headers=self._headers(),
            json=self._build_body(request, stream=True),
        )
        yield from self._iter_chunks(lines)

    async def achat_stream(self, request: ChatRequest) -> AsyncIterator[StreamChunk]:
        lines = self.transport.astream(
            "POST",
            self._url(),
            headers=self._headers(),
            json=self._build_body(request, stream=True),
        )

        async def _agen() -> AsyncIterator[str]:
            async for line in lines:
                yield line

        collected: list[str] = []
        async for line in _agen():
            collected.append(line)
        for chunk in self._iter_chunks(iter(collected)):
            yield chunk
