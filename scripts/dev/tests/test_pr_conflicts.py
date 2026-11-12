"""Replays the merge queue against a real throwaway git repo, and lists PRs through the GitHub fake."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ci" / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ci"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from github_fake import FakeGitHub, Reply, serve
from lib.github import GitHub
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


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeGitHub]:
    with serve() as fake:
        fake.point_client(monkeypatch)
        monkeypatch.setattr(pr_conflicts, "parse_repo", lambda: ("o", "r"))
        yield fake


def search_reply(*numbers: int, count: int | None = None) -> Reply:
    nodes = [{"number": n} for n in numbers]
    issue_count = len(numbers) if count is None else count
    return Reply(body={"data": {"search": {"issueCount": issue_count, "nodes": nodes}}})


def test_the_default_is_every_open_non_draft_pr_of_yours_in_this_repo(api: FakeGitHub) -> None:
    """Regression: `gh pr list` stopped at 30 PRs drafts included, so 21 of 30 non-drafts went unchecked."""
    numbers = list(range(100, 131))
    api.on("POST", "/graphql", search_reply(*reversed(numbers)))
    assert pr_conflicts.default_prs(GitHub.from_env(), "o", "r") == numbers
    [search] = api.requests
    assert isinstance(search.body, dict)
    assert search.body["variables"] == {"q": "repo:o/r is:pr is:open draft:false author:@me"}


def test_more_prs_than_one_search_page_holds_is_refused_not_truncated(
    api: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    api.on("POST", "/graphql", search_reply(1, 2, count=pr_conflicts.SEARCH_LIMIT + 1))
    with pytest.raises(SystemExit) as exited:
        pr_conflicts.main([])
    assert exited.value.code == 2
    assert "pass the numbers" in capsys.readouterr().err


def test_no_open_prs_is_nothing_to_check(
    api: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    api.on("POST", "/graphql", search_reply())
    assert pr_conflicts.main([]) == 0
    assert capsys.readouterr().out == "no open PRs to check\n"


def test_a_github_failure_listing_prs_exits_two(
    api: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    api.on("POST", "/graphql", Reply(401, {"message": "Bad credentials"}))
    assert pr_conflicts.main([]) == 2
    assert "listing your open PRs failed" in capsys.readouterr().err
