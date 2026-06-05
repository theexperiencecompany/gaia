"""
ClickUp tool output models.

Reference: node_modules/@composio/core/generated/clickup.ts
"""

# Unwired as of 2026-06; kept for future use.
# from pydantic import BaseModel, ConfigDict, Field
#
# class ClickUpTask(BaseModel):
#     model_config = ConfigDict(extra="ignore")
#     id: str | None = None
#     name: str | None = None
#     due_date: str | None = None
#
# class ClickUpTasksData(BaseModel):
#     """Output data for CLICKUP_GET_FILTERED_TEAM_TASKS tool."""
#     model_config = ConfigDict(extra="ignore")
#     tasks: list[ClickUpTask] = Field(default_factory=list)
