"""Shared protocol helpers: SSE parsing, finish_reason mapping, error mapping."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from common.logger import get_logger
from llm.errors import ErrorType, LLMError
from llm.types import FinishReason, Usage

logger = get_logger(__name__)


def join_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    # Avoid duplicating /v1 if base already ends with it and path starts with /v1
    return base + path


def map_finish_reason(raw: str | None) -> FinishReason | None:
    if raw is None:
        return None
    value = raw.strip().lower()
    mapping = {
        "stop": "stop",
        "end_turn": "stop",
        "stop_sequence": "stop",
        "length": "length",
        "max_tokens": "length",
        "max_output_tokens": "length",
        "content_filter": "content_filter",
        "content_filtered": "content_filter",
        "tool_calls": "tool_calls",
        "tool_use": "tool_calls",
        "function_call": "tool_calls",
    }
    return mapping.get(value)  # type: ignore[return-value]


def parse_usage_openai_chat(data: dict[str, Any] | None) -> Usage | None:
    if not data:
        return None
    prompt = data.get("prompt_tokens")
    completion = data.get("completion_tokens")
    total = data.get("total_tokens")
    if prompt is None and completion is None and total is None:
        return None
    return Usage(
        input_tokens=prompt,
        output_tokens=completion,
        total_tokens=total,
    )


def parse_usage_tokens(data: dict[str, Any] | None) -> Usage | None:
    """Parse usage with input_tokens / output_tokens style fields."""
    if not data:
        return None
    input_tokens = data.get("input_tokens")
    output_tokens = data.get("output_tokens")
    total = data.get("total_tokens")
    if total is None and input_tokens is not None and output_tokens is not None:
        total = input_tokens + output_tokens
    if input_tokens is None and output_tokens is None and total is None:
        return None
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total,
    )


def classify_http_error(status_code: int, provider_code: str | None) -> ErrorType:
    if status_code in (401, 403):
        return "auth_error"
    code = (provider_code or "").lower()
    if any(
        token in code
        for token in ("unsupported", "invalid_request", "invalid_value")
    ):
        return "unsupported_parameter"
    if status_code == 429 or status_code >= 500:
        return "api_error"
    return "api_error"


def retryable_for_status(status_code: int) -> bool | None:
    if status_code == 429 or status_code >= 500:
        return True
    if 400 <= status_code < 500:
        return False
    return None


def raise_from_http_body(status_code: int, body: str, *, protocol: str) -> None:
    message = body.strip() or f"HTTP {status_code}"
    provider_code: str | None = None
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        payload = {}

    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            message = str(err.get("message") or message)
            provider_code = err.get("code") or err.get("type")
            if provider_code is not None:
                provider_code = str(provider_code)
        elif isinstance(err, str):
            message = err
        elif "message" in payload:
            message = str(payload["message"])
            provider_code = (
                str(payload["type"]) if payload.get("type") is not None else None
            )

    # Prefer message/code at ERROR (visible at default INFO+); raw body only at DEBUG.
    logger.error(
        "Upstream %s error status=%s code=%s message=%s",
        protocol,
        status_code,
        provider_code,
        message,
    )
    logger.debug(
        "Upstream %s error body=%s",
        protocol,
        body[:500],
    )

    raise LLMError(
        type=classify_http_error(status_code, provider_code),
        message=message,
        status_code=status_code,
        provider_code=provider_code,
        retryable=retryable_for_status(status_code),
    )


def iter_sse_data_lines(lines: Iterator[str]) -> Iterator[str]:
    """Yield SSE `data:` payloads; skip comments/empty; stop at [DONE]."""
    for line in lines:
        if line.startswith("__HTTP_ERROR__:"):
            # status:body encoded by transport
            _, rest = line.split(":", 1)
            status_str, body = rest.split(":", 1)
            raise_from_http_body(int(status_str), body, protocol="sse")
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            data = line[5:].lstrip()
            if data == "[DONE]":
                return
            yield data


def parse_json_object(raw: str) -> dict[str, Any] | None:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
