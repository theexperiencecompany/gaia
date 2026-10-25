"""Replays the merge queue against a real throwaway git repo."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pr_conflicts  # the path insert above must precede this import


def run(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def branch(repo: Path, name: str, files: dict[str, str]) -> str:
    run(repo, "checkout", "-q", "-b", name, "master")
    for path, text in files.items():
        (repo / path).write_text(text)
    run(repo, "commit", "-qam", name)
    return run(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    run(tmp_path, "init", "-q", "-b", "master")
    run(tmp_path, "config", "user.email", "t@t")
    run(tmp_path, "config", "user.name", "t")
    (tmp_path / "tests.py").write_text("a\nb\n")
    (tmp_path / "other.py").write_text("x\n")
    run(tmp_path, "add", ".")
    run(tmp_path, "commit", "-qm", "base")
    return tmp_path


def test_two_prs_appending_to_the_same_file_end_conflict_once_one_lands(repo: Path) -> None:
    first = branch(repo, "first", {"tests.py": "a\nb\nfirst\n"})
    second = branch(repo, "second", {"tests.py": "a\nb\nsecond\n"})
    assert pr_conflicts.merge_onto("master", first, str(repo)).conflicts == ()
    assert pr_conflicts.merge_onto("master", second, str(repo)).conflicts == ()
    assert pr_conflicts.queue_conflicts("master", first, second, str(repo)) == ("tests.py",)


def test_prs_touching_different_files_replay_cleanly(repo: Path) -> None:
    first = branch(repo, "first", {"tests.py": "a\nb\nfirst\n"})
    second = branch(repo, "second", {"other.py": "y\n"})
    assert pr_conflicts.queue_conflicts("master", first, second, str(repo)) == ()


def test_a_pr_that_conflicts_with_master_reports_its_files(repo: Path) -> None:
    pr = branch(repo, "pr", {"other.py": "pr\n"})
    run(repo, "checkout", "-q", "master")
    (repo / "other.py").write_text("master moved\n")
    run(repo, "commit", "-qam", "master moved")
    merge = pr_conflicts.merge_onto("master", pr, str(repo))
    assert merge.commit is None
    assert merge.conflicts == ("other.py",)
