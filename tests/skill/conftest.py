from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "skills"


@pytest.fixture
def skills_root(tmp_path: Path) -> Path:
    """Copy fixture skills into an isolated temp root."""
    import shutil

    root = tmp_path / "skills"
    shutil.copytree(FIXTURES, root)
    return root
