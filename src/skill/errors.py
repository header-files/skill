"""Skill Runtime error types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SkillError(Exception):
    message: str
    skill_name: str | None = None

    def __str__(self) -> str:
        if self.skill_name:
            return f"[{self.skill_name}] {self.message}"
        return self.message


@dataclass
class SkillNotFoundError(SkillError):
    pass


@dataclass
class SkillNameConflictError(SkillError):
    paths: tuple[str, ...] = ()


@dataclass
class SkillInvalidFormatError(SkillError):
    path: str | None = None


@dataclass
class SkillMissingMetadataError(SkillError):
    path: str | None = None
    field: str | None = None


@dataclass
class SkillResourceNotFoundError(SkillError):
    path: str | None = None


@dataclass
class SkillResourceForbiddenError(SkillError):
    path: str | None = None


@dataclass
class SkillExecutionError(SkillError):
    pass


@dataclass
class SkillScriptError(SkillError):
    script_path: str | None = None
    exit_code: int | None = None
