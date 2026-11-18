"""Drive ci:local's main() with nx faked, and read each check's files back through the real handoff."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gaia_verify  # the path insert above must precede this import

nx_affected = gaia_verify.nx_affected
NX_AFFECTED_PY = Path(nx_affected.__file__)
TASK = "ci:file-size"
CHANGED = "scripts/ci/checks.mjs"


def handed_files(task: str) -> str:
    """Read the files changes.sh scoped hands the check, through nx_affected.py --files-for."""
    return subprocess.run(
        [sys.executable, str(NX_AFFECTED_PY), "--files-for", task, "--base", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def run_ci_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *argv: str) -> dict[str, str]:
    """Run main() over a branch that changed one .mjs file; return what each check that ran was handed."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.chdir(tmp_path)
    check = nx_affected.Check(
        task=TASK,
        job="lint-node",
        check="file-size",
        area="node",
        events=None,
        branch=None,
        reuse=True,
        runner="nx",
    )
    reasons = [{"kind": "input-file", "file": CHANGED, "pattern": "{workspaceRoot}/**/*.mjs"}]
    monkeypatch.setattr(nx_affected, "checks", lambda: {TASK: check})
    monkeypatch.setattr(
        nx_affected, "select", lambda _range: nx_affected.Selection({TASK: reasons})
    )
    monkeypatch.setattr(gaia_verify, "changed_files", lambda _root, _base: [CHANGED])
    monkeypatch.setattr(gaia_verify, "_nx_parallel", lambda _root: 1)
    monkeypatch.setenv("GH_BASE", "origin/master")
    handed: dict[str, str] = {}

    def fake_run(
        tasks: list[str], _parallel: int, _wrap: nx_affected.Wrap, on_done: nx_affected.OnDone
    ) -> bool:
        for task in tasks:
            handed[task] = handed_files(task)
            on_done(task, {"status": "success", "code": 0, "output": ""})
        return True

    monkeypatch.setattr(nx_affected, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["gaia_verify.py", *argv])
    assert gaia_verify.main() == 0
    return handed


def test_only_hands_the_check_the_changed_files_it_reads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert run_ci_local(monkeypatch, tmp_path, "--only", "file-size") == {TASK: f"{CHANGED}\n"}


def test_all_hands_every_check_a_full_scan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert run_ci_local(monkeypatch, tmp_path, "--all") == {TASK: f"{nx_affected.FULL_SCAN}\n"}


def test_default_scope_hands_the_check_the_changed_files_it_reads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert run_ci_local(monkeypatch, tmp_path) == {TASK: f"{CHANGED}\n"}
