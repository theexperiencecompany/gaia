"""Unit tests for app/models/composio_schemas/github.py."""

from pydantic import ValidationError
import pytest

from app.models.composio_schemas.github import (
    GitHubCommitEventPayload,
    GitHubIssueAddedEventPayload,
    GitHubPullRequestEventPayload,
    GitHubStarAddedEventPayload,
)


class TestGitHubCommitEventPayload:
    def test_valid_minimal(self):
        m = GitHubCommitEventPayload()
        assert m.author is None
        assert m.id is None

    def test_valid_full(self):
        m = GitHubCommitEventPayload(
            author="octocat",
            id="abc123",
            message="fix: stuff",
            timestamp="2025-01-01T00:00:00Z",
            url="https://github.com/org/repo/commit/abc123",
        )
        assert m.author == "octocat"
        assert m.id == "abc123"
        assert m.url == "https://github.com/org/repo/commit/abc123"

    def test_wrong_type_author(self):
        with pytest.raises(ValidationError):
            GitHubCommitEventPayload(author=123)


class TestGitHubPullRequestEventPayload:
    def test_valid_minimal(self):
        m = GitHubPullRequestEventPayload()
        assert m.description == ""
        assert m.number is None

    def test_valid_full(self):
        m = GitHubPullRequestEventPayload(
            action="opened",
            createdAt="2025-01-01T00:00:00Z",
            createdBy="octocat",
            description="Adds docs",
            number=42,
            title="Docs",
            url="https://github.com/org/repo/pull/42",
        )
        assert m.action == "opened"
        assert m.number == 42
        assert m.title == "Docs"

    def test_custom_description(self):
        m = GitHubPullRequestEventPayload(description="hello")
        assert m.description == "hello"

    def test_wrong_type_number(self):
        with pytest.raises(ValidationError):
            GitHubPullRequestEventPayload(number="not-a-number")


class TestGitHubStarAddedEventPayload:
    def test_valid_minimal(self):
        m = GitHubStarAddedEventPayload()
        assert m.action is None
        assert m.starred_by is None

    def test_valid_full(self):
        # Field set verified against Composio triggers_types API (2026-08).
        m = GitHubStarAddedEventPayload(
            action="starred",
            repository_id=186853002,
            repository_name="org/repo",
            repository_url="https://github.com/org/repo",
            starred_at="2025-01-01T00:00:00Z",
            starred_by="octocat",
        )
        assert m.starred_at == "2025-01-01T00:00:00Z"
        assert m.starred_by == "octocat"
        assert m.repository_name == "org/repo"
        assert m.repository_id == 186853002


class TestGitHubIssueAddedEventPayload:
    def test_valid_minimal(self):
        m = GitHubIssueAddedEventPayload()
        assert m.description == ""
        assert m.issue_id is None

    def test_valid_full(self):
        m = GitHubIssueAddedEventPayload(
            action="opened",
            createdAt="2025-01-01T00:00:00Z",
            createdBy="octocat",
            description="Bug report",
            issue_id=7,
            number=7,
            title="Bug",
            url="https://github.com/org/repo/issues/7",
        )
        assert m.issue_id == 7
        assert m.number == 7
        assert m.title == "Bug"

    def test_wrong_type_issue_id(self):
        with pytest.raises(ValidationError):
            GitHubIssueAddedEventPayload(issue_id="not-a-number")


# ---------------------------------------------------------------------------
# google_calendar
# ---------------------------------------------------------------------------
