"""Google Tasks payloads the context tool reads and forwards.

Reference: https://developers.google.com/workspace/tasks/reference/rest/v1/tasks
(due is an RFC 3339 timestamp, absent when the task has no due date).
"""

from pydantic import BaseModel, ConfigDict


class GoogleTask(BaseModel):
    """A task. Forwarded verbatim into the tool output — passthrough."""

    model_config = ConfigDict(extra="allow")

    due: str | None = None


class GoogleTaskList(BaseModel):
    """``GOOGLETASKS_LIST_ALL_TASKS`` data — ``items`` per Google, or Composio's ``tasks``."""

    model_config = ConfigDict(extra="ignore")

    items: list[GoogleTask] | None = None
    tasks: list[GoogleTask] | None = None

    @property
    def all(self) -> list[GoogleTask]:
        if self.items is not None:
            return self.items
        return self.tasks or []
