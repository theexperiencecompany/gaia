"""MCP configuration models (Pydantic)."""

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel


class MCPConfig(BaseModel):
    """Configuration for MCP (Model Context Protocol) integration."""

    server_url: str
    requires_auth: bool = False
    auth_type: Optional[Literal["none", "oauth", "bearer"]] = None
    transport: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    client_id_env: Optional[str] = None
    client_secret_env: Optional[str] = None
    oauth_scopes: Optional[List[str]] = None
    oauth_metadata: Optional[Dict[str, str]] = None


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
    specific_tools: Optional[List[str]] = None
    auto_bind_tools: Optional[List[str]] = None
    memory_prompt: Optional[str] = None


class VariableExtraction(BaseModel):
    """Configuration for a single variable to extract from a tool response."""

    name: str  # Variable name (e.g., "username", "user_id", "email")
    field_path: str  # Dot-notation path to extract (e.g., "data.username")


class ToolMetadataConfig(BaseModel):
    """Configuration for one tool and its variables to extract."""

    tool: str  # Tool to call (e.g., "TWITTER_USER_LOOKUP_ME")
    variables: List[
        VariableExtraction
    ]  # Variables to extract from this tool's response


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

    tools: List[ToolMetadataConfig]  # List of tools to call and variables to extract
