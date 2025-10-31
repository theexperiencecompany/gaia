"""
MCP Server Registry

Pre-configured popular remote MCP servers that users can connect to.
These are NOT OAuth integrations - they're remote MCP protocol servers.

Based on official MCP servers list: https://github.com/modelcontextprotocol/servers
"""

from typing import List, Optional

from pydantic import BaseModel


class MCPServerTemplate(BaseModel):
    """Template for a pre-configured MCP server."""

    id: str
    name: str
    description: str
    category: str
    server_url: Optional[str] = None
    setup_instructions: str
    requires_auth: bool = False
    auth_type: Optional[str] = None  # 'oauth', 'bearer', 'api_key', or None
    oauth_integration_id: Optional[str] = None  # Links to OAuth integration
    documentation_url: str
    icon_url: str


# Remote MCP Servers Only
# We focus on remote MCP servers that are hosted and don't require local setup
MCP_SERVER_REGISTRY: List[MCPServerTemplate] = [
    MCPServerTemplate(
        id="github",
        name="GitHub",
        description="GitHub's official remote MCP Server for repository operations, issues, PRs, workflows, and code management.",
        category="development",
        server_url="https://api.githubcopilot.com/mcp/",
        setup_instructions="Connect your GitHub account via OAuth to enable repository operations, issue management, and code analysis.",
        requires_auth=True,
        auth_type="oauth",
        oauth_integration_id="github",
        documentation_url="https://github.com/github/github-mcp-server",
        icon_url="/images/icons/github.png",
    ),
    MCPServerTemplate(
        id="linear",
        name="Linear",
        description="Linear's official remote MCP server for searching, creating, and updating issues, projects, and comments.",
        category="productivity",
        server_url="https://mcp.linear.app/mcp",
        setup_instructions="Connect your Linear workspace via OAuth to enable issue management, project tracking, and team collaboration.",
        requires_auth=True,
        auth_type="oauth",
        oauth_integration_id="linear",
        documentation_url="https://linear.app/docs/mcp",
        icon_url="/images/icons/linear.png",
    ),
]


def get_mcp_templates() -> List[MCPServerTemplate]:
    """Get all pre-configured MCP server templates."""
    return MCP_SERVER_REGISTRY


def get_mcp_template_by_id(server_id: str) -> Optional[MCPServerTemplate]:
    """Get a specific MCP server template by ID."""
    return next((s for s in MCP_SERVER_REGISTRY if s.id == server_id), None)


def get_mcp_templates_by_category(category: str) -> List[MCPServerTemplate]:
    """Get MCP server templates filtered by category."""
    return [s for s in MCP_SERVER_REGISTRY if s.category == category]
