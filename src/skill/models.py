"""Skill Runtime data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

ResourceKind = Literal["references", "scripts", "assets", "other"]


@dataclass(frozen=True)
class ResourceEntry:
    relative_path: str
    kind: ResourceKind


@dataclass(frozen=True)
class SkillSummary:
    name: str
    description: str
    directory: Path
    fingerprint: str


@dataclass(frozen=True)
class DiscoveryError:
    path: str
    reason: str
    skill_name: str | None = None


@dataclass(frozen=True)
class ListResult:
    skills: tuple[SkillSummary, ...]
    discovery_errors: tuple[DiscoveryError, ...]


@dataclass(frozen=True)
class LoadedSkill:
    name: str
    description: str
    directory: Path
    instructions: str
    metadata: dict[str, Any]
    resources: tuple[ResourceEntry, ...]
    fingerprint: str
    skill_md_path: Path


@dataclass
class ExecutionResult:
    skill_name: str
    output: str
    errors: list[str] = field(default_factory=list)
    trace_id: str | None = None
    success: bool = True
