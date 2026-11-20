"""mise ci:local (scripts/dev/gaia_verify.py): the files each check is handed, and a checkout nx cannot run in."""

from __future__ import annotations

from collections.abc import Iterator
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

_SYS_PATH = list(sys.path)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gaia_verify  # the path insert above must precede this import

sys.path[:] = _SYS_PATH

REPO_ROOT = Path(__file__).resolve().parents[3]
nx_affected = gaia_verify.nx_affected
NX_AFFECTED_PY = Path(nx_affected.__file__)
TASK = "ci:file-size"
CHANGED = "apps/bots/src/report,format.mjs"


@pytest.fixture(autouse=True)
def restore_environ() -> Iterator[None]:
    """Restore os.environ after each test, which main() writes its handoff into directly."""
    before = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(before)


def handed_files(task: str) -> str:
    """Read the files changes.sh scoped hands the check, through nx_affected.py --files-for."""
    return subprocess.run(
        [sys.executable, str(NX_AFFECTED_PY), "--files-for", task, "--base", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def run_ci_local(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *argv: str,
    selects: list[str | None] | None = None,
) -> dict[str, str]:
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

    def fake_select(_range: list[str], stdin: str | None = None) -> nx_affected.Selection:
        if selects is not None:
            selects.append(stdin)
        return nx_affected.Selection({TASK: reasons})

    monkeypatch.setattr(nx_affected, "select", fake_select)
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


def test_a_filename_with_a_comma_reaches_nx_whole_on_stdin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selects: list[str | None] = []
    run_ci_local(monkeypatch, tmp_path, selects=selects)
    assert selects == [CHANGED]


def test_only_dry_run_never_asks_nx(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    selects: list[str | None] = []
    assert (
        run_ci_local(monkeypatch, tmp_path, "--only", "file-size", "--dry-run", selects=selects)
        == {}
    )
    assert selects == []


def test_the_checks_are_handed_the_base_ci_local_resolved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_ci_local(monkeypatch, tmp_path, "--all", "--base", "HEAD")
    assert os.environ["GAIA_PR_BASE"] == "HEAD"


def _checkout_without_node_modules(tmp_path: Path) -> Path:
    """Build a git checkout carrying ci:local and the nx lib it reads, and no node_modules."""
    root = tmp_path / "checkout"
    for rel in ("scripts/dev/gaia_verify.py", "scripts/ci/lib/nx_affected.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / rel, root / rel)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


def test_ci_local_without_node_modules_names_the_install_command(tmp_path: Path) -> None:
    """Regression: a fresh worktree got a CalledProcessError traceback from `nx graph`."""
    root = _checkout_without_node_modules(tmp_path)

    process = subprocess.run(
        [sys.executable, str(root / "scripts" / "dev" / "gaia_verify.py"), "--list"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert process.returncode == 2
    assert process.stderr.strip().splitlines() == [
        f"ci:local: node_modules is not installed in {root.resolve()}, so nx cannot run. "
        "Run: pnpm install --frozen-lockfile"
    ]
