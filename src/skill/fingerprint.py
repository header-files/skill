"""Skill directory content fingerprinting."""

from __future__ import annotations

import hashlib
from pathlib import Path

_IGNORE_DIR_NAMES = {".git", "__pycache__", ".venv", "node_modules", ".DS_Store"}
_IGNORE_FILE_NAMES = {".DS_Store"}


def iter_skill_files(root: Path) -> list[Path]:
    """Return sorted regular files under root, applying ignore rules."""
    root = root.resolve()
    files: list[Path] = []
    if not root.is_dir():
        return files
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        parts = rel.parts
        if any(p in _IGNORE_DIR_NAMES for p in parts[:-1]):
            continue
        if path.name in _IGNORE_FILE_NAMES or path.name in _IGNORE_DIR_NAMES:
            continue
        files.append(path)
    return files


def compute_fingerprint(root: Path, *, mode: str = "content") -> str:
    """Compute stable fingerprint of all scanned files under skill root."""
    root = root.resolve()
    h = hashlib.sha256()
    h.update(f"mode={mode}\n".encode())
    for path in iter_skill_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            st = path.stat()
        except OSError:
            continue
        if mode == "meta":
            entry = f"{rel}\0{st.st_size}\0{getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9))}\n"
            h.update(entry.encode())
        else:
            # content mode: path + content hash (streamed)
            file_hash = hashlib.sha256()
            try:
                with path.open("rb") as fh:
                    while True:
                        chunk = fh.read(1024 * 64)
                        if not chunk:
                            break
                        file_hash.update(chunk)
            except OSError:
                continue
            h.update(f"{rel}\0{file_hash.hexdigest()}\n".encode())
    return h.hexdigest()
