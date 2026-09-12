"""Behaviour tests for tools/lints/check_plr_complexity.py.

The ratchet grandfathers a (file, rule) only while the file is untouched by
the PR. A baseline line may carry a third field,
``deferred-until=YYYY-MM-DD; <reason>``, which keeps a touched file's known
violation from failing until that date -- announced as a workflow warning so
the debt stays visible -- and fails once the date has passed.

Runs the real script via subprocess against a throwaway repo, mirroring CI.
The checker resolves the repo root from its own location (two parents up from
``__file__``) and asks ``scripts/ci/changes.sh files py`` which files the PR
touched, so the fixture installs the script at the same relative path and
stubs the changes script to name ``app.py``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

_HERE = Path(__file__).resolve().parent
SCRIPT = _HERE / "check_plr_complexity.py"
COMMON = _HERE / "_common.py"

# Six parameters: PLR0913 (max-args defaults to 5) fires on line 1.
APP_WITH_VIOLATION = """\
def handler(a: int, b: int, c: int, d: int, e: int, f: int) -> int:
    return a + b + c + d + e + f
"""

REASON = "proxy wrap touched the file mechanically; restructuring is its own PR"


def _baseline(deferred_until: date | None) -> str:
    line = "app.py\tPLR0913"
    if deferred_until is not None:
        line += f"\tdeferred-until={deferred_until.isoformat()}; {REASON}"
    return f"# header\n{line}\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    lints_dir = tmp_path / "tools" / "lints"
    lints_dir.mkdir(parents=True)
    shutil.copy(SCRIPT, lints_dir / "check_plr_complexity.py")
    shutil.copy(COMMON, lints_dir / "_common.py")
    ci_dir = tmp_path / "scripts" / "ci"
    ci_dir.mkdir(parents=True)
    changes = ci_dir / "changes.sh"
    changes.write_text("#!/bin/sh\nprintf 'app.py\\n'\n")
    changes.chmod(0o755)
    (tmp_path / "app.py").write_text(APP_WITH_VIOLATION)
    return tmp_path


def run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/lints/check_plr_complexity.py", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_touched_without_deferral_fails(repo: Path) -> None:
    (repo / "tools/lints/plr_complexity_baseline.txt").write_text(_baseline(None))
    result = run(repo)
    assert result.returncode == 1
    assert "touched, grandfathered" in result.stderr


def test_touched_with_future_deferral_passes_with_warning(repo: Path) -> None:
    until = datetime.now(tz=UTC).date() + timedelta(days=30)
    (repo / "tools/lints/plr_complexity_baseline.txt").write_text(_baseline(until))
    result = run(repo)
    assert result.returncode == 0, result.stderr
    warning = f"::warning file=app.py,line=1::PLR0913 deferred until {until.isoformat()}"
    assert warning in result.stdout
    assert REASON in result.stdout


def test_touched_with_expired_deferral_fails(repo: Path) -> None:
    until = datetime.now(tz=UTC).date() - timedelta(days=1)
    (repo / "tools/lints/plr_complexity_baseline.txt").write_text(_baseline(until))
    result = run(repo)
    assert result.returncode == 1
    assert "deferral expired" in result.stderr
    assert "fix or renew with a reason" in result.stderr


def test_update_round_trips_the_deferral_field(repo: Path) -> None:
    until = datetime.now(tz=UTC).date() + timedelta(days=30)
    baseline = repo / "tools/lints/plr_complexity_baseline.txt"
    baseline.write_text(_baseline(until))
    result = run(repo, "--update")
    assert result.returncode == 0, result.stderr
    assert (
        f"app.py\tPLR0913\tdeferred-until={until.isoformat()}; {REASON}\n" in baseline.read_text()
    )
