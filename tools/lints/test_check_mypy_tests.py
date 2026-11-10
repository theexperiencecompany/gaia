"""Behaviour tests for tools/lints/check_mypy_tests.py.

Runs the real script in a throwaway repo. A stub uv on PATH replays canned mypy
JSON output, and a stub changes.sh names the files the PR touched.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

_HERE = Path(__file__).resolve().parent
SCRIPT = _HERE / "check_mypy_tests.py"
COMMON = _HERE / "_common.py"
RATCHET = _HERE / "_ratchet.py"

OLD = "apps/api/tests/unit/test_old.py"
OTHER = "apps/api/tests/unit/test_other.py"
BASELINE = "tools/lints/mypy_tests_baseline.txt"


def _error(file: str, code: str, line: int = 3) -> dict[str, object]:
    return {
        "file": file,
        "line": line,
        "column": 4,
        "message": "boom",
        "hint": None,
        "code": code,
        "severity": "error",
    }


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    lints_dir = tmp_path / "tools" / "lints"
    lints_dir.mkdir(parents=True)
    for source in (SCRIPT, COMMON, RATCHET):
        shutil.copy(source, lints_dir / source.name)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(f'#!/bin/sh\ncat "{tmp_path}/mypy.out"\nexit "$(cat "{tmp_path}/mypy.rc")"\n')
    uv.chmod(0o755)
    ci_dir = tmp_path / "scripts" / "ci"
    ci_dir.mkdir(parents=True)
    changes = ci_dir / "changes.sh"
    changes.write_text(f'#!/bin/sh\ncat "{tmp_path}/touched"\n')
    changes.chmod(0o755)
    (tmp_path / "touched").write_text("")
    (tmp_path / BASELINE).write_text(f"# header\n{OLD}\targ-type\n")
    return tmp_path


def _mypy_reports(repo: Path, *errors: dict[str, object]) -> None:
    (repo / "mypy.out").write_text("".join(json.dumps(e) + "\n" for e in errors))
    (repo / "mypy.rc").write_text("1" if errors else "0")


def run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/lints/check_mypy_tests.py", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": f"{repo / 'bin'}{os.pathsep}{os.environ['PATH']}"},
    )


def test_new_error_fails(repo: Path) -> None:
    _mypy_reports(repo, _error(OLD, "arg-type"), _error(OTHER, "attr-defined", line=7))
    result = run(repo)
    assert result.returncode == 1
    assert f"{OTHER}:7" in result.stderr
    assert "attr-defined (new)" in result.stderr


def test_new_error_code_in_grandfathered_file_fails(repo: Path) -> None:
    _mypy_reports(repo, _error(OLD, "arg-type"), _error(OLD, "union-attr"))
    result = run(repo)
    assert result.returncode == 1
    assert "union-attr (new)" in result.stderr


def test_untouched_grandfathered_error_passes(repo: Path) -> None:
    _mypy_reports(repo, _error(OLD, "arg-type"))
    (repo / "touched").write_text(f"{OTHER}\n")
    result = run(repo)
    assert result.returncode == 0, result.stderr
    assert "all grandfathered and untouched" in result.stdout


def test_touched_grandfathered_error_fails(repo: Path) -> None:
    _mypy_reports(repo, _error(OLD, "arg-type"))
    (repo / "touched").write_text(f"{OLD}\n")
    result = run(repo)
    assert result.returncode == 1
    assert "arg-type (touched, grandfathered)" in result.stderr


def test_notes_are_not_errors(repo: Path) -> None:
    note = {**_error(OTHER, "misc"), "severity": "note"}
    _mypy_reports(repo, _error(OLD, "arg-type"), note)
    assert run(repo).returncode == 0


def test_update_shrinks_the_baseline(repo: Path) -> None:
    (repo / BASELINE).write_text(f"# header\n{OLD}\targ-type\n{OTHER}\tattr-defined\n")
    _mypy_reports(repo, _error(OLD, "arg-type"))
    result = run(repo, "--update")
    assert result.returncode == 0, result.stderr
    entries = [
        line for line in (repo / BASELINE).read_text().splitlines() if not line.startswith("#")
    ]
    assert entries == [f"{OLD}\targ-type"]


def test_mypy_crash_fails_loud(repo: Path) -> None:
    (repo / "mypy.out").write_text("")
    (repo / "mypy.rc").write_text("2")
    result = run(repo)
    assert result.returncode == 1
    assert "mypy failed unexpectedly (exit 2)" in result.stderr
