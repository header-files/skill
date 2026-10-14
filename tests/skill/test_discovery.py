from __future__ import annotations

from pathlib import Path

from skill.discovery import discover_skills
from skill.runtime import SkillRuntime


def test_discover_valid_and_errors(skills_root: Path) -> None:
    result = discover_skills((skills_root,), fingerprint_mode="content")
    names = {s.name for s in result.skills}
    assert "demo-skill" in names
    assert "twin" not in names  # conflict excluded
    reasons = " ".join(e.reason for e in result.discovery_errors)
    assert "conflict" in reasons or "name conflict" in reasons
    assert any("description" in e.reason or "YAML" in e.reason or "yaml" in e.reason.lower() or "Invalid" in e.reason or "missing" in e.reason for e in result.discovery_errors)


def test_name_conflict_raises_on_load(skills_root: Path) -> None:
    rt = SkillRuntime(roots=[skills_root])
    from skill.errors import SkillNameConflictError
    import pytest

    with pytest.raises(SkillNameConflictError):
        rt.load("twin")
