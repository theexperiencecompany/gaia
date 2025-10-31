"""
MCP Service - MongoDB + mcp-use Native

Manages MCP client lifecycle, server connections, and tool discovery.
Uses MongoDB for config storage, mcp-use handles OAuth and tokens.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from app.config.loggers import common_logger as logger
from app.config.oauth_config import get_integration_by_id
from app.config.token_repository import token_repository
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from app.db.mongodb.collections import mcp_servers_collection
from langchain_core.tools import BaseTool
from mcp_use import MCPClient
from mcp_use.adapters.langchain_adapter import LangChainAdapter


class MCPService:
    """Service for managing MCP servers - MongoDB + mcp-use."""

    def __init__(self):
        """Initialize MCP service."""
        self._clients: Dict[str, MCPClient] = {}  # user_id -> MCPClient
        self._adapters: Dict[str, LangChainAdapter] = {}  # user_id -> LangChainAdapter
        self._user_tools: Dict[
            str, Dict[str, List[BaseTool]]
        ] = {}  # user_id -> {server_name -> tools}
        logger.info("MCP service initialized")

    async def initialize_user_client(self, user_id: str) -> Optional[MCPClient]:
        """
        Initialize MCP client for a user from MongoDB configs.

        Builds mcp-use config dict from MongoDB documents.
        mcp-use handles OAuth tokens from ~/.mcp_use/tokens/
        """
        servers = await self.get_user_servers(user_id)
        if not servers:
            logger.debug(f"No MCP servers for user {user_id}")
            return None

        # Build mcp-use config from MongoDB docs
        mcp_config = {"mcpServers": {}}
        for server in servers:
            if server.get("enabled", True):
                # Use raw mcp_config stored in MongoDB
                mcp_config["mcpServers"][server["server_name"]] = server["mcp_config"]

        if not mcp_config["mcpServers"]:
            logger.debug(f"No enabled servers for user {user_id}")
            return None

        try:
            # mcp-use handles token loading from ~/.mcp_use/tokens/
            client = MCPClient.from_dict(mcp_config)
            await client.create_all_sessions()

            self._clients[user_id] = client
            self._adapters[user_id] = LangChainAdapter()

            logger.info(f"Initialized MCP client for user {user_id}")
            return client

        except Exception as e:
            logger.error(f"Failed to initialize MCP client: {e}")
            return None

    async def get_user_client(self, user_id: str) -> Optional[MCPClient]:
        """Get cached or initialize new MCP client."""
        if user_id in self._clients:
            return self._clients[user_id]
        return await self.initialize_user_client(user_id)

    async def get_user_tools(
        self, user_id: str, server_name: Optional[str] = None
    ) -> Dict[str, List[BaseTool]]:
        """
        Get LangChain tools from user's MCP servers.

        Args:
            user_id: User identifier
            server_name: Optional specific server name

        Returns:
            Dictionary mapping server names to tool lists
        """

        # Check if we have cached tools
        if user_id in self._user_tools:
            if server_name:
                return {server_name: self._user_tools[user_id].get(server_name, [])}
            return self._user_tools[user_id]

        # Get or create client
        client = await self.get_user_client(user_id)
        if not client:
            return {}

        # Get adapter
        adapter = self._adapters.get(user_id)
        if not adapter:
            adapter = LangChainAdapter()
            self._adapters[user_id] = adapter

        try:
            # Convert MCP tools to LangChain tools
            tools = await adapter.create_tools(client)

            # Organize tools by server
            server_tools: Dict[str, List[BaseTool]] = {}
            for tool in tools:
                # Extract server name from tool metadata if available
                tool_server = getattr(tool, "server_name", "unknown")
                if tool_server not in server_tools:
                    server_tools[tool_server] = []
                server_tools[tool_server].append(tool)

            # Cache tools
            self._user_tools[user_id] = server_tools

            if server_name:
                return {server_name: server_tools.get(server_name, [])}
            return server_tools

        except Exception as e:
            logger.error(f"Failed to get tools for user {user_id}: {e}")
            return {}

    async def get_user_servers(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all MCP servers from MongoDB."""
        cursor = mcp_servers_collection.find({"user_id": user_id})
        servers = await cursor.to_list(length=None)
        # Convert ObjectId to string for JSON serialization
        for server in servers:
            if "_id" in server:
                server["_id"] = str(server["_id"])
        return servers

    async def create_server(
        self,
        user_id: str,
        server_name: str,
        mcp_config: Dict[str, Any],
        display_name: str,
        description: str = "",
        oauth_integration_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create MCP server in MongoDB."""
        # Check if server exists
        existing = await mcp_servers_collection.find_one(
            {"user_id": user_id, "server_name": server_name}
        )
        if existing:
            raise ValueError(f"Server '{server_name}' already exists")

        doc = {
            "user_id": user_id,
            "server_name": server_name,
            "mcp_config": mcp_config,  # Raw mcp-use config
            "display_name": display_name,
            "description": description,
            "oauth_integration_id": oauth_integration_id,
            "enabled": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }

        result = await mcp_servers_collection.insert_one(doc)
        doc["_id"] = str(result.inserted_id)

        # Invalidate cache
        await self._invalidate_user_cache(user_id)

        logger.info(f"Created MCP server {server_name} for user {user_id}")
        return doc

    async def update_server(
        self, user_id: str, server_name: str, updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Update MCP server in MongoDB."""
        updates["updated_at"] = datetime.utcnow()

        result = await mcp_servers_collection.find_one_and_update(
            {"user_id": user_id, "server_name": server_name},
            {"$set": updates},
            return_document=True,
        )

        if result:
            result["_id"] = str(result["_id"])
            await self._invalidate_user_cache(user_id)
            logger.info(f"Updated MCP server {server_name}")

        return result

    async def delete_server(self, user_id: str, server_name: str) -> bool:
        """Delete MCP server from MongoDB."""
        result = await mcp_servers_collection.delete_one(
            {"user_id": user_id, "server_name": server_name}
        )

        if result.deleted_count > 0:
            await self._invalidate_user_cache(user_id)
            logger.info(f"Deleted MCP server {server_name}")
            return True

        return False

    async def get_server_status(
        self, user_id: str, server_name: str
    ) -> Optional[Dict[str, Any]]:
        """Get connection status and tools for MCP server."""
        server = await mcp_servers_collection.find_one(
            {"user_id": user_id, "server_name": server_name}
        )

        if not server:
            return None

        if not server.get("enabled", True):
            return {
                "server_name": server_name,
                "connected": False,
                "tool_count": 0,
                "tools": [],
                "error": "Server disabled",
            }

        try:
            # Get tools
            tools_dict = await self.get_user_tools(user_id, server_name)
            server_tools = tools_dict.get(server_name, [])

            tool_infos = [
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "server_name": server_name,
                }
                for tool in server_tools
            ]

            return {
                "server_name": server_name,
                "connected": True,
                "tool_count": len(tool_infos),
                "tools": tool_infos,
            }

        except Exception as e:
            logger.error(f"Error getting status: {e}")
            return {
                "server_name": server_name,
                "connected": False,
                "tool_count": 0,
                "tools": [],
                "error": str(e),
            }

    async def initiate_oauth(self, user_id: str, server_name: str) -> str:
        """
        Initiate OAuth flow for MCP server using existing OAuth integration.

        Returns authorization URL that redirects through our OAuth flow.
        After OAuth completes, user is redirected back to MCP callback.
        """
        
        server = await mcp_servers_collection.find_one(
            {"user_id": user_id, "server_name": server_name}
        )

        if not server:
            raise ValueError(f"Server '{server_name}' not found")

        # Get OAuth integration ID
        oauth_integration_id = server.get("oauth_integration_id")
        if not oauth_integration_id:
            raise ValueError(f"No OAuth integration configured for '{server_name}'")

        # Get OAuth integration config
        integration = get_integration_by_id(oauth_integration_id)
        if not integration:
            raise ValueError(f"OAuth integration '{oauth_integration_id}' not found")

        # Build authorization URL using existing OAuth flow
        # The OAuth callback will store tokens in PostgreSQL
        # Then redirect to /api/v1/mcp/oauth/{server_name}/callback
        redirect_path = f"/api/v1/mcp/oauth/{server_name}/callback"
        auth_url = f"/api/v1/oauth/{oauth_integration_id}/authorize?redirect_path={redirect_path}"
        
        logger.info(f"OAuth initiated for {server_name} using {oauth_integration_id}")
        return auth_url

    async def complete_oauth(
        self, user_id: str, server_name: str
    ) -> bool:
        """
        Complete OAuth flow after callback.

        The OAuth tokens are stored in PostgreSQL by the OAuth callback handler.
        mcp-use will read tokens from token_repository when initializing MCPClient.
        We just need to invalidate cache to reload client with new tokens.
        """
        server = await mcp_servers_collection.find_one(
            {"user_id": user_id, "server_name": server_name}
        )

        if not server:
            return False

        # Verify OAuth token exists
        oauth_integration_id = server.get("oauth_integration_id")
        if oauth_integration_id:
            try:
                # Check if token exists (will raise HTTPException if not)
                await token_repository.get_token(user_id, oauth_integration_id)
                logger.info(f"OAuth completed successfully for {server_name}")
            except Exception as e:
                logger.error(f"OAuth token not found for {server_name}: {e}")
                return False

        # Invalidate cache to reload with new tokens
        await self._invalidate_user_cache(user_id)
        return True

    async def _invalidate_user_cache(self, user_id: str):
        """Invalidate all cached data for a user."""
        if user_id in self._clients:
            try:
                await self._clients[user_id].close_all_sessions()
            except Exception as e:
                logger.error(f"Error closing sessions: {e}")
            del self._clients[user_id]

        if user_id in self._adapters:
            del self._adapters[user_id]

        if user_id in self._user_tools:
            del self._user_tools[user_id]

    async def cleanup_user_client(self, user_id: str):
        """Clean up MCP client resources."""
        await self._invalidate_user_cache(user_id)


@lazy_provider(
    name="mcp_service",
    required_keys=[],
    strategy=MissingKeyStrategy.WARN,
    auto_initialize=True,
    warning_message="MCP service initialized but mcp-use library may not be available",
)
def init_mcp_service():
    """Initialize the global MCP service instance."""
    return MCPService()


def get_mcp_service() -> MCPService:
    """Get the global MCP service instance."""
    service = providers.get("mcp_service")
    if service is None:
        raise RuntimeError("MCP service not available")
    return service
