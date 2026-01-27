"""
Linear tool schemas.

Reference: node_modules/@composio/core/generated/linear.ts

Note: All Composio tool responses are wrapped in ToolExecutionResponse with
`data`, `error`, `successful` keys. These models represent the INNER data structure.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LinearGetAllTeamsInput(BaseModel):
    """Input for LINEAR_GET_ALL_LINEAR_TEAMS."""

    pass  # No input parameters required


class LinearMember(BaseModel):
    """Linear team member."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str
    name: str = ""
    email: str = ""


class LinearTeam(BaseModel):
    """Linear team."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str
    key: str = ""
    name: str = ""
    members: list[LinearMember] = Field(default_factory=list)


class LinearGetAllTeamsData(BaseModel):
    """Data inside ToolExecutionResponse.data for LINEAR_GET_ALL_LINEAR_TEAMS.

    The API returns teams in 'items' or 'teams' field.
    """

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    items: list[dict[str, Any]] = Field(default_factory=list)
    teams: list[Any] = Field(default_factory=list)

    def get_teams(self) -> list[LinearTeam]:
        """Get teams list, preferring 'items' over 'teams'."""
        # Prefer 'items' as it has the structured data
        items_data = self.items if self.items else self.teams
        return [LinearTeam.model_validate(t) for t in items_data if isinstance(t, dict)]
