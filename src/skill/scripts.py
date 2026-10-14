"""Async sandboxed script runner for Skills."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from dataclasses import dataclass, field
from pathlib import Path

from common.logger import get_logger
from skill.errors import SkillScriptError
from skill.resources import resolve_under_root

log = get_logger(__name__)

_ENV_ALLOWLIST = {
    "PATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "HOME",
    "TMPDIR",
    "TMP",
    "TEMP",
    "TERM",
    "USER",
    "LOGNAME",
}


@dataclass
class ScriptResult:
    stdout: str
    stderr: str
    exit_code: int
    truncated: bool = False


@dataclass
class OutputBudget:
    max_bytes: int
    stdout: bytearray = field(default_factory=bytearray)
    stderr: bytearray = field(default_factory=bytearray)
    remaining: int = 0
    truncated: bool = False
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        self.remaining = self.max_bytes

    async def claim_and_append(self, stream: str, chunk: bytes) -> bool:
        """Append up to remaining budget. Returns True if over limit triggered."""
        async with self._lock:
            if self.remaining <= 0:
                self.truncated = True
                return True
            take = min(len(chunk), self.remaining)
            buf = self.stdout if stream == "stdout" else self.stderr
            buf.extend(chunk[:take])
            self.remaining -= take
            if take < len(chunk):
                self.truncated = True
                return True
            return False


class ScriptRunner:
    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_concurrent: int,
        max_output_bytes: int,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._current_pgid: int | None = None
        self._pgid_lock = asyncio.Lock()

    async def kill_current(self) -> None:
        async with self._pgid_lock:
            pgid = self._current_pgid
        if pgid is not None:
            await asyncio.to_thread(_kill_process_group, pgid)

    async def run(
        self,
        skill_root: Path,
        relative_path: str,
        args: list[str] | None = None,
        *,
        skill_name: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> ScriptResult:
        path = resolve_under_root(skill_root, relative_path)
        if not path.is_file():
            raise SkillScriptError(
                message=f"script not found: {relative_path}",
                skill_name=skill_name,
                script_path=relative_path,
            )
        cmd = _build_command(path)
        if args:
            if not all(isinstance(a, str) for a in args):
                raise SkillScriptError(
                    message="script args must be a list of strings",
                    skill_name=skill_name,
                    script_path=relative_path,
                )
            cmd.extend(args)

        env = _filtered_env(extra_env)
        await self._semaphore.acquire()
        proc: asyncio.subprocess.Process | None = None
        budget = OutputBudget(max_bytes=self.max_output_bytes)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(skill_root.resolve()),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            assert proc.pid is not None
            async with self._pgid_lock:
                self._current_pgid = proc.pid

            async def _pump(stream_name: str, reader: asyncio.StreamReader) -> None:
                while True:
                    chunk = await reader.read(64 * 1024)
                    if not chunk:
                        break
                    over = await budget.claim_and_append(stream_name, chunk)
                    if over:
                        await self.kill_current()
                        # drain remainder without buffering
                        while await reader.read(64 * 1024):
                            pass
                        break

            assert proc.stdout and proc.stderr
            pump_out = asyncio.create_task(_pump("stdout", proc.stdout))
            pump_err = asyncio.create_task(_pump("stderr", proc.stderr))
            try:
                await asyncio.wait_for(
                    proc.wait(),
                    timeout=self.timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                await self.kill_current()
                await asyncio.gather(pump_out, pump_err, return_exceptions=True)
                raise SkillScriptError(
                    message=(
                        f"script timed out after {self.timeout_seconds}s: "
                        f"{relative_path}"
                    ),
                    skill_name=skill_name,
                    script_path=relative_path,
                ) from exc

            await asyncio.gather(pump_out, pump_err)
            code = proc.returncode if proc.returncode is not None else -1
            stdout = bytes(budget.stdout).decode("utf-8", errors="replace")
            stderr = bytes(budget.stderr).decode("utf-8", errors="replace")
            if budget.truncated:
                raise SkillScriptError(
                    message=(
                        f"script output exceeded {self.max_output_bytes} bytes: "
                        f"{relative_path}"
                    ),
                    skill_name=skill_name,
                    script_path=relative_path,
                    exit_code=code,
                )
            if code != 0:
                raise SkillScriptError(
                    message=(
                        f"script exited with code {code}: {relative_path}"
                        + (f"\nstderr: {stderr}" if stderr else "")
                    ),
                    skill_name=skill_name,
                    script_path=relative_path,
                    exit_code=code,
                )
            log.info(
                "script ok skill=%s path=%s exit=%d",
                skill_name or "-",
                relative_path,
                code,
            )
            return ScriptResult(
                stdout=stdout, stderr=stderr, exit_code=code, truncated=False
            )
        finally:
            async with self._pgid_lock:
                self._current_pgid = None
            self._semaphore.release()


def _build_command(script_path: Path) -> list[str]:
    suffix = script_path.suffix.lower()
    if suffix == ".py":
        return [sys.executable, str(script_path)]
    if suffix == ".sh":
        return ["/bin/bash", str(script_path)]
    raise SkillScriptError(
        message=f"unsupported script type: {suffix or '(none)'}",
        script_path=script_path.name,
    )


def _filtered_env(extra: dict[str, str] | None) -> dict[str, str]:
    env: dict[str, str] = {}
    for key in _ENV_ALLOWLIST:
        if key in os.environ:
            env[key] = os.environ[key]
    if extra:
        for k, v in extra.items():
            env[str(k)] = str(v)
    return env


def _kill_process_group(pgid: int) -> None:
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        return
    try:
        # brief grace then SIGKILL
        import time

        time.sleep(0.2)
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except PermissionError:
        return
