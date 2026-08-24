"""Behaviour tests for tools/lints/check_ignore_staleness.py.

Inline noqas clean themselves up via RUF100; config exemptions have nobody.
The watchdog re-runs every concrete ``per-file-ignores`` entry's rule against
its file with only that entry stripped from a temp copy of the config, and
fails when the entry masks nothing anymore.

Runs the real script via subprocess against a throwaway repo, mirroring CI.
The checker resolves its own location to find the repo root (two parents up
from ``__file__``), so the fixture installs the script at the same relative
path it lives at here.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

_HERE = Path(__file__).resolve().parent
SCRIPT = _HERE / "check_ignore_staleness.py"
COMMON = _HERE / "_common.py"

PYPROJECT = """\
[tool.ruff.lint]
select = ["E", "F", "ARG"]

[tool.ruff.lint.per-file-ignores]
"app.py" = ["ARG001"]  # DI binds by name; unused params are contract
"""

# ``user_id`` is never read: ARG001 fires, so the entry above is load-bearing.
APP_WITH_VIOLATION = """\
def handler(user_id: str) -> str:
    return "ok"
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    lints_dir = tmp_path / "tools" / "lints"
    lints_dir.mkdir(parents=True)
    shutil.copy(SCRIPT, lints_dir / "check_ignore_staleness.py")
    shutil.copy(COMMON, lints_dir / "_common.py")
    (tmp_path / "pyproject.toml").write_text(PYPROJECT)
    (tmp_path / "app.py").write_text(APP_WITH_VIOLATION)
    return tmp_path


def run(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/lints/check_ignore_staleness.py"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_entry_masking_a_real_finding_passes(repo: Path) -> None:
    result = run(repo)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_entry_masking_nothing_fails_naming_the_file(repo: Path) -> None:
    """Delete the violating line, keep the entry: the exemption now masks
    nothing and must be reported by the file it sits in."""
    (repo / "app.py").write_text("def handler(user_id: str) -> str:\n    return user_id\n")
    result = run(repo)
    assert result.returncode == 1
    assert '"app.py"' in result.stderr
    assert "masks nothing anymore" in result.stderr
