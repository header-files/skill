"""Unified LLM client entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

from common.config.models import ModelConfig, get_model, load_models
from common.logger import get_logger
from llm.protocols.registry import create_adapter
from llm.protocols.tool_helpers import validate_chat_request
from llm.transport.http import HttpTransport
from llm.types import ChatRequest, ChatResponse, StreamChunk

log = get_logger(__name__)


class LLMClient:
    def __init__(
        self,
        config: ModelConfig,
        *,
        transport: HttpTransport | None = None,
    ) -> None:
        self.config = config
        self._adapter = create_adapter(config, transport=transport)

    @classmethod
    def from_env(
        cls,
        model_id: str | None = None,
        *,
        env_path: str | Path | None = None,
    ) -> LLMClient:
        config = get_model(model_id, env_path=env_path)
        return cls(config)

    @classmethod
    def list_models(
        cls,
        *,
        env_path: str | Path | None = None,
    ) -> tuple[str, dict[str, ModelConfig]]:
        return load_models(env_path)

    def _prepare(self, request: ChatRequest) -> ChatRequest:
        return validate_chat_request(request)

    @staticmethod
    def _tools_log_fields(request: ChatRequest) -> tuple[int, str | None]:
        count = len(request.tools) if request.tools else 0
        choice = request.tool_choice
        return count, choice

    def chat(self, request: ChatRequest) -> ChatResponse:
        request = self._prepare(request)
        tools_count, tool_choice = self._tools_log_fields(request)
        log.info(
            "chat start model_id=%s protocol=%s name=%s messages=%d "
            "tools_count=%d tool_choice=%s",
            self.config.id,
            self.config.protocol,
            self.config.name,
            len(request.messages),
            tools_count,
            tool_choice or "-",
        )
        try:
            response = self._adapter.chat(request)
        except Exception as exc:
            log.error(
                "chat failed model_id=%s protocol=%s error=%s",
                self.config.id,
                self.config.protocol,
                exc,
            )
            raise
        tool_calls_count = len(response.tool_calls) if response.tool_calls else 0
        names = (
            ",".join(c.name for c in response.tool_calls) if response.tool_calls else "-"
        )
        log.info(
            "chat done model_id=%s finish_reason=%s has_reasoning=%s "
            "tool_calls_count=%d tool_names=%s",
            self.config.id,
            response.finish_reason,
            bool(response.reasoning),
            tool_calls_count,
            names,
        )
        return response

    def chat_stream(self, request: ChatRequest) -> Iterator[StreamChunk]:
        request = self._prepare(request)
        tools_count, tool_choice = self._tools_log_fields(request)
        log.info(
            "chat_stream start model_id=%s protocol=%s name=%s messages=%d "
            "tools_count=%d tool_choice=%s",
            self.config.id,
            self.config.protocol,
            self.config.name,
            len(request.messages),
            tools_count,
            tool_choice or "-",
        )
        finish_reason = None
        finished = False
        try:
            for chunk in self._adapter.chat_stream(request):
                if chunk.type == "finish":
                    finished = True
                    finish_reason = chunk.finish_reason
                yield chunk
        except Exception as exc:
            log.error(
                "chat_stream failed model_id=%s protocol=%s error=%s",
                self.config.id,
                self.config.protocol,
                exc,
            )
            raise
        if finished:
            log.info(
                "chat_stream done model_id=%s finish_reason=%s",
                self.config.id,
                finish_reason,
            )
        else:
            log.warning(
                "chat_stream ended without finish model_id=%s",
                self.config.id,
            )

    async def achat(self, request: ChatRequest) -> ChatResponse:
        request = self._prepare(request)
        tools_count, tool_choice = self._tools_log_fields(request)
        log.info(
            "achat start model_id=%s protocol=%s name=%s messages=%d "
            "tools_count=%d tool_choice=%s",
            self.config.id,
            self.config.protocol,
            self.config.name,
            len(request.messages),
            tools_count,
            tool_choice or "-",
        )
        try:
            response = await self._adapter.achat(request)
        except Exception as exc:
            log.error(
                "achat failed model_id=%s protocol=%s error=%s",
                self.config.id,
                self.config.protocol,
                exc,
            )
            raise
        tool_calls_count = len(response.tool_calls) if response.tool_calls else 0
        names = (
            ",".join(c.name for c in response.tool_calls) if response.tool_calls else "-"
        )
        log.info(
            "achat done model_id=%s finish_reason=%s has_reasoning=%s "
            "tool_calls_count=%d tool_names=%s",
            self.config.id,
            response.finish_reason,
            bool(response.reasoning),
            tool_calls_count,
            names,
        )
        return response

    async def achat_stream(self, request: ChatRequest) -> AsyncIterator[StreamChunk]:
        request = self._prepare(request)
        tools_count, tool_choice = self._tools_log_fields(request)
        log.info(
            "achat_stream start model_id=%s protocol=%s name=%s messages=%d "
            "tools_count=%d tool_choice=%s",
            self.config.id,
            self.config.protocol,
            self.config.name,
            len(request.messages),
            tools_count,
            tool_choice or "-",
        )
        finish_reason = None
        finished = False
        try:
            async for chunk in self._adapter.achat_stream(request):
                if chunk.type == "finish":
                    finished = True
                    finish_reason = chunk.finish_reason
                yield chunk
        except Exception as exc:
            log.error(
                "achat_stream failed model_id=%s protocol=%s error=%s",
                self.config.id,
                self.config.protocol,
                exc,
            )
            raise
        if finished:
            log.info(
                "achat_stream done model_id=%s finish_reason=%s",
                self.config.id,
                finish_reason,
            )
        else:
            log.warning(
                "achat_stream ended without finish model_id=%s",
                self.config.id,
            )
