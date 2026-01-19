"""
Google Tasks tool output models.

Reference: node_modules/@composio/core/generated/googletasks.ts
"""

from pydantic import BaseModel, ConfigDict, Field


class GoogleTask(BaseModel):
    """Single Google Task - minimal fields for LLM summarization."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    title: str | None = None
    due: str | None = None
    status: str | None = None


class GoogleTasksListData(BaseModel):
    """Output data for GOOGLETASKS_LIST_ALL_TASKS tool."""

    model_config = ConfigDict(extra="ignore")

    items: list[GoogleTask] = Field(default_factory=list)
    tasks: list[GoogleTask] = Field(default_factory=list)

    def get_tasks(self) -> list[GoogleTask]:
        """Get tasks list, preferring items over tasks."""
        return self.items or self.tasks
