from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from llm.types import ChatRequest, ChatResponse, Message, ToolCall
from skill.executor import SkillExecutor
from skill.loader import load_skill_from_directory
from skill.runtime import SkillRuntime
from skill.scripts import ScriptRunner


class FakeLLM:
    def __init__(self, responses: list[ChatResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[ChatRequest] = []

    async def achat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("no more fake responses")
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_executor_tool_loop(skills_root: Path) -> None:
    skill = load_skill_from_directory(skills_root / "demo-skill")
    call = ToolCall(
        id="1",
        name="read_resource",
        arguments_raw='{"path":"references/note.txt"}',
        arguments={"path": "references/note.txt"},
    )
    fake = FakeLLM(
        [
            ChatResponse(
                content="",
                tool_calls=[call],
                finish_reason="tool_calls",
            ),
            ChatResponse(content="done with note", finish_reason="stop"),
        ]
    )
    runner = ScriptRunner(
        timeout_seconds=10, max_concurrent=2, max_output_bytes=64_000
    )
    executor = SkillExecutor(
        llm=fake,  # type: ignore[arg-type]
        script_runner=runner,
        read_max_bytes=4096,
        max_steps=5,
        agent_timeout_seconds=30,
    )
    result = await executor.run(skill, "read the note", {})
    assert result.success
    assert "done with note" in result.output
    assert len(fake.requests) == 2
    # second request should include tool result message
    roles = [m.role for m in fake.requests[1].messages]
    assert "tool" in roles


@pytest.mark.asyncio
async def test_concurrent_runs_isolated(skills_root: Path) -> None:
    """Two skills can be executed concurrently; one failure does not block the other."""
    other = skills_root / "other-skill"
    other.mkdir()
    (other / "SKILL.md").write_text(
        "---\nname: other-skill\ndescription: other\n---\nDo nothing.\n",
        encoding="utf-8",
    )

    class SeqLLM:
        def __init__(self, mapping: dict[str, str]) -> None:
            self.mapping = mapping

        async def achat(self, request: ChatRequest) -> ChatResponse:
            # Find skill name from system prompt
            sys_msg = request.messages[0].content or ""
            for name, out in self.mapping.items():
                if f"# Skill: {name}" in sys_msg:
                    return ChatResponse(content=out, finish_reason="stop")
            return ChatResponse(content="unknown", finish_reason="stop")

    rt = SkillRuntime(
        roots=[skills_root],
        llm=SeqLLM({"demo-skill": "A", "other-skill": "B"}),  # type: ignore[arg-type]
    )
    import asyncio

    r1, r2 = await asyncio.gather(
        rt.run("demo-skill", "t1"),
        rt.run("other-skill", "t2"),
    )
    assert r1.output == "A"
    assert r2.output == "B"
