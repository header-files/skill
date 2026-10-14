"""Unified client-facing types (protocol-agnostic)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]
FinishReason = Literal["stop", "length", "content_filter", "tool_calls"]
StreamChunkType = Literal["reasoning", "content", "finish"]
ToolChoice = Literal["auto", "none", "required"]


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments_raw: str = ""
    arguments: dict[str, Any] | None = None
    arguments_parse_error: str | None = None
    truncated: bool = False


@dataclass
class Message:
    role: Role
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass
class ChatRequest:
    messages: list[Message]
    temperature: float | None = None
    max_output_tokens: int | None = None
    stop: list[str] | None = None
    tools: list[ToolSpec] | None = None
    tool_choice: ToolChoice | None = None


@dataclass
class ChatResponse:
    content: str
    reasoning: str | None = None
    tool_calls: list[ToolCall] | None = None
    finish_reason: FinishReason | None = None
    model: str | None = None
    usage: Usage | None = None
    metadata: dict | None = None


@dataclass
class StreamChunk:
    type: StreamChunkType
    delta: str = ""
    finish_reason: FinishReason | None = None
    model: str | None = None
    usage: Usage | None = None
    tool_calls: list[ToolCall] | None = None
