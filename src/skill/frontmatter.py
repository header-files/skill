"""Parse SKILL.md YAML frontmatter + body."""

from __future__ import annotations

import re
from typing import Any

from skill.errors import SkillInvalidFormatError, SkillMissingMetadataError

_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z",
    re.DOTALL,
)


def parse_skill_md(text: str, *, path: str, skill_name_hint: str | None = None) -> tuple[dict[str, Any], str]:
    """Return (metadata, body). Raises Skill* errors on failure."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise SkillInvalidFormatError(
            message="SKILL.md must start with YAML frontmatter delimited by ---",
            skill_name=skill_name_hint,
            path=path,
        )
    raw_yaml, body = match.group(1), match.group(2)
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover
        raise SkillInvalidFormatError(
            message="PyYAML is required to parse SKILL.md frontmatter",
            skill_name=skill_name_hint,
            path=path,
        ) from exc

    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        raise SkillInvalidFormatError(
            message=f"Invalid YAML frontmatter: {exc}",
            skill_name=skill_name_hint,
            path=path,
        ) from exc

    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise SkillInvalidFormatError(
            message="SKILL.md frontmatter must be a mapping",
            skill_name=skill_name_hint,
            path=path,
        )

    name = data.get("name")
    description = data.get("description")
    if name is None or (isinstance(name, str) and not name.strip()):
        raise SkillMissingMetadataError(
            message="missing required field 'name'",
            skill_name=skill_name_hint,
            path=path,
            field="name",
        )
    if not isinstance(name, str):
        raise SkillInvalidFormatError(
            message="'name' must be a string",
            skill_name=skill_name_hint,
            path=path,
        )
    if description is None or (isinstance(description, str) and not description.strip()):
        raise SkillMissingMetadataError(
            message="missing required field 'description'",
            skill_name=str(name).strip() if isinstance(name, str) else skill_name_hint,
            path=path,
            field="description",
        )
    if not isinstance(description, str):
        raise SkillInvalidFormatError(
            message="'description' must be a string",
            skill_name=str(name).strip(),
            path=path,
        )

    meta = {str(k): v for k, v in data.items()}
    meta["name"] = name.strip()
    meta["description"] = description.strip()
    return meta, body
