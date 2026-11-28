"""The todo_progress card's payload: the plan an agent keeps with plan_tasks and update_tasks, per source agent."""

from typing import Literal

from pydantic import Field

from app.schemas.common import ResponseModel

TodoProgressStatus = Literal["pending", "in_progress", "completed", "cancelled"]


class TodoProgressItem(ResponseModel):
    """One step of an agent's plan."""

    id: str
    content: str
    status: TodoProgressStatus


class TodoProgressSnapshot(ResponseModel):
    """One source agent's plan as it last changed; integration_name is absent when the source has no display name."""

    todos: list[TodoProgressItem]
    source: str
    integration_name: str | None = Field(default=None, exclude_if=lambda name: name is None)


#: The todo_progress card's data: each source agent's newest plan, keyed by its source.
TodoProgressCardData = dict[str, TodoProgressSnapshot]
