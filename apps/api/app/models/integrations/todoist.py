"""Todoist task payloads the context tool reads and forwards.

Reference: https://developer.todoist.com/rest/v2/#tasks (due is a Due
object or null; due.date is a string).
"""

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class TodoistDue(BaseModel):
    """The ``due`` object of a task."""

    model_config = ConfigDict(extra="allow")

    date: str | None = None


class TodoistTask(BaseModel):
    """A task. Forwarded verbatim into the tool output — passthrough."""

    model_config = ConfigDict(extra="allow")

    due: TodoistDue | None = None


class TodoistTaskList(BaseModel):
    """``TODOIST_GET_ALL_TASKS`` data — Composio answers with the tasks under
    ``items``, ``tasks``, or as a bare list; any other shape is no tasks."""

    model_config = ConfigDict(extra="ignore")

    items: list[TodoistTask] | None = None
    tasks: list[TodoistTask] | None = None

    @model_validator(mode="before")
    @classmethod
    def _wrap_bare_list(cls, data: object) -> object:
        if isinstance(data, list):
            return {"items": data}
        return data if isinstance(data, dict) else {}

    @field_validator("items", "tasks", mode="before")
    @classmethod
    def _list_or_nothing(cls, value: object) -> object:
        return value if isinstance(value, list) else []

    @property
    def all(self) -> list[TodoistTask]:
        if self.items is not None:
            return self.items
        return self.tasks or []
