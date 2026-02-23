"""
GitHub tool schemas.

Reference: node_modules/@composio/core/generated/github.ts

Note: All Composio tool responses are wrapped in ToolExecutionResponse with
`data`, `error`, `successful` keys. These models represent the INNER data structure.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class GitHubListRepositoriesInput(BaseModel):
    """Input for GITHUB_LIST_REPOSITORIES_FOR_THE_AUTHENTICATED_USER."""

    before: str | None = Field(
        None, description="Filter for repos updated before timestamp"
    )
    direction: Literal["asc", "desc"] | None = Field(None, description="Sort direction")
    page: int = Field(1, description="Page number")
    per_page: int = Field(30, description="Results per page")
    raw_response: bool = Field(False, description="Return full raw response")
    since: str | None = Field(
        None, description="Filter for repos updated after timestamp"
    )
    sort: Literal["created", "updated", "pushed", "full_name"] | None = Field(
        None, description="Sort field"
    )
    type: Literal["all", "owner", "public", "private", "member"] | None = Field(
        None, description="Repo type filter"
    )
    visibility: Literal["all", "public", "private"] | None = Field(
        None, description="Visibility filter"
    )


class GitHubRepository(BaseModel):
    """GitHub repository model."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: int | None = None
    name: str | None = None
    full_name: str | None = None
    private: bool | None = None
    owner: dict[str, Any] | None = None
    html_url: str | None = None
    description: str | None = None
    fork: bool | None = None
    url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    pushed_at: str | None = None
    default_branch: str | None = None


class GitHubListRepositoriesData(BaseModel):
    """Data inside ToolExecutionResponse.data for GITHUB_LIST_REPOSITORIES.

    The API returns a list of repositories directly, but the Composio wrapper
    may nest it under different keys. This model handles both cases.
    """

    model_config = ConfigDict(from_attributes=True, extra="allow")

    # Repositories may be at top level as a list or nested
    # We handle this in the handler by checking structure

    @classmethod
    def from_response_data(cls, data: dict[str, Any]) -> list[GitHubRepository]:
        """Extract repositories from response data.

        The data structure can vary:
        - Direct list of repos (when raw_response=False)
        - Nested under 'repositories' key
        - Nested under 'data' key (rare)
        """
        # If data itself is a list, it's the repositories
        if isinstance(data, list):
            return [GitHubRepository.model_validate(r) for r in data]

        # Try common keys
        repos_list = data.get("repositories") or data.get("data") or []
        if isinstance(repos_list, list):
            return [GitHubRepository.model_validate(r) for r in repos_list]

        return []
