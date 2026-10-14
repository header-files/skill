"""Sandboxed resource listing and reading within a Skill directory."""

from __future__ import annotations

import os
from pathlib import Path

from skill.errors import SkillResourceForbiddenError, SkillResourceNotFoundError
from skill.fingerprint import iter_skill_files
from skill.models import ResourceEntry, ResourceKind


def classify_resource(relative_path: str) -> ResourceKind:
    top = relative_path.split("/", 1)[0]
    if top == "references":
        return "references"
    if top == "scripts":
        return "scripts"
    if top == "assets":
        return "assets"
    return "other"


def list_resources(skill_root: Path) -> tuple[ResourceEntry, ...]:
    root = skill_root.resolve()
    entries: list[ResourceEntry] = []
    for path in iter_skill_files(root):
        rel = path.relative_to(root).as_posix()
        if rel == "SKILL.md":
            continue
        entries.append(ResourceEntry(relative_path=rel, kind=classify_resource(rel)))
    return tuple(entries)


def normalize_relative_path(relative_path: str) -> str:
    if relative_path is None:
        raise SkillResourceForbiddenError(message="path is empty", path=relative_path)
    text = relative_path.strip()
    if not text:
        raise SkillResourceForbiddenError(message="path is empty", path=relative_path)
    if text.startswith("/") or text.startswith("~"):
        raise SkillResourceForbiddenError(
            message="absolute paths are forbidden",
            path=relative_path,
        )
    # Reject Windows drive paths
    if len(text) >= 2 and text[1] == ":":
        raise SkillResourceForbiddenError(
            message="absolute paths are forbidden",
            path=relative_path,
        )
    parts = []
    for part in text.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise SkillResourceForbiddenError(
                message="path traversal is forbidden",
                path=relative_path,
            )
        parts.append(part)
    if not parts:
        raise SkillResourceForbiddenError(message="path is empty", path=relative_path)
    return "/".join(parts)


def resolve_under_root(skill_root: Path, relative_path: str) -> Path:
    """Resolve relative_path under skill_root; raise if escapes."""
    rel = normalize_relative_path(relative_path)
    root = skill_root.resolve()
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SkillResourceForbiddenError(
            message="path escapes skill directory",
            path=relative_path,
        ) from exc
    return candidate


def read_resource_text(
    skill_root: Path,
    relative_path: str,
    *,
    max_bytes: int,
    skill_name: str | None = None,
) -> str:
    path = resolve_under_root(skill_root, relative_path)
    if not path.exists():
        raise SkillResourceNotFoundError(
            message=f"resource not found: {relative_path}",
            skill_name=skill_name,
            path=relative_path,
        )
    if not path.is_file():
        raise SkillResourceForbiddenError(
            message=f"resource is not a regular file: {relative_path}",
            skill_name=skill_name,
            path=relative_path,
        )
    # Reject symlink that points outside (resolve already followed; check origin)
    if path.is_symlink():
        # If the final resolved path is under root we're ok; open without following
        # last component when possible.
        pass
    try:
        # Prefer open that does not follow final symlink when available
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            try:
                fd = os.open(path, flags | os.O_NOFOLLOW)
            except OSError:
                # May fail if intermediate ok but - use resolved path open
                fd = os.open(path, flags)
        else:
            fd = os.open(path, flags)
        try:
            data = os.read(fd, max_bytes + 1)
        finally:
            os.close(fd)
    except FileNotFoundError as exc:
        raise SkillResourceNotFoundError(
            message=f"resource not found: {relative_path}",
            skill_name=skill_name,
            path=relative_path,
        ) from exc
    except OSError as exc:
        raise SkillResourceForbiddenError(
            message=f"cannot read resource: {exc}",
            skill_name=skill_name,
            path=relative_path,
        ) from exc

    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
    if truncated:
        text += "\n\n[truncated: exceeded SKILL_READ_MAX_BYTES]"
    return text
