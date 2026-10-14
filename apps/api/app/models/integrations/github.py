"""GitHub REST payloads the context tool reads and forwards.

Reference: https://docs.github.com/en/rest/issues/issues (pull_request is
present only on pull requests, never null) and
https://docs.github.com/en/rest/activity/notifications.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GitHubPullRequestRef(BaseModel):
    """The ``pull_request`` key that marks an issue as a pull request."""

    model_config = ConfigDict(extra="allow")


class GitHubIssue(BaseModel):
    """An issue or pull request. Forwarded verbatim into the tool output — passthrough;
    only the key that decides the bucket is declared."""

    model_config = ConfigDict(extra="allow")

    pull_request: GitHubPullRequestRef | None = None


class GitHubIssueList(BaseModel):
    """Issue-list / search data — Composio answers under ``issues`` or ``items``."""

    model_config = ConfigDict(extra="ignore")

    issues: list[GitHubIssue] | None = None
    items: list[GitHubIssue] | None = None

    @property
    def all(self) -> list[GitHubIssue]:
        if self.issues is not None:
            return self.issues
        return self.items or []


class GitHubNotification(BaseModel):
    """A notification thread — nothing is read, it is forwarded verbatim (passthrough)."""

    model_config = ConfigDict(extra="allow")


class GitHubNotificationList(BaseModel):
    """``GITHUB_LIST_NOTIFICATIONS`` data — a bare list, or ``{notifications: [...]}``.

    Anything else (a non-list ``notifications`` value) counts as no notifications.
    """

    model_config = ConfigDict(extra="ignore")

    notifications: list[GitHubNotification] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _wrap_bare_list(cls, data: object) -> object:
        return {"notifications": data} if isinstance(data, list) else data

    @field_validator("notifications", mode="before")
    @classmethod
    def _list_or_nothing(cls, value: object) -> object:
        return value if isinstance(value, list) else []
