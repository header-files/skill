"""Unified error types for LLM client calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ErrorType = Literal[
    "auth_error",
    "api_error",
    "timeout_error",
    "network_error",
    "stream_error",
    "unsupported_parameter",
    "invalid_request",
]


@dataclass
class LLMError(Exception):
    type: ErrorType
    message: str
    status_code: int | None = None
    provider_code: str | None = None
    retryable: bool | None = None

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        if self.provider_code:
            parts.append(f"code={self.provider_code}")
        return " | ".join(parts)
