from __future__ import annotations

from pathlib import Path

from skill.runtime import SkillRuntime


def test_reload_after_content_change(skills_root: Path) -> None:
    rt = SkillRuntime(roots=[skills_root])
    first = rt.load("demo-skill")
    fp1 = first.fingerprint
    note = skills_root / "demo-skill" / "references" / "note.txt"
    note.write_text("changed content", encoding="utf-8")
    rt.reload("demo-skill")
    second = rt.load("demo-skill")
    assert second.fingerprint != fp1
    assert second.fingerprint == rt.inspect("demo-skill").fingerprint
