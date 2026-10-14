"""Protocol tool-calling tests (mocked HTTP)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from common.config.models import ModelConfig
from llm.protocols.anthropic_messages import AnthropicMessagesAdapter
from llm.protocols.openai_completions import OpenAICompletionsAdapter
from llm.protocols.openai_responses import OpenAIResponsesAdapter
from llm.protocols.tool_helpers import validate_chat_request
from llm.types import ChatRequest, Message, ToolCall, ToolSpec


def _tool() -> ToolSpec:
    return ToolSpec(
        name="lookup",
        description="look up",
        parameters={
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        },
    )


def _completions_config() -> ModelConfig:
    return ModelConfig(
        id="chatgpt",
        protocol="openai-completions",
        name="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
    )


def _anthropic_config() -> ModelConfig:
    return ModelConfig(
        id="claude",
        protocol="anthropic-messages",
        name="claude-3-5-sonnet-latest",
        base_url="https://api.anthropic.com",
        api_key="sk-ant-test",
    )


def _responses_config() -> ModelConfig:
    return ModelConfig(
        id="oai-resp",
        protocol="openai-responses",
        name="gpt-4o",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
    )


@respx.mock
def test_completions_tools_request_and_response() -> None:
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "lookup",
                                        "arguments": '{"q":"x"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            },
        )
    )
    adapter = OpenAICompletionsAdapter(_completions_config())
    req = validate_chat_request(
        ChatRequest(
            messages=[Message(role="user", content="hi")],
            tools=[_tool()],
            tool_choice="auto",
        )
    )
    resp = adapter.chat(req)
    body = json.loads(route.calls.last.request.content.decode())
    assert body["tools"][0]["function"]["name"] == "lookup"
    assert body["tool_choice"] == "auto"
    assert resp.finish_reason == "tool_calls"
    assert resp.tool_calls is not None
    assert resp.tool_calls[0].id == "call_1"
    assert resp.tool_calls[0].arguments == {"q": "x"}


@respx.mock
def test_completions_multiturn_tool_result_wire() -> None:
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "done"}, "finish_reason": "stop"}
                ]
            },
        )
    )
    adapter = OpenAICompletionsAdapter(_completions_config())
    call = ToolCall(
        id="call_1",
        name="lookup",
        arguments_raw='{"q":"x"}',
        arguments={"q": "x"},
    )
    req = validate_chat_request(
        ChatRequest(
            messages=[
                Message(role="user", content="hi"),
                Message(role="assistant", content=None, tool_calls=[call]),
                Message(role="tool", content='{"ok":true}', tool_call_id="call_1"),
            ],
            tools=[_tool()],
        )
    )
    adapter.chat(req)
    body = json.loads(route.calls.last.request.content.decode())
    assert body["messages"][1]["tool_calls"][0]["id"] == "call_1"
    assert body["messages"][2]["role"] == "tool"
    assert body["messages"][2]["tool_call_id"] == "call_1"


@respx.mock
def test_completions_stream_aggregates_tool_calls() -> None:
    sse = (
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
        '"function":{"name":"lookup","arguments":""}}]}}]}\n\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
        '"function":{"arguments":"{\\"q\\":"}}]}}]}\n\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
        '"function":{"arguments":"\\"y\\"}"}}]},"finish_reason":"tool_calls"}]}\n\n'
        "data: [DONE]\n\n"
    )
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            content=sse.encode(),
            headers={"Content-Type": "text/event-stream"},
        )
    )
    adapter = OpenAICompletionsAdapter(_completions_config())
    chunks = list(
        adapter.chat_stream(
            ChatRequest(messages=[Message(role="user", content="hi")], tools=[_tool()])
        )
    )
    assert [c.type for c in chunks].count("finish") == 1
    finish = chunks[-1]
    assert finish.type == "finish"
    assert finish.tool_calls is not None
    assert finish.tool_calls[0].arguments == {"q": "y"}
    assert finish.finish_reason == "tool_calls"


@respx.mock
def test_anthropic_tool_use_and_none_without_tools() -> None:
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu_1",
                        "name": "lookup",
                        "input": {"q": "z"},
                    }
                ],
                "stop_reason": "tool_use",
            },
        )
    )
    adapter = AnthropicMessagesAdapter(_anthropic_config())
    req = validate_chat_request(
        ChatRequest(
            messages=[Message(role="user", content="hi")],
            tools=[_tool()],
            tool_choice="auto",
        )
    )
    resp = adapter.chat(req)
    body = json.loads(route.calls.last.request.content.decode())
    assert body["tools"][0]["name"] == "lookup"
    assert body["tool_choice"] == {"type": "auto"}
    assert resp.tool_calls is not None
    assert resp.tool_calls[0].id == "tu_1"
    assert resp.finish_reason == "tool_calls"

    # empty tools + none → omit both
    route.calls.clear()
    route.mock(
        return_value=httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "hi"}], "stop_reason": "end_turn"},
        )
    )
    req2 = validate_chat_request(
        ChatRequest(
            messages=[Message(role="user", content="hi")],
            tools=[],
            tool_choice="none",
        )
    )
    adapter.chat(req2)
    body2 = json.loads(route.calls.last.request.content.decode())
    assert "tools" not in body2
    assert "tool_choice" not in body2


@respx.mock
def test_anthropic_stream_input_json_delta_interleaved() -> None:
    events = [
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": "a", "name": "lookup"},
        },
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "b", "name": "lookup"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"q":"'},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"q":"'},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '1"}'},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '2"}'},
        },
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
        {"type": "message_stop"},
    ]
    sse = "".join(f"data: {json.dumps(e)}\n\n" for e in events)
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            content=sse.encode(),
            headers={"Content-Type": "text/event-stream"},
        )
    )
    adapter = AnthropicMessagesAdapter(_anthropic_config())
    chunks = list(
        adapter.chat_stream(
            ChatRequest(messages=[Message(role="user", content="hi")], tools=[_tool()])
        )
    )
    finish = chunks[-1]
    assert finish.type == "finish"
    assert finish.tool_calls is not None
    assert len(finish.tool_calls) == 2
    by_id = {c.id: c for c in finish.tool_calls}
    assert by_id["a"].arguments == {"q": "1"}
    assert by_id["b"].arguments == {"q": "2"}


@respx.mock
def test_responses_uses_call_id_and_string_arguments() -> None:
    route = respx.post("https://api.openai.com/v1/responses").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "gpt-4o",
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc_item_should_not_be_id",
                        "call_id": "call_abc",
                        "name": "lookup",
                        "arguments": '{"q":"r"}',
                    }
                ],
            },
        )
    )
    adapter = OpenAIResponsesAdapter(_responses_config())
    call = ToolCall(
        id="call_prev",
        name="lookup",
        arguments_raw='{"q":"prev"}',
        arguments={"q": "prev"},
    )
    req = validate_chat_request(
        ChatRequest(
            messages=[
                Message(role="user", content="hi"),
                Message(role="assistant", content=None, tool_calls=[call]),
                Message(role="tool", content="ok", tool_call_id="call_prev"),
            ],
            tools=[_tool()],
        )
    )
    resp = adapter.chat(req)
    body = json.loads(route.calls.last.request.content.decode())
    fn_calls = [x for x in body["input"] if x.get("type") == "function_call"]
    assert fn_calls[0]["call_id"] == "call_prev"
    assert isinstance(fn_calls[0]["arguments"], str)
    outs = [x for x in body["input"] if x.get("type") == "function_call_output"]
    assert outs[0]["call_id"] == "call_prev"
    assert resp.tool_calls is not None
    assert resp.tool_calls[0].id == "call_abc"
    assert resp.tool_calls[0].id != "fc_item_should_not_be_id"
