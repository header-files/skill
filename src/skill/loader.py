"""Load a Skill from disk."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from skill.errors import SkillNotFoundError
from skill.fingerprint import compute_fingerprint
from skill.frontmatter import parse_skill_md
from skill.models import LoadedSkill
from skill.resources import list_resources


def load_skill_from_directory(
    directory: Path,
    *,
    fingerprint_mode: str = "content",
    expected_name: str | None = None,
) -> LoadedSkill:
    directory = directory.resolve()
    skill_md = directory / "SKILL.md"
    if not skill_md.is_file():
        raise SkillNotFoundError(
            message=f"SKILL.md not found in {directory}",
            skill_name=expected_name,
        )
    text = skill_md.read_text(encoding="utf-8")
    meta, body = parse_skill_md(
        text, path=str(skill_md), skill_name_hint=expected_name or directory.name
    )
    name = str(meta["name"])
    if expected_name is not None and name != expected_name:
        raise SkillNotFoundError(
            message=(
                f"skill directory name metadata mismatch: "
                f"expected {expected_name!r}, got {name!r}"
            ),
            skill_name=expected_name,
        )
    fingerprint = compute_fingerprint(directory, mode=fingerprint_mode)
    resources = list_resources(directory)
    metadata: dict[str, Any] = dict(meta)
    return LoadedSkill(
        name=name,
        description=str(meta["description"]),
        directory=directory,
        instructions=body,
        metadata=metadata,
        resources=resources,
        fingerprint=fingerprint,
        skill_md_path=skill_md,
    )
