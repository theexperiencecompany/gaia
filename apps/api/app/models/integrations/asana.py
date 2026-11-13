"""Asana task payloads the context tool reads and forwards.

Reference: https://developers.asana.com/reference/searchtasksforworkspace
(gid and name are strings; due_on is an ISO date string or null).
"""

from pydantic import BaseModel, ConfigDict


class AsanaTask(BaseModel):
    """A compact task. Forwarded verbatim into the tool output — passthrough."""

    model_config = ConfigDict(extra="allow")

    due_on: str | None = None


class AsanaTaskSearch(BaseModel):
    """``ASANA_SEARCH_TASKS_IN_WORKSPACE`` data — ``data`` per Asana, or Composio's ``tasks``."""

    model_config = ConfigDict(extra="ignore")

    data: list[AsanaTask] | None = None
    tasks: list[AsanaTask] | None = None

    @property
    def all(self) -> list[AsanaTask]:
        if self.data is not None:
            return self.data
        return self.tasks or []
