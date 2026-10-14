from __future__ import annotations

from pathlib import Path

import pytest

from skill.errors import SkillResourceForbiddenError, SkillResourceNotFoundError
from skill.loader import load_skill_from_directory
from skill.resources import read_resource_text, resolve_under_root


def test_read_resource_and_traversal(skills_root: Path) -> None:
    loaded = load_skill_from_directory(skills_root / "demo-skill")
    text = read_resource_text(
        loaded.directory, "references/note.txt", max_bytes=1024
    )
    assert "hello from note" in text

    with pytest.raises(SkillResourceForbiddenError):
        resolve_under_root(loaded.directory, "../secret")

    with pytest.raises(SkillResourceForbiddenError):
        resolve_under_root(loaded.directory, "/etc/passwd")

    with pytest.raises(SkillResourceNotFoundError):
        read_resource_text(
            loaded.directory, "references/missing.txt", max_bytes=1024
        )
