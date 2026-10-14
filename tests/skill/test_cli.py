from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from skill.cli.main import app

runner = CliRunner()


def test_cli_list_and_inspect(skills_root: Path) -> None:
    result = runner.invoke(
        app,
        ["list", "--skills-dir", str(skills_root)],
    )
    assert result.exit_code == 0, result.output
    assert "demo-skill" in result.stdout

    result2 = runner.invoke(
        app,
        ["inspect", "demo-skill", "--skills-dir", str(skills_root)],
    )
    assert result2.exit_code == 0, result2.output
    assert "Demo skill for tests" in result2.stdout
    assert "fingerprint:" in result2.stdout
