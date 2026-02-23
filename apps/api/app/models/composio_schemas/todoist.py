"""
Todoist tool output models.

Reference: node_modules/@composio/core/generated/todoist.ts
"""

from pydantic import BaseModel, ConfigDict, Field


class TodoistDue(BaseModel):
    """Todoist due date info - minimal for summarization."""

    model_config = ConfigDict(extra="ignore")

    date: str | None = None


class TodoistTask(BaseModel):
    """Single Todoist task - minimal fields for LLM summarization."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    content: str | None = None
    due: TodoistDue | None = None
    priority: int = 1


class TodoistListData(BaseModel):
    """Output data for TODOIST_GET_ALL_TASKS tool."""

    model_config = ConfigDict(extra="ignore")

    items: list[TodoistTask] = Field(default_factory=list)
    tasks: list[TodoistTask] = Field(default_factory=list)

    def get_tasks(self) -> list[TodoistTask]:
        """Get tasks list."""
        return self.items or self.tasks
