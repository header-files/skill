"""SkillRuntime facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from common.config.skill import SkillSettings, load_skill_settings
from common.logger import get_logger, new_trace_id
from llm.client import LLMClient
from skill.discovery import discover_skills
from skill.errors import (
    SkillNameConflictError,
    SkillNotFoundError,
)
from skill.executor import SkillExecutor
from skill.loader import load_skill_from_directory
from skill.models import (
    ExecutionResult,
    ListResult,
    LoadedSkill,
    SkillSummary,
)
from skill.scripts import ScriptRunner

log = get_logger(__name__)


class SkillRuntime:
    """Discover, load, and execute Skills from configured roots."""

    def __init__(
        self,
        settings: SkillSettings | None = None,
        *,
        llm: LLMClient | None = None,
        roots: list[Path] | tuple[Path, ...] | None = None,
        env_path: str | Path | None = None,
    ) -> None:
        base = settings or load_skill_settings(env_path)
        if roots is not None:
            self.settings = SkillSettings(
                roots=tuple(Path(p).expanduser() for p in roots),
                fingerprint_mode=base.fingerprint_mode,
                script_timeout_seconds=base.script_timeout_seconds,
                script_max_concurrent=base.script_max_concurrent,
                script_max_output_bytes=base.script_max_output_bytes,
                agent_max_steps=base.agent_max_steps,
                agent_timeout_seconds=base.agent_timeout_seconds,
                read_max_bytes=base.read_max_bytes,
                chat_model_id=base.chat_model_id,
            )
        else:
            self.settings = base
        self._llm = llm
        self._cache: dict[str, LoadedSkill] = {}
        self._script_runner = ScriptRunner(
            timeout_seconds=self.settings.script_timeout_seconds,
            max_concurrent=self.settings.script_max_concurrent,
            max_output_bytes=self.settings.script_max_output_bytes,
        )

    def _get_llm(self) -> LLMClient:
        if self._llm is not None:
            return self._llm
        try:
            self._llm = LLMClient.from_env(self.settings.chat_model_id)
        except Exception as exc:  # noqa: BLE001
            from skill.errors import SkillExecutionError

            raise SkillExecutionError(
                message=f"LLM is not configured: {exc}",
            ) from exc
        return self._llm

    def list(self) -> ListResult:
        return discover_skills(
            self.settings.roots,
            fingerprint_mode=self.settings.fingerprint_mode,
        )

    def inspect(self, name: str) -> SkillSummary:
        loaded = self.load(name)
        return SkillSummary(
            name=loaded.name,
            description=loaded.description,
            directory=loaded.directory,
            fingerprint=loaded.fingerprint,
        )

    def load(self, name: str) -> LoadedSkill:
        summary = self._resolve_name(name)
        cached = self._cache.get(name)
        if cached is not None and cached.fingerprint == summary.fingerprint:
            return cached
        loaded = load_skill_from_directory(
            summary.directory,
            fingerprint_mode=self.settings.fingerprint_mode,
            expected_name=name,
        )
        self._cache[name] = loaded
        log.info(
            "skill loaded name=%s fingerprint=%s resources=%d",
            loaded.name,
            loaded.fingerprint,
            len(loaded.resources),
        )
        return loaded

    def reload(self, name: str | None = None) -> None:
        if name is None:
            self._cache.clear()
            log.info("skill cache cleared (all)")
            return
        self._cache.pop(name, None)
        log.info("skill cache cleared name=%s", name)

    async def run(
        self,
        name: str,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        loaded = self.load(name)
        # Re-check fingerprint consistency with discovery
        summary = self._resolve_name(name)
        if summary.fingerprint != loaded.fingerprint:
            self.reload(name)
            loaded = self.load(name)

        executor = SkillExecutor(
            llm=self._get_llm(),
            script_runner=self._script_runner,
            read_max_bytes=self.settings.read_max_bytes,
            max_steps=self.settings.agent_max_steps,
            agent_timeout_seconds=self.settings.agent_timeout_seconds,
        )
        return await executor.run(
            loaded,
            task,
            context,
            trace_id=new_trace_id(),
        )

    def _resolve_name(self, name: str) -> SkillSummary:
        result = self.list()
        # Detect conflict-only errors for this name
        conflict_paths = [
            e.path
            for e in result.discovery_errors
            if e.skill_name == name and "name conflict" in e.reason
        ]
        if conflict_paths:
            raise SkillNameConflictError(
                message=f"skill name '{name}' conflicts across multiple directories",
                skill_name=name,
                paths=tuple(conflict_paths),
            )
        for skill in result.skills:
            if skill.name == name:
                return skill
        raise SkillNotFoundError(
            message=f"skill not found: {name}",
            skill_name=name,
        )
