"""LLM agent loop that executes a Skill with three sandboxed tools."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from common.logger import get_logger, new_trace_id, traced
from llm.client import LLMClient
from llm.errors import LLMError
from llm.types import ChatRequest, Message, ToolCall, ToolSpec
from skill.errors import SkillExecutionError, SkillScriptError
from skill.models import ExecutionResult, LoadedSkill
from skill.resources import read_resource_text
from skill.scripts import ScriptRunner

log = get_logger(__name__)

_TOOL_SPECS = [
    ToolSpec(
        name="list_resources",
        description="List relative resource paths available in this Skill.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    ToolSpec(
        name="read_resource",
        description="Read a text resource file inside this Skill by relative path.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path within the Skill directory",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="run_script",
        description="Run a script file inside this Skill (scripts/*.py or *.sh).",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the script",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional argv strings",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
]


class SkillExecutor:
    def __init__(
        self,
        *,
        llm: LLMClient,
        script_runner: ScriptRunner,
        read_max_bytes: int,
        max_steps: int,
        agent_timeout_seconds: float,
    ) -> None:
        self.llm = llm
        self.script_runner = script_runner
        self.read_max_bytes = read_max_bytes
        self.max_steps = max_steps
        self.agent_timeout_seconds = agent_timeout_seconds

    async def run(
        self,
        skill: LoadedSkill,
        task: str,
        context: dict[str, Any] | None = None,
        *,
        trace_id: str | None = None,
    ) -> ExecutionResult:
        tid = trace_id or new_trace_id()
        with traced(trace_id=tid):
            log.info(
                "skill run start name=%s fingerprint=%s task_chars=%d",
                skill.name,
                skill.fingerprint,
                len(task),
            )
            try:
                result = await asyncio.wait_for(
                    self._agent_loop(skill, task, context or {}),
                    timeout=self.agent_timeout_seconds,
                )
                result.trace_id = tid
                log.info(
                    "skill run done name=%s success=%s errors=%d",
                    skill.name,
                    result.success,
                    len(result.errors),
                )
                return result
            except asyncio.TimeoutError as exc:
                await self.script_runner.kill_current()
                log.error(
                    "skill run agent timeout name=%s seconds=%.1f",
                    skill.name,
                    self.agent_timeout_seconds,
                )
                raise SkillExecutionError(
                    message=(
                        f"agent timed out after {self.agent_timeout_seconds}s"
                    ),
                    skill_name=skill.name,
                ) from exc
            except asyncio.CancelledError:
                await self.script_runner.kill_current()
                raise

    async def _agent_loop(
        self,
        skill: LoadedSkill,
        task: str,
        context: dict[str, Any],
    ) -> ExecutionResult:
        errors: list[str] = []
        system = (
            "You are a Skill execution agent. Follow the Skill instructions below "
            "to complete the user's task. Use only the provided tools to access "
            "Skill resources and scripts. When finished, respond with a clear "
            "final answer and no further tool calls.\n\n"
            f"# Skill: {skill.name}\n\n{skill.instructions}"
        )
        user_payload = {"task": task, "context": context}
        messages: list[Message] = [
            Message(role="system", content=system),
            Message(
                role="user",
                content=json.dumps(user_payload, ensure_ascii=False),
            ),
        ]

        for step in range(1, self.max_steps + 1):
            log.info("skill agent step=%d/%d name=%s", step, self.max_steps, skill.name)
            try:
                response = await self.llm.achat(
                    ChatRequest(
                        messages=messages,
                        tools=_TOOL_SPECS,
                        tool_choice="auto",
                    )
                )
            except LLMError as exc:
                raise SkillExecutionError(
                    message=f"LLM call failed: {exc}",
                    skill_name=skill.name,
                ) from exc

            if not response.tool_calls:
                return ExecutionResult(
                    skill_name=skill.name,
                    output=response.content or "",
                    errors=errors,
                    success=True,
                )

            # Append assistant with full tool_calls, then execute serially
            messages.append(
                Message(
                    role="assistant",
                    content=response.content or None,
                    tool_calls=response.tool_calls,
                )
            )
            for call in response.tool_calls:
                tool_content = await self._dispatch_tool(skill, call, errors)
                messages.append(
                    Message(
                        role="tool",
                        content=tool_content,
                        tool_call_id=call.id,
                        name=call.name,
                    )
                )

        raise SkillExecutionError(
            message=f"agent exceeded max steps ({self.max_steps})",
            skill_name=skill.name,
        )

    async def _dispatch_tool(
        self,
        skill: LoadedSkill,
        call: ToolCall,
        errors: list[str],
    ) -> str:
        if call.truncated or call.arguments is None:
            msg = (
                f"tool call not executable: truncated={call.truncated} "
                f"parse_error={call.arguments_parse_error!r}"
            )
            errors.append(msg)
            return json.dumps({"error": msg}, ensure_ascii=False)

        name = call.name
        args = call.arguments

        try:
            if name == "list_resources":
                # Use snapshot from LoadedSkill (entry snapshot), not re-scan
                items = [
                    {"path": r.relative_path, "kind": r.kind} for r in skill.resources
                ]
                return json.dumps({"resources": items}, ensure_ascii=False)

            if name == "read_resource":
                path = args.get("path")
                if not isinstance(path, str):
                    return json.dumps(
                        {"error": "path must be a string"}, ensure_ascii=False
                    )
                text = await asyncio.to_thread(
                    read_resource_text,
                    skill.directory,
                    path,
                    max_bytes=self.read_max_bytes,
                    skill_name=skill.name,
                )
                return json.dumps({"path": path, "content": text}, ensure_ascii=False)

            if name == "run_script":
                path = args.get("path")
                if not isinstance(path, str):
                    return json.dumps(
                        {"error": "path must be a string"}, ensure_ascii=False
                    )
                raw_args = args.get("args")
                script_args: list[str] | None = None
                if raw_args is not None:
                    if not isinstance(raw_args, list) or not all(
                        isinstance(a, str) for a in raw_args
                    ):
                        return json.dumps(
                            {"error": "args must be a list of strings"},
                            ensure_ascii=False,
                        )
                    script_args = list(raw_args)
                result = await self.script_runner.run(
                    skill.directory,
                    path,
                    script_args,
                    skill_name=skill.name,
                )
                return json.dumps(
                    {
                        "exit_code": result.exit_code,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    },
                    ensure_ascii=False,
                )

            return json.dumps(
                {"error": "unknown_tool", "name": name},
                ensure_ascii=False,
            )
        except SkillScriptError as exc:
            errors.append(str(exc))
            return json.dumps(
                {
                    "error": "script_error",
                    "message": exc.message,
                    "script_path": exc.script_path,
                    "exit_code": exc.exit_code,
                },
                ensure_ascii=False,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            return json.dumps(
                {"error": type(exc).__name__, "message": str(exc)},
                ensure_ascii=False,
            )
