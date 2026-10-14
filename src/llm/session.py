"""Chat session: maintains conversation context."""

from __future__ import annotations

from common.logger import get_logger
from llm.client import LLMClient
from llm.types import ChatRequest, ChatResponse, Message, StreamChunk

log = get_logger(__name__)


class ChatSession:
    """In-memory multi-turn session over a unified LLMClient."""

    def __init__(
        self,
        client: LLMClient,
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> None:
        self.client = client
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.messages: list[Message] = []
        if system_prompt:
            self.messages.append(Message(role="system", content=system_prompt))

    def clear(self) -> None:
        system = [m for m in self.messages if m.role == "system"]
        self.messages = list(system)
        log.info(
            "Session cleared model_id=%s remaining_messages=%d",
            self.client.config.id,
            len(self.messages),
        )

    def switch_client(self, client: LLMClient, *, clear_history: bool = True) -> None:
        """Switch underlying model client.

        By default clears non-system history to avoid cross-protocol context issues.
        """
        old_id = self.client.config.id
        self.client = client
        if clear_history:
            self.clear()
        log.info(
            "Session switched model %s -> %s clear_history=%s messages=%d",
            old_id,
            client.config.id,
            clear_history,
            len(self.messages),
        )

    def _request(self) -> ChatRequest:
        return ChatRequest(
            messages=list(self.messages),
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
            stop=None,
        )

    def send(self, user_text: str) -> ChatResponse:
        self.messages.append(Message(role="user", content=user_text))
        model_id = self.client.config.id
        log.info(
            "Session turn start model_id=%s messages=%d stream=false",
            model_id,
            len(self.messages),
        )
        try:
            response = self.client.chat(self._request())
        except Exception as exc:
            self.messages.pop()
            log.error(
                "Session turn failed model_id=%s messages=%d error=%s",
                model_id,
                len(self.messages),
                exc,
            )
            raise
        self.messages.append(
            Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            )
        )
        log.info(
            "Session turn success model_id=%s messages=%d finish_reason=%s "
            "tool_calls_count=%d",
            model_id,
            len(self.messages),
            response.finish_reason,
            len(response.tool_calls) if response.tool_calls else 0,
        )
        return response

    def send_stream(self, user_text: str):
        """Yield StreamChunks; append assistant only after successful finish."""
        self.messages.append(Message(role="user", content=user_text))
        model_id = self.client.config.id
        content_parts: list[str] = []
        finished = False
        finish_reason = None
        finish_tool_calls = None
        log.info(
            "Session turn start model_id=%s messages=%d stream=true",
            model_id,
            len(self.messages),
        )
        try:
            for chunk in self.client.chat_stream(self._request()):
                if chunk.type == "content" and chunk.delta:
                    content_parts.append(chunk.delta)
                if chunk.type == "finish":
                    finished = True
                    finish_reason = chunk.finish_reason
                    finish_tool_calls = chunk.tool_calls
                yield chunk
            if finished:
                self.messages.append(
                    Message(
                        role="assistant",
                        content="".join(content_parts),
                        tool_calls=finish_tool_calls,
                    )
                )
                log.info(
                    "Session turn success model_id=%s messages=%d "
                    "finish_reason=%s stream=true",
                    model_id,
                    len(self.messages),
                    finish_reason,
                )
            else:
                self.messages.pop()
                log.warning(
                    "Session turn incomplete model_id=%s (no finish chunk)",
                    model_id,
                )
        except Exception as exc:
            self.messages.pop()
            log.error(
                "Session turn failed model_id=%s messages=%d error=%s stream=true",
                model_id,
                len(self.messages),
                exc,
            )
            raise
