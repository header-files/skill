"""Tool-calling helpers: parse, validate outbound requests, finish_reason."""

from __future__ import annotations

import json
from typing import Any

from llm.errors import LLMError
from llm.types import (
    ChatRequest,
    FinishReason,
    Message,
    ToolCall,
    ToolChoice,
    ToolSpec,
)


def parse_arguments_object(raw: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse tool arguments JSON. Success only for JSON objects (incl. {})."""
    try:
        value = json.loads(raw) if raw != "" else None
    except json.JSONDecodeError as exc:
        return None, f"invalid json: {exc}"
    if value is None:
        return None, "empty arguments"
    if not isinstance(value, dict):
        return None, f"arguments must be a JSON object, got {type(value).__name__}"
    return value, None


def build_tool_call(
    *,
    id: str,
    name: str,
    arguments_raw: str = "",
    truncated: bool = False,
) -> ToolCall:
    if truncated:
        return ToolCall(
            id=id,
            name=name,
            arguments_raw=arguments_raw,
            arguments=None,
            arguments_parse_error=None,
            truncated=True,
        )
    arguments, err = parse_arguments_object(arguments_raw)
    return ToolCall(
        id=id,
        name=name,
        arguments_raw=arguments_raw,
        arguments=arguments,
        arguments_parse_error=err,
        truncated=False,
    )


def arguments_to_wire_string(call: ToolCall) -> str:
    """Encode ToolCall arguments for protocol wire (always a JSON string)."""
    if call.arguments_raw:
        return call.arguments_raw
    if call.arguments is not None:
        return json.dumps(call.arguments, ensure_ascii=False, separators=(",", ":"))
    return call.arguments_raw or ""


def normalize_tool_calls(
    tool_calls: list[ToolCall] | None,
) -> list[ToolCall] | None:
    if not tool_calls:
        return None
    return tool_calls


def tool_call_is_complete(call: ToolCall) -> bool:
    if not (call.id or "").strip() or not (call.name or "").strip():
        return False
    if call.truncated:
        return False
    return call.arguments is not None


def resolve_finish_reason(
    upstream: FinishReason | None,
    tool_calls: list[ToolCall] | None,
) -> FinishReason | None:
    """Apply integrity rules: truncation wins over bare tool_calls labeling."""
    calls = normalize_tool_calls(tool_calls)
    if not calls:
        return upstream

    has_incomplete = any(not tool_call_is_complete(c) for c in calls)
    has_complete = any(tool_call_is_complete(c) for c in calls)

    if has_incomplete and upstream in ("length", "content_filter"):
        return upstream
    if has_complete and not has_incomplete:
        return "tool_calls"
    if has_complete and has_incomplete:
        if upstream == "length":
            return "length"
        return "tool_calls"
    # Only incomplete / parse-failed entries
    return upstream if upstream is not None else "tool_calls"


def effective_tools(tools: list[ToolSpec] | None) -> list[ToolSpec] | None:
    if not tools:
        return None
    return tools


def validate_chat_request(request: ChatRequest) -> ChatRequest:
    """Normalize and validate request; raise LLMError(invalid_request) on violation."""
    tools = effective_tools(request.tools)
    choice = request.tool_choice

    if tools is None:
        if choice in ("auto", "required"):
            raise LLMError(
                type="invalid_request",
                message="tool_choice auto/required requires non-empty tools",
            )
        # null or none: omit tools and tool_choice on wire
        normalized_choice: ToolChoice | None = None
    else:
        names = [t.name.strip() for t in tools]
        if any(not n for n in names):
            raise LLMError(
                type="invalid_request",
                message="tool name must be non-empty",
            )
        if len(names) != len(set(names)):
            raise LLMError(
                type="invalid_request",
                message="tool names must be unique",
            )
        normalized_choice = choice

    messages = [_normalize_message(m) for m in request.messages]
    _validate_messages(messages)
    _validate_tool_turn_pairing(messages)

    return ChatRequest(
        messages=messages,
        temperature=request.temperature,
        max_output_tokens=request.max_output_tokens,
        stop=request.stop,
        tools=tools,
        tool_choice=normalized_choice if tools is not None else None,
    )


def _normalize_message(msg: Message) -> Message:
    tool_calls = normalize_tool_calls(msg.tool_calls)
    return Message(
        role=msg.role,
        content=msg.content,
        tool_calls=tool_calls,
        tool_call_id=msg.tool_call_id,
        name=msg.name,
    )


def _validate_messages(messages: list[Message]) -> None:
    for i, msg in enumerate(messages):
        role = msg.role
        if role in ("system", "user"):
            if msg.content is None or not isinstance(msg.content, str):
                raise LLMError(
                    type="invalid_request",
                    message=f"messages[{i}] {role} content must be a string",
                )
            if msg.tool_calls is not None or msg.tool_call_id is not None:
                raise LLMError(
                    type="invalid_request",
                    message=f"messages[{i}] {role} must not have tool_calls/tool_call_id",
                )
        elif role == "assistant":
            has_content = isinstance(msg.content, str) and msg.content != ""
            has_empty_content = msg.content == "" or msg.content is None
            has_tools = bool(msg.tool_calls)
            if not has_tools and msg.content is None:
                raise LLMError(
                    type="invalid_request",
                    message=f"messages[{i}] assistant needs content or tool_calls",
                )
            if not has_tools and not isinstance(msg.content, str):
                raise LLMError(
                    type="invalid_request",
                    message=f"messages[{i}] assistant content must be a string",
                )
            if has_tools:
                _validate_assistant_tool_calls(i, msg.tool_calls or [])
            if msg.tool_call_id is not None:
                raise LLMError(
                    type="invalid_request",
                    message=f"messages[{i}] assistant must not have tool_call_id",
                )
            # allow content None when tool_calls present
            if has_tools and has_empty_content and msg.content is None:
                pass
            elif has_tools and msg.content is not None and not isinstance(msg.content, str):
                raise LLMError(
                    type="invalid_request",
                    message=f"messages[{i}] assistant content must be string or null",
                )
            _ = has_content  # silence lint
        elif role == "tool":
            tid = (msg.tool_call_id or "").strip()
            if not tid:
                raise LLMError(
                    type="invalid_request",
                    message=f"messages[{i}] tool tool_call_id must be non-empty",
                )
            if msg.content is None or not isinstance(msg.content, str):
                raise LLMError(
                    type="invalid_request",
                    message=f"messages[{i}] tool content must be a string",
                )
            if msg.tool_calls is not None:
                raise LLMError(
                    type="invalid_request",
                    message=f"messages[{i}] tool must not have tool_calls",
                )
        else:
            raise LLMError(
                type="invalid_request",
                message=f"messages[{i}] unknown role {role!r}",
            )


def _validate_assistant_tool_calls(index: int, calls: list[ToolCall]) -> None:
    seen: set[str] = set()
    for j, call in enumerate(calls):
        cid = (call.id or "").strip()
        name = (call.name or "").strip()
        if not cid:
            raise LLMError(
                type="invalid_request",
                message=f"messages[{index}].tool_calls[{j}] id must be non-empty",
            )
        if not name:
            raise LLMError(
                type="invalid_request",
                message=f"messages[{index}].tool_calls[{j}] name must be non-empty",
            )
        if cid in seen:
            raise LLMError(
                type="invalid_request",
                message=f"messages[{index}] duplicate tool_call id {cid!r}",
            )
        seen.add(cid)


def _validate_tool_turn_pairing(messages: list[Message]) -> None:
    """Strict mode: each tool round must have exactly one result per call id."""
    expected: set[str] | None = None
    seen_results: set[str] = set()

    def close_round(*, at_end: bool = False) -> None:
        nonlocal expected, seen_results
        if expected is None:
            return
        missing = expected - seen_results
        extra = seen_results - expected
        if missing or extra:
            parts = []
            if missing:
                parts.append(f"missing tool results for ids={sorted(missing)}")
            if extra:
                parts.append(f"unexpected tool_call_ids={sorted(extra)}")
            where = "at end of messages" if at_end else "before next non-tool message"
            raise LLMError(
                type="invalid_request",
                message=f"incomplete tool round {where}: " + "; ".join(parts),
            )
        expected = None
        seen_results = set()

    for msg in messages:
        if msg.role == "assistant" and msg.tool_calls:
            close_round()
            expected = {(c.id or "").strip() for c in msg.tool_calls}
            seen_results = set()
            continue
        if msg.role == "tool":
            if expected is None:
                raise LLMError(
                    type="invalid_request",
                    message=(
                        f"tool message tool_call_id={msg.tool_call_id!r} "
                        "has no matching open assistant tool_calls round"
                    ),
                )
            tid = (msg.tool_call_id or "").strip()
            if tid not in expected:
                raise LLMError(
                    type="invalid_request",
                    message=f"tool_call_id={tid!r} not in current tool round",
                )
            if tid in seen_results:
                raise LLMError(
                    type="invalid_request",
                    message=f"duplicate tool result for tool_call_id={tid!r}",
                )
            seen_results.add(tid)
            continue
        # non-tool message closes any open round
        close_round()

    close_round(at_end=True)


def map_tool_finish_token(raw: str | None) -> FinishReason | None:
    """Map upstream tokens that mean tool use (used before resolve_finish_reason)."""
    if raw is None:
        return None
    value = raw.strip().lower()
    if value in ("tool_calls", "tool_use", "function_call"):
        return "tool_calls"
    return None
