"""
Asana tool output models.

Reference: node_modules/@composio/core/generated/asana.ts
"""

# Unwired as of 2026-06; kept for future use.
# from pydantic import BaseModel, ConfigDict, Field
#
# class AsanaTask(BaseModel):
#     model_config = ConfigDict(extra="ignore")
#     gid: str | None = None
#     name: str | None = None
#     due_on: str | None = None
#     completed: bool = False
#
# class AsanaSearchTasksData(BaseModel):
#     """Output data for ASANA_SEARCH_TASKS_IN_WORKSPACE tool."""
#     model_config = ConfigDict(extra="ignore")
#     data: list[AsanaTask] = Field(default_factory=list)
#     tasks: list[AsanaTask] = Field(default_factory=list)
#     def get_tasks(self) -> list[AsanaTask]:
#         return self.data or self.tasks
