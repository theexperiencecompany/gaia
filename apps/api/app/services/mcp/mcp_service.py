"""
Simple MCP Service for connecting to MCP servers like DeepWiki.

This is a minimal implementation that:
1. Connects to MCP servers via SSE transport
2. Returns LangChain-compatible tools
3. Integrates with GAIA's ToolRegistry
"""

from dataclasses import dataclass
from typing import Optional

from app.config.loggers import langchain_logger as logger
from langchain_core.tools import BaseTool


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server."""

    name: str
    url: str
    api_key: Optional[str] = None


# Pre-configured system MCP servers
SYSTEM_MCP_SERVERS = {
    "deepwiki": MCPServerConfig(
        name="deepwiki",
        url="https://mcp.deepwiki.com/sse",
    ),
}


class MCPService:
    """Simple service for connecting to MCP servers and getting tools."""

    def __init__(self):
        self._connected_servers: dict[str, list[BaseTool]] = {}

    async def connect(self, config: MCPServerConfig) -> list[BaseTool]:
        """
        Connect to an MCP server and return its tools as LangChain tools.

        Args:
            config: MCP server configuration

        Returns:
            List of LangChain BaseTool objects
        """
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient

            logger.info(f"Connecting to MCP server: {config.name} at {config.url}")

            # Build server config for MultiServerMCPClient
            server_config = {
                config.name: {
                    "transport": "sse",
                    "url": config.url,
                }
            }

            # Add auth headers if API key provided
            if config.api_key:
                server_config[config.name]["headers"] = {
                    "Authorization": f"Bearer {config.api_key}",
                }

            # Create client and get tools
            client = MultiServerMCPClient(server_config)
            tools = await client.get_tools()

            self._connected_servers[config.name] = tools
            logger.info(
                f"Connected to {config.name}: found {len(tools)} tools - "
                f"{[t.name for t in tools]}"
            )

            return tools

        except ImportError:
            logger.error(
                "langchain-mcp-adapters not installed. "
                "Run: pip install langchain-mcp-adapters"
            )
            return []
        except Exception as e:
            logger.error(f"Failed to connect to MCP server {config.name}: {e}")
            return []

    async def connect_deepwiki(self) -> list[BaseTool]:
        """Connect to DeepWiki MCP server and return tools."""
        return await self.connect(SYSTEM_MCP_SERVERS["deepwiki"])

    async def get_tools(self, server_name: str) -> list[BaseTool]:
        """Get tools for an already connected server."""
        return self._connected_servers.get(server_name, [])

    def is_connected(self, server_name: str) -> bool:
        """Check if a server is connected."""
        return server_name in self._connected_servers


# Global singleton
_mcp_service: Optional[MCPService] = None


def get_mcp_service() -> MCPService:
    """Get or create the global MCP service instance."""
    global _mcp_service
    if _mcp_service is None:
        _mcp_service = MCPService()
    return _mcp_service
