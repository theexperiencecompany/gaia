"""
GitHub trigger payload models.

Reference: node_modules/@composio/core/generated/github.ts
"""

from pydantic import BaseModel, Field


class GitHubCommitEventPayload(BaseModel):
    """Payload for GITHUB_COMMIT_EVENT trigger."""

    author: str | None = Field(None, description="GitHub username of the commit author")
    id: str | None = Field(None, description="SHA of the commit")
    message: str | None = Field(None, description="Commit message")
    timestamp: str | None = Field(None, description="Timestamp of the commit")
    url: str | None = Field(None, description="GitHub URL of the commit")


class GitHubPullRequestEventPayload(BaseModel):
    """Payload for GITHUB_PULL_REQUEST_EVENT trigger."""

    action: str | None = Field(None, description="Action performed on the PR")
    createdAt: str | None = Field(None, description="When the PR was created")
    createdBy: str | None = Field(None, description="Username who created the PR")
    description: str = Field("", description="PR description")
    number: int | None = Field(None, description="PR number")
    title: str | None = Field(None, description="PR title")
    url: str | None = Field(None, description="GitHub URL of the PR")


class GitHubStarAddedEventPayload(BaseModel):
    """Payload for GITHUB_STAR_ADDED_EVENT trigger."""

    action: str | None = Field(None, description="Action (starred)")
    starred_at: str | None = Field(None, description="When the star was added")
    user: str | None = Field(None, description="Username who starred")


class GitHubIssueAddedEventPayload(BaseModel):
    """Payload for GITHUB_ISSUE_ADDED_EVENT trigger."""

    action: str | None = Field(None, description="Action performed on the issue")
    createdAt: str | None = Field(None, description="When the issue was created")
    createdBy: str | None = Field(None, description="Username who created the issue")
    description: str = Field("", description="Issue description")
    issue_id: int | None = Field(None, description="Unique issue ID")
    number: int | None = Field(None, description="Issue number")
    title: str | None = Field(None, description="Issue title")
    url: str | None = Field(None, description="GitHub URL of the issue")
