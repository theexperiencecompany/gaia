"""MCP configuration models (Pydantic)."""

from typing import Literal

from pydantic import BaseModel


class MCPConfig(BaseModel):
    """Configuration for MCP (Model Context Protocol) integration."""

    server_url: str
    requires_auth: bool = False
    auth_type: Literal["none", "oauth", "bearer"] | None = None
    transport: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    client_id_env: str | None = None
    client_secret_env: str | None = None
    oauth_scopes: list[str] | None = None
    oauth_metadata: dict[str, str] | None = None


class OAuthScope(BaseModel):
    """OAuth scope configuration."""

    scope: str
    description: str


class ComposioConfig(BaseModel):
    """Configuration for Composio integration."""

    auth_config_id: str
    toolkit: str
    toolkit_version: str | None = None


class SubAgentConfig(BaseModel):
    """Configuration for sub-agent metadata."""

    has_subagent: bool = False
    agent_name: str
    tool_space: str
    handoff_tool_name: str
    domain: str
    capabilities: str
    use_cases: str
    system_prompt: str
    use_direct_tools: bool = False
    disable_retrieve_tools: bool = False
    specific_tools: list[str] | None = None
    auto_bind_tools: list[str] | None = None
    memory_prompt: str | None = None
    # When False, finish_task is omitted from the subagent's tool set. The
    # subagent must terminate naturally with an AIMessage. The streaming
    # layer's complete_message accumulator captures that text directly —
    # no special-case extraction needed. Use False for read-only / answer-
    # only subagents (e.g. doc fetchers). Default True preserves the
    # explicit-completion contract for action subagents.
    include_finish_task: bool = True


class VariableExtraction(BaseModel):
    """Configuration for a single variable to extract from a tool response."""

    name: str  # Variable name (e.g., "username", "user_id", "email")
    field_path: str  # Dot-notation path to extract (e.g., "data.username")


class ToolMetadataConfig(BaseModel):
    """Configuration for one tool and its variables to extract."""

    tool: str  # Tool to call (e.g., "TWITTER_USER_LOOKUP_ME")
    variables: list[VariableExtraction]  # Variables to extract from this tool's response


class ProviderMetadataConfig(BaseModel):
    """Configuration for fetching provider-specific user metadata.

    Supports multiple tools, each with multiple variables to extract.

    Example:
        metadata_config=ProviderMetadataConfig(
            tools=[
                ToolMetadataConfig(
                    tool="TWITTER_USER_LOOKUP_ME",
                    variables=[
                        VariableExtraction(name="username", field_path="data.username"),
                        VariableExtraction(name="user_id", field_path="data.id"),
                    ],
                ),
            ],
        )
    """

    tools: list[ToolMetadataConfig]  # List of tools to call and variables to extract
