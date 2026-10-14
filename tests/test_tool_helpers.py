"""Unit tests for tool-calling validation and helpers."""

from __future__ import annotations

import pytest

from llm.errors import LLMError
from llm.protocols.tool_helpers import (
    build_tool_call,
    resolve_finish_reason,
    tool_call_is_complete,
    validate_chat_request,
)
from llm.types import ChatRequest, Message, ToolCall, ToolSpec


def test_build_tool_call_empty_object_vs_invalid_json() -> None:
    ok = build_tool_call(id="1", name="f", arguments_raw="{}")
    assert ok.arguments == {}
    assert ok.arguments_parse_error is None
    assert tool_call_is_complete(ok)

    bad = build_tool_call(id="1", name="f", arguments_raw="{")
    assert bad.arguments is None
    assert bad.arguments_parse_error is not None
    assert not tool_call_is_complete(bad)


def test_resolve_finish_reason_truncation_wins() -> None:
    incomplete = build_tool_call(
        id="1", name="f", arguments_raw="{", truncated=True
    )
    assert resolve_finish_reason("length", [incomplete]) == "length"

    complete = build_tool_call(id="1", name="f", arguments_raw='{"a":1}')
    assert resolve_finish_reason("stop", [complete]) == "tool_calls"


def test_tools_null_with_none_is_valid() -> None:
    req = validate_chat_request(
        ChatRequest(
            messages=[Message(role="user", content="hi")],
            tools=None,
            tool_choice="none",
        )
    )
    assert req.tools is None
    assert req.tool_choice is None


def test_empty_tools_with_required_invalid() -> None:
    with pytest.raises(LLMError) as exc:
        validate_chat_request(
            ChatRequest(
                messages=[Message(role="user", content="hi")],
                tools=[],
                tool_choice="required",
            )
        )
    assert exc.value.type == "invalid_request"


def test_tool_round_requires_exact_results() -> None:
    tools = [
        ToolCall(id="c1", name="a", arguments_raw="{}", arguments={}),
        ToolCall(id="c2", name="b", arguments_raw="{}", arguments={}),
    ]
    with pytest.raises(LLMError) as exc:
        validate_chat_request(
            ChatRequest(
                messages=[
                    Message(role="user", content="hi"),
                    Message(role="assistant", content="", tool_calls=tools),
                    Message(role="tool", content="ok", tool_call_id="c1"),
                    Message(role="user", content="next"),
                ]
            )
        )
    assert exc.value.type == "invalid_request"
    assert "missing" in exc.value.message


def test_duplicate_tool_result_invalid() -> None:
    tools = [ToolCall(id="c1", name="a", arguments_raw="{}", arguments={})]
    with pytest.raises(LLMError) as exc:
        validate_chat_request(
            ChatRequest(
                messages=[
                    Message(role="user", content="hi"),
                    Message(role="assistant", content=None, tool_calls=tools),
                    Message(role="tool", content="1", tool_call_id="c1"),
                    Message(role="tool", content="2", tool_call_id="c1"),
                ]
            )
        )
    assert "duplicate" in exc.value.message


def test_closed_tool_round_ok() -> None:
    tools = [ToolCall(id="c1", name="a", arguments_raw="{}", arguments={})]
    req = validate_chat_request(
        ChatRequest(
            messages=[
                Message(role="user", content="hi"),
                Message(role="assistant", content=None, tool_calls=tools),
                Message(role="tool", content="ok", tool_call_id="c1"),
                Message(role="user", content="thanks"),
            ],
            tools=[
                ToolSpec(
                    name="a",
                    description="d",
                    parameters={"type": "object", "properties": {}},
                )
            ],
            tool_choice="auto",
        )
    )
    assert req.tools is not None
    assert len(req.messages) == 4
