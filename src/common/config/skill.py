"""Skill Runtime settings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from common.config.env import load_env
from common.config.errors import ConfigError
from common.config.parsing import parse_int
from common.logger import get_logger

log = get_logger(__name__)

_FINGERPRINT_MODES = {"content", "meta"}


@dataclass(frozen=True)
class SkillSettings:
    roots: tuple[Path, ...]
    fingerprint_mode: str = "content"
    script_timeout_seconds: float = 30.0
    script_max_concurrent: int = 4
    script_max_output_bytes: int = 1_048_576
    agent_max_steps: int = 20
    agent_timeout_seconds: float = 300.0
    read_max_bytes: int = 1_048_576
    chat_model_id: str | None = None


def load_skill_settings(
    env_path: str | Path | None = None,
    *,
    environ: dict[str, str] | None = None,
) -> SkillSettings:
    values = load_env(env_path, environ=environ, prefixes=("SKILL_",))

    roots_raw = _optional_str(values.get("SKILL_ROOTS"))
    if not roots_raw:
        roots: tuple[Path, ...] = ()
    else:
        roots = tuple(Path(p.strip()).expanduser() for p in roots_raw.split(":") if p.strip())

    mode = (_optional_str(values.get("SKILL_FINGERPRINT_MODE")) or "content").lower()
    if mode not in _FINGERPRINT_MODES:
        known = ", ".join(sorted(_FINGERPRINT_MODES))
        raise ConfigError(
            message=f"Unsupported SKILL_FINGERPRINT_MODE '{mode}'. Available: {known}"
        )

    settings = SkillSettings(
        roots=roots,
        fingerprint_mode=mode,
        script_timeout_seconds=_parse_float(
            values.get("SKILL_SCRIPT_TIMEOUT_SECONDS"),
            default=30.0,
            field="SKILL_SCRIPT_TIMEOUT_SECONDS",
            minimum=0.1,
        ),
        script_max_concurrent=parse_int(
            _as_str(values.get("SKILL_SCRIPT_MAX_CONCURRENT")),
            default=4,
            field="SKILL_SCRIPT_MAX_CONCURRENT",
            minimum=1,
        ),
        script_max_output_bytes=parse_int(
            _as_str(values.get("SKILL_SCRIPT_MAX_OUTPUT_BYTES")),
            default=1_048_576,
            field="SKILL_SCRIPT_MAX_OUTPUT_BYTES",
            minimum=1,
        ),
        agent_max_steps=parse_int(
            _as_str(values.get("SKILL_AGENT_MAX_STEPS")),
            default=20,
            field="SKILL_AGENT_MAX_STEPS",
            minimum=1,
        ),
        agent_timeout_seconds=_parse_float(
            values.get("SKILL_AGENT_TIMEOUT_SECONDS"),
            default=300.0,
            field="SKILL_AGENT_TIMEOUT_SECONDS",
            minimum=0.1,
        ),
        read_max_bytes=parse_int(
            _as_str(values.get("SKILL_READ_MAX_BYTES")),
            default=1_048_576,
            field="SKILL_READ_MAX_BYTES",
            minimum=1,
        ),
        chat_model_id=_optional_str(values.get("SKILL_CHAT_MODEL")),
    )
    log.info(
        "Loaded skill settings roots=%d fingerprint_mode=%s "
        "script_timeout=%.1fs script_max_concurrent=%d agent_max_steps=%d",
        len(settings.roots),
        settings.fingerprint_mode,
        settings.script_timeout_seconds,
        settings.script_max_concurrent,
        settings.agent_max_steps,
    )
    return settings


def _parse_float(
    raw: str | None,
    *,
    default: float,
    field: str,
    minimum: float | None = None,
) -> float:
    if raw is None or str(raw).strip() == "":
        value = default
    else:
        try:
            value = float(str(raw).strip())
        except ValueError as exc:
            raise ConfigError(message=f"Invalid number for {field}: {raw}") from exc
    if minimum is not None and value < minimum:
        raise ConfigError(message=f"{field} must be >= {minimum}, got {value}")
    return value


def _as_str(value: str | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
