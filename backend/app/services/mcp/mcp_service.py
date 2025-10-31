"""
MCP Service

Manages MCP client lifecycle, server connections, and tool discovery.
Integrates mcp-use library with GAIA's tool registry and agent system.
"""

from typing import Any, Dict, List, Optional

from app.config.loggers import common_logger as logger
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from app.db.postgresql import get_db_session
from app.models.mcp_models import (
    MCPAuthConfig,
    MCPServer,
    MCPServerConfig,
    MCPServerCreateRequest,
    MCPServerResponse,
    MCPServerStatusResponse,
    MCPServerType,
    MCPServerUpdateRequest,
    MCPToolInfo,
)
from langchain_core.tools import BaseTool
from mcp_use import MCPClient
from mcp_use.adapters.langchain_adapter import LangChainAdapter
from sqlalchemy import select


class MCPService:
    """Service for managing MCP servers and tool discovery."""

    def __init__(self):
        """Initialize MCP service."""
        self._clients: Dict[str, Any] = {}  # user_id -> MCPClient
        self._adapters: Dict[str, Any] = {}  # user_id -> LangChainAdapter
        self._user_tools: Dict[
            str, Dict[str, List[BaseTool]]
        ] = {}  # user_id -> {server_name -> tools}
        self._initialized = False
        logger.info("MCP service initialized successfully")

    async def initialize_user_client(self, user_id: str) -> Optional[Any]:
        """
        Initialize MCP client for a user based on their configured servers.

        Args:
            user_id: User identifier

        Returns:
            MCPClient instance or None if no servers configured
        """
        # Get user's MCP servers
        servers = await self.get_user_servers(user_id)
        if not servers:
            logger.debug(f"No MCP servers configured for user {user_id}")
            return None

        # Build mcp-use config
        mcp_config = {"mcpServers": {}}
        for server in servers:
            if server.enabled:
                server_config = MCPServerConfig.model_validate(server.config)
                mcp_config["mcpServers"][server.name] = (
                    server_config.to_mcp_use_config()
                )

        if not mcp_config["mcpServers"]:
            logger.debug(f"No enabled MCP servers for user {user_id}")
            return None

        try:
            # Create MCPClient from config
            client = MCPClient.from_dict(mcp_config)
            await client.create_all_sessions()

            # Store client and adapter
            self._clients[user_id] = client
            self._adapters[user_id] = LangChainAdapter()

            logger.info(
                f"Initialized MCP client for user {user_id} with {len(mcp_config['mcpServers'])} servers"
            )
            return client

        except Exception as e:
            logger.error(f"Failed to initialize MCP client for user {user_id}: {e}")
            return None

    async def get_user_client(self, user_id: str) -> Optional[Any]:
        """Get or create MCP client for a user."""
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

    async def get_user_servers(self, user_id: str) -> List[MCPServer]:
        """Get all MCP servers for a user."""
        async with get_db_session() as session:
            stmt = select(MCPServer).where(MCPServer.user_id == user_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def create_server(
        self, user_id: str, request: MCPServerCreateRequest
    ) -> MCPServerResponse:
        """Create a new MCP server configuration."""
        # Build config
        server_config = MCPServerConfig(
            name=request.name,
            description=request.description,
            server_type=request.server_type,
            enabled=request.enabled,
            stdio_config=request.stdio_config,
            http_config=request.http_config,
            auth_config=request.auth_config or MCPAuthConfig(),
            sandbox_config=request.sandbox_config,
            metadata=request.metadata,
        )

        async with get_db_session() as session:
            server = MCPServer(
                user_id=user_id,
                name=request.name,
                description=request.description,
                server_type=request.server_type.value,
                enabled=request.enabled,
                config=server_config.model_dump(),
            )
            session.add(server)
            await session.commit()
            await session.refresh(server)

            # Invalidate cached client
            if user_id in self._clients:
                await self._clients[user_id].close_all_sessions()
                del self._clients[user_id]
            if user_id in self._user_tools:
                del self._user_tools[user_id]

            return MCPServerResponse(
                id=server.id,
                name=server.name,
                description=server.description or "",
                server_type=MCPServerType(server.server_type),
                enabled=server.enabled,
                config=server_config,
                created_at=server.created_at,
                updated_at=server.updated_at,
            )

    async def update_server(
        self, user_id: str, server_id: int, request: MCPServerUpdateRequest
    ) -> Optional[MCPServerResponse]:
        """Update an MCP server configuration."""
        async with get_db_session() as session:
            stmt = select(MCPServer).where(
                MCPServer.id == server_id, MCPServer.user_id == user_id
            )
            result = await session.execute(stmt)
            server = result.scalar_one_or_none()

            if not server:
                return None

            # Update fields
            config = MCPServerConfig.model_validate(server.config)
            if request.name:
                server.name = request.name
                config.name = request.name
            if request.description:
                server.description = request.description
                config.description = request.description
            if request.enabled is not None:
                server.enabled = request.enabled
                config.enabled = request.enabled
            if request.stdio_config:
                config.stdio_config = request.stdio_config
            if request.http_config:
                config.http_config = request.http_config
            if request.auth_config:
                config.auth_config = request.auth_config
            if request.sandbox_config:
                config.sandbox_config = request.sandbox_config
            if request.metadata:
                config.metadata = request.metadata

            server.config = config.model_dump()
            await session.commit()
            await session.refresh(server)

            # Invalidate cache
            if user_id in self._clients:
                await self._clients[user_id].close_all_sessions()
                del self._clients[user_id]
            if user_id in self._user_tools:
                del self._user_tools[user_id]

            return MCPServerResponse(
                id=server.id,
                name=server.name,
                description=server.description or "",
                server_type=MCPServerType(server.server_type),
                enabled=server.enabled,
                config=config,
                created_at=server.created_at,
                updated_at=server.updated_at,
            )

    async def delete_server(self, user_id: str, server_id: int) -> bool:
        """Delete an MCP server configuration."""
        async with get_db_session() as session:
            stmt = select(MCPServer).where(
                MCPServer.id == server_id, MCPServer.user_id == user_id
            )
            result = await session.execute(stmt)
            server = result.scalar_one_or_none()

            if not server:
                return False

            await session.delete(server)
            await session.commit()

            # Invalidate cache
            if user_id in self._clients:
                await self._clients[user_id].close_all_sessions()
                del self._clients[user_id]
            if user_id in self._user_tools:
                del self._user_tools[user_id]

            return True

    async def get_server_status(
        self, user_id: str, server_id: int
    ) -> Optional[MCPServerStatusResponse]:
        """Get status and tools for a specific MCP server."""
        async with get_db_session() as session:
            stmt = select(MCPServer).where(
                MCPServer.id == server_id, MCPServer.user_id == user_id
            )
            result = await session.execute(stmt)
            server = result.scalar_one_or_none()

            if not server:
                return None

            if not server.enabled:
                return MCPServerStatusResponse(
                    server_id=server.id,
                    name=server.name,
                    connected=False,
                    tool_count=0,
                    tools=[],
                    error="Server disabled",
                )

            try:
                # Get tools for this server
                tools_dict = await self.get_user_tools(user_id, server.name)
                server_tools = tools_dict.get(server.name, [])

                tool_infos = [
                    MCPToolInfo(
                        name=tool.name,
                        description=tool.description or "",
                        server_name=server.name,
                        parameters=getattr(tool, "args_schema", None),
                    )
                    for tool in server_tools
                ]

                return MCPServerStatusResponse(
                    server_id=server.id,
                    name=server.name,
                    connected=True,
                    tool_count=len(tool_infos),
                    tools=tool_infos,
                )

            except Exception as e:
                logger.error(f"Error getting status for server {server_id}: {e}")
                return MCPServerStatusResponse(
                    server_id=server.id,
                    name=server.name,
                    connected=False,
                    tool_count=0,
                    tools=[],
                    error=str(e),
                )

    async def cleanup_user_client(self, user_id: str):
        """Clean up MCP client resources for a user."""
        if user_id in self._clients:
            try:
                await self._clients[user_id].close_all_sessions()
            except Exception as e:
                logger.error(f"Error closing sessions for user {user_id}: {e}")
            del self._clients[user_id]

        if user_id in self._adapters:
            del self._adapters[user_id]

        if user_id in self._user_tools:
            del self._user_tools[user_id]


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
