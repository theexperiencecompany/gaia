"""`release.sh sync-uv-lock` re-locks the release PR branch after release-please bumps a version.

Runs the real script and the real uv against a local bare remote standing in for GitHub.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_SH = REPO_ROOT / "scripts" / "ci" / "release.sh"
BRANCH = "release-please--branches--master"

pytestmark = pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv on PATH")


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def _pyproject(version: str) -> str:
    return f'[project]\nname = "demo"\nversion = "{version}"\nrequires-python = ">=3.12"\n'


def _remote_with_release_branch(tmp_path: Path, *, locked: str, released: str) -> Path:
    """Build a bare remote whose release branch has pyproject at `released` and uv.lock at `locked`."""
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-q", "-b", BRANCH)
    _git(seed, "config", "user.email", "t@t")
    _git(seed, "config", "user.name", "t")
    (seed / "pyproject.toml").write_text(_pyproject(locked))
    subprocess.run(["uv", "lock", "--offline", "-q"], cwd=seed, check=True, env=_env())
    (seed / "pyproject.toml").write_text(_pyproject(released))
    _git(seed, "add", "-A")
    _git(seed, "commit", "-qm", "chore: release master")
    remote = tmp_path / "remote.git"
    _git(tmp_path, "clone", "-q", "--bare", str(seed), str(remote))
    return remote


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env["UV_OFFLINE"] = "1"
    return env


def _sync(tmp_path: Path, remote: Path, branch: str = BRANCH) -> subprocess.CompletedProcess[str]:
    work = tmp_path / "work"
    if not work.exists():
        work.mkdir()
        _git(work, "init", "-q")
        _git(work, "remote", "add", "origin", str(remote))
    return subprocess.run(
        ["bash", str(RELEASE_SH), "sync-uv-lock"],
        cwd=work,
        capture_output=True,
        text=True,
        check=False,
        env={**_env(), "RELEASE_BRANCH": branch},
    )


def _locked_version(remote: Path) -> str:
    lock = _git(remote, "show", f"{BRANCH}:uv.lock")
    block = lock.split('name = "demo"\n', 1)[1]
    return block.split('version = "', 1)[1].split('"', 1)[0]


def test_a_stale_lock_on_the_release_branch_is_relocked_and_pushed(tmp_path: Path) -> None:
    remote = _remote_with_release_branch(tmp_path, locked="0.1.0", released="0.2.0")

    proc = _sync(tmp_path, remote)

    assert proc.returncode == 0, proc.stderr
    assert _locked_version(remote) == "0.2.0"
    assert (
        _git(remote, "log", "-1", "--format=%s", BRANCH)
        == "chore: sync uv.lock with the release versions"
    )


def test_a_current_lock_pushes_nothing(tmp_path: Path) -> None:
    remote = _remote_with_release_branch(tmp_path, locked="0.2.0", released="0.2.0")
    before = _git(remote, "rev-parse", BRANCH)

    proc = _sync(tmp_path, remote)

    assert proc.returncode == 0, proc.stderr
    assert _git(remote, "rev-parse", BRANCH) == before


def test_no_release_branch_is_a_no_op(tmp_path: Path) -> None:
    remote = _remote_with_release_branch(tmp_path, locked="0.1.0", released="0.2.0")

    proc = _sync(tmp_path, remote, branch="release-please--branches--absent")

    assert proc.returncode == 0, proc.stderr
    assert _git(remote, "branch", "--list") == f"* {BRANCH}"
