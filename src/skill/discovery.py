"""Discover Skills under configured roots."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from common.logger import get_logger
from skill.errors import (
    SkillError,
    SkillInvalidFormatError,
    SkillMissingMetadataError,
)
from skill.fingerprint import compute_fingerprint
from skill.frontmatter import parse_skill_md
from skill.models import DiscoveryError, ListResult, SkillSummary

log = get_logger(__name__)


def discover_skills(
    roots: tuple[Path, ...] | list[Path],
    *,
    fingerprint_mode: str = "content",
) -> ListResult:
    """Scan one level of children under each root for SKILL.md."""
    candidates: list[tuple[str, SkillSummary]] = []
    errors: list[DiscoveryError] = []
    by_name: dict[str, list[SkillSummary]] = defaultdict(list)

    for root in roots:
        root = Path(root).expanduser()
        if not root.exists():
            errors.append(
                DiscoveryError(path=str(root), reason="skill root does not exist")
            )
            continue
        if not root.is_dir():
            errors.append(
                DiscoveryError(path=str(root), reason="skill root is not a directory")
            )
            continue

        try:
            children = sorted(root.iterdir(), key=lambda p: p.name)
        except OSError as exc:
            errors.append(
                DiscoveryError(path=str(root), reason=f"cannot list directory: {exc}")
            )
            continue

        for child in children:
            if not child.is_dir():
                continue
            skill_md = child / "SKILL.md"
            if not skill_md.is_file():
                continue
            try:
                text = skill_md.read_text(encoding="utf-8")
                meta, _body = parse_skill_md(
                    text, path=str(skill_md), skill_name_hint=child.name
                )
                fp = compute_fingerprint(child, mode=fingerprint_mode)
                summary = SkillSummary(
                    name=str(meta["name"]),
                    description=str(meta["description"]),
                    directory=child.resolve(),
                    fingerprint=fp,
                )
                by_name[summary.name].append(summary)
                candidates.append((summary.name, summary))
            except (SkillInvalidFormatError, SkillMissingMetadataError) as exc:
                errors.append(
                    DiscoveryError(
                        path=str(skill_md),
                        reason=exc.message,
                        skill_name=exc.skill_name,
                    )
                )
            except SkillError as exc:
                errors.append(
                    DiscoveryError(
                        path=str(skill_md),
                        reason=str(exc),
                        skill_name=exc.skill_name,
                    )
                )
            except OSError as exc:
                errors.append(
                    DiscoveryError(path=str(skill_md), reason=f"read failed: {exc}")
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    DiscoveryError(
                        path=str(skill_md),
                        reason=f"unexpected error: {exc}",
                    )
                )

    skills: list[SkillSummary] = []
    for name, summaries in sorted(by_name.items()):
        if len(summaries) > 1:
            paths = tuple(str(s.directory) for s in summaries)
            for s in summaries:
                errors.append(
                    DiscoveryError(
                        path=str(s.directory),
                        reason=(
                            f"name conflict for '{name}': "
                            f"all conflicting skills are excluded ({', '.join(paths)})"
                        ),
                        skill_name=name,
                    )
                )
            continue
        skills.append(summaries[0])

    log.info(
        "Skill discovery roots=%d skills=%d errors=%d",
        len(roots),
        len(skills),
        len(errors),
    )
    return ListResult(skills=tuple(skills), discovery_errors=tuple(errors))
