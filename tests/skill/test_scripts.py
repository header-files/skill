from __future__ import annotations

from pathlib import Path

import pytest

from skill.errors import SkillScriptError
from skill.scripts import OutputBudget, ScriptRunner


@pytest.mark.asyncio
async def test_run_script_ok(skills_root: Path) -> None:
    runner = ScriptRunner(
        timeout_seconds=10,
        max_concurrent=2,
        max_output_bytes=64_000,
    )
    result = await runner.run(
        skills_root / "demo-skill",
        "scripts/echo.py",
        ["hi"],
        skill_name="demo-skill",
    )
    assert result.exit_code == 0
    assert "echo-ok" in result.stdout
    assert "hi" in result.stdout


@pytest.mark.asyncio
async def test_output_budget_cap() -> None:
    budget = OutputBudget(max_bytes=10)
    over1 = await budget.claim_and_append("stdout", b"1234567890")
    assert over1 is False
    assert budget.remaining == 0
    over2 = await budget.claim_and_append("stderr", b"x")
    assert over2 is True
    assert budget.truncated is True
    assert len(budget.stdout) + len(budget.stderr) <= 10


@pytest.mark.asyncio
async def test_script_timeout(skills_root: Path, tmp_path: Path) -> None:
    skill = tmp_path / "slow"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: slow\ndescription: d\n---\n", encoding="utf-8"
    )
    script = skill / "scripts"
    script.mkdir()
    (script / "sleep.py").write_text(
        "import time\ntime.sleep(5)\n", encoding="utf-8"
    )
    runner = ScriptRunner(
        timeout_seconds=0.2,
        max_concurrent=1,
        max_output_bytes=1024,
    )
    with pytest.raises(SkillScriptError) as exc:
        await runner.run(skill, "scripts/sleep.py", skill_name="slow")
    assert "timed out" in exc.value.message
