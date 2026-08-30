"""changes.sh: the diff every lane scopes itself to.

Driven against a real throwaway git repo — the script's whole job is git
plumbing, so stubbing git would test the stub.

Each test names a way the answer could be wrong in the direction that costs a
green PR on a broken tree:

* `files` must print `__FULL__` and nothing else on a push, or every scoped
  lane reports "no changed files — skipping" on the one branch that needs
  scanning;
* `docker-inputs` must notice `apps/api/Dockerfile.dockerignore`. It decides
  what enters the build CONTEXT, so a newly-excluded path drops out of the
  image — while the lane said "image inputs unchanged" and skipped the build.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

CI = Path(__file__).resolve().parent.parent
SCRIPT = CI / "changes.sh"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
    "HOME": "/tmp",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=GIT_ENV, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo with a `master` commit and a branch on top of it."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "master")
    for rel in ("apps/api/Dockerfile", "apps/api/Dockerfile.dockerignore", ".dockerignore"):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("base\n")
    (root / "app.py").write_text("x = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    # A real `origin`: `docker-inputs` fetches it before diffing, so a repo with
    # only a remote-tracking ref would fail on the fetch rather than exercise
    # the diff.
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "master", str(origin)],
        check=True,
        env=GIT_ENV,
        capture_output=True,
    )
    _git(root, "remote", "add", "origin", str(origin))
    _git(root, "push", "-q", "origin", "master")
    _git(root, "checkout", "-qb", "feature")
    return root


def _docker_inputs(repo: Path, tmp_path: Path) -> str:
    out = tmp_path / "gh_output"
    out.write_text("")
    proc = subprocess.run(
        ["bash", str(SCRIPT), "docker-inputs"],
        cwd=repo,
        env={**GIT_ENV, "BASE_BRANCH": "master", "GITHUB_OUTPUT": str(out)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return out.read_text()


def test_a_dockerignore_change_rebuilds_the_image(repo: Path, tmp_path: Path) -> None:
    (repo / "apps/api/Dockerfile.dockerignore").write_text("base\n**/tests\n")
    _git(repo, "commit", "-aqm", "narrow the build context")
    assert "build=true" in _docker_inputs(repo, tmp_path)


def test_the_root_dockerignore_still_rebuilds_the_image(repo: Path, tmp_path: Path) -> None:
    (repo / ".dockerignore").write_text("base\nnode_modules\n")
    _git(repo, "commit", "-aqm", "root ignore")
    assert "build=true" in _docker_inputs(repo, tmp_path)


def test_an_unrelated_change_skips_the_build(repo: Path, tmp_path: Path) -> None:
    # The control: without this the test above would pass on a script that
    # answered build=true unconditionally.
    (repo / "app.py").write_text("x = 2\n")
    _git(repo, "commit", "-aqm", "unrelated")
    assert "build=false" in _docker_inputs(repo, tmp_path)


def test_files_prints_only_the_full_sentinel_on_a_push(repo: Path) -> None:
    proc = subprocess.run(
        ["bash", str(SCRIPT), "files", "py"],
        cwd=repo,
        env={**GIT_ENV, "GITHUB_ACTIONS": "true", "GITHUB_BASE_REF": ""},
        capture_output=True,
        text=True,
        check=True,
    )
    # Byte-for-byte: callers compare with `[ "$FILES" = "__FULL__" ]`.
    assert proc.stdout == "__FULL__\n"


def test_files_requires_an_extension(repo: Path) -> None:
    proc = subprocess.run(
        ["bash", str(SCRIPT), "files"],
        cwd=repo,
        env=GIT_ENV,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2


def test_an_unknown_subcommand_exits_two(repo: Path) -> None:
    proc = subprocess.run(
        ["bash", str(SCRIPT), "nope"],
        cwd=repo,
        env=GIT_ENV,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
