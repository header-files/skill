"""CLI for Skill Runtime (thin wrapper)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import typer

from common.logger import setup_logging
from skill.errors import SkillError
from skill.runtime import SkillRuntime

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Skill Runtime CLI")


def _runtime(skills_dir: Optional[Path], env_path: Optional[Path]) -> SkillRuntime:
    setup_logging(env_path=env_path)
    roots = [skills_dir] if skills_dir is not None else None
    return SkillRuntime(roots=roots, env_path=env_path)


def _skills_dir_option() -> Optional[Path]:
    return typer.Option(
        None,
        "--skills-dir",
        help="Override SKILL_ROOTS with a single directory",
    )


def _env_file_option() -> Optional[Path]:
    return typer.Option(
        None,
        "--env-file",
        help="Path to .env",
    )


@app.command("list")
def list_cmd(
    skills_dir: Optional[Path] = typer.Option(
        None,
        "--skills-dir",
        help="Override SKILL_ROOTS with a single directory",
    ),
    env_file: Optional[Path] = typer.Option(
        None,
        "--env-file",
        help="Path to .env",
    ),
) -> None:
    """List discovered Skills."""
    rt = _runtime(skills_dir, env_file)
    result = rt.list()
    if not result.skills and not result.discovery_errors:
        typer.echo("No skills found.")
        return
    for s in result.skills:
        typer.echo(f"{s.name}\t{s.description}\t{s.directory}")
    for err in result.discovery_errors:
        typer.echo(f"ERROR\t{err.path}\t{err.reason}", err=True)


@app.command("inspect")
def inspect_cmd(
    name: str = typer.Argument(..., help="Skill name"),
    skills_dir: Optional[Path] = typer.Option(
        None,
        "--skills-dir",
        help="Override SKILL_ROOTS with a single directory",
    ),
    env_file: Optional[Path] = typer.Option(
        None,
        "--env-file",
        help="Path to .env",
    ),
) -> None:
    """Show Skill summary and full instructions."""
    rt = _runtime(skills_dir, env_file)
    try:
        loaded = rt.load(name)
    except SkillError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"name: {loaded.name}")
    typer.echo(f"description: {loaded.description}")
    typer.echo(f"directory: {loaded.directory}")
    typer.echo(f"fingerprint: {loaded.fingerprint}")
    typer.echo(f"resources: {len(loaded.resources)}")
    for r in loaded.resources:
        typer.echo(f"  - {r.relative_path} ({r.kind})")
    typer.echo("---")
    typer.echo(loaded.instructions)


@app.command("run")
def run_cmd(
    name: str = typer.Argument(..., help="Skill name"),
    task: str = typer.Option(..., "--task", help="Task for the Skill"),
    context: Optional[str] = typer.Option(
        None,
        "--context",
        help='JSON object context, e.g. \'{"k":"v"}\'',
    ),
    skills_dir: Optional[Path] = typer.Option(
        None,
        "--skills-dir",
        help="Override SKILL_ROOTS with a single directory",
    ),
    env_file: Optional[Path] = typer.Option(
        None,
        "--env-file",
        help="Path to .env",
    ),
) -> None:
    """Execute a Skill."""
    ctx_obj: dict = {}
    if context:
        try:
            parsed = json.loads(context)
        except json.JSONDecodeError as exc:
            typer.echo(f"invalid --context JSON: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        if not isinstance(parsed, dict):
            typer.echo("--context must be a JSON object", err=True)
            raise typer.Exit(code=1)
        ctx_obj = parsed

    rt = _runtime(skills_dir, env_file)
    try:
        result = asyncio.run(rt.run(name, task, ctx_obj))
    except SkillError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(result.output)
    if result.errors:
        for e in result.errors:
            typer.echo(f"ERROR: {e}", err=True)
    if not result.success:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
