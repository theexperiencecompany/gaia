"""ClickUp task payloads the context tool reads and forwards.

Reference: https://developer.clickup.com/reference/gettasks (due_date is a
string or null holding epoch milliseconds; status.type is a string).
"""

from pydantic import BaseModel, ConfigDict, Field


class ClickUpTaskStatus(BaseModel):
    """The ``status`` object of a task."""

    model_config = ConfigDict(extra="allow")

    type: str


class ClickUpTask(BaseModel):
    """A task. Forwarded verbatim into the tool output — passthrough.

    ``status`` is documented as required; it stays optional because the tool has
    always tolerated its absence and the unit fixtures pin that.
    """

    model_config = ConfigDict(extra="allow")

    due_date: str | None = None
    status: ClickUpTaskStatus | None = None


class ClickUpTaskList(BaseModel):
    """``CLICKUP_GET_FILTERED_TEAM_TASKS`` data."""

    model_config = ConfigDict(extra="ignore")

    tasks: list[ClickUpTask] = Field(default_factory=list)
