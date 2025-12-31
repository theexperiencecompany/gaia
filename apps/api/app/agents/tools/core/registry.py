import asyncio
from collections.abc import Mapping
from functools import cache
from typing import Dict, Iterator, List, Optional

from app.agents.tools import (
    calendar_tool,
    code_exec_tool,
    document_tool,
    file_tools,
    flowchart_tool,
    goal_tool,
    google_docs_tool,
    image_tool,
    integration_tool,
    memory_tools,
    notification_tool,
    reminder_tool,
    search_tool,
    support_tool,
    todo_tool,
    weather_tool,
    webpage_tool,
)
from app.config.loggers import langchain_logger as logger
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from langchain_core.tools import BaseTool


class DynamicToolDict(Mapping[str, BaseTool]):
    """
    A dict-like wrapper that provides live access to the tool registry.

    This allows tools added to the registry after graph compilation
    to be accessible to the agent.
    """

    def __init__(self, registry: "ToolRegistry"):
        self._registry = registry
        self._extra_tools: Dict[str, BaseTool] = {}

    def __getitem__(self, key: str) -> BaseTool:
        # Check extra tools first (like handoff)
        if key in self._extra_tools:
            return self._extra_tools[key]
        # Then check registry
        tool_dict = self._registry._get_tool_dict_internal()
        if key in tool_dict:
            return tool_dict[key]
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        seen = set()
        for key in self._extra_tools:
            if key not in seen:
                seen.add(key)
                yield key
        for key in self._registry._get_tool_dict_internal():
            if key not in seen:
                seen.add(key)
                yield key

    def __len__(self) -> int:
        return len(
            set(self._extra_tools.keys())
            | set(self._registry._get_tool_dict_internal().keys())
        )

    def __contains__(self, key: object) -> bool:
        return (
            key in self._extra_tools or key in self._registry._get_tool_dict_internal()
        )

    def update(self, other: Dict[str, BaseTool]) -> None:
        """Add extra tools (like handoff) that aren't in the registry."""
        self._extra_tools.update(other)

    def values(self):
        """Return all tool values for ToolNode initialization."""
        all_tools = dict(self._registry._get_tool_dict_internal())
        all_tools.update(self._extra_tools)
        return all_tools.values()

    def keys(self):
        return list(self)

    def items(self):
        all_tools = dict(self._registry._get_tool_dict_internal())
        all_tools.update(self._extra_tools)
        return all_tools.items()


class Tool:
    """Simplified tool object that holds individual tool metadata."""

    def __init__(
        self,
        tool: BaseTool,
        name: Optional[str] = None,
        is_core: bool = False,
    ):
        self.tool = tool
        self.name = name or tool.name
        self.is_core = is_core


class ToolCategory:
    """Category that holds tools and category-level metadata."""

    def __init__(
        self,
        name: str,
        space: str = "general",
        require_integration: bool = False,
        integration_name: Optional[str] = None,
        is_delegated: bool = False,
    ):
        self.name = name
        self.space = space
        self.require_integration = require_integration
        self.integration_name = integration_name
        self.is_delegated = is_delegated
        self.tools: List[Tool] = []

    def add_tool(
        self, tool: BaseTool, is_core: bool = False, name: Optional[str] = None
    ):
        """Add a tool to this category."""
        self.tools.append(Tool(tool=tool, name=name, is_core=is_core))

    def add_tools(self, tools: List[BaseTool], is_core: bool = False):
        """Add multiple tools to this category."""
        for tool in tools:
            self.add_tool(tool, is_core=is_core)

    def get_tool_objects(self) -> List[BaseTool]:
        """Get the actual tool objects for binding."""
        return [tool.tool for tool in self.tools]

    def get_core_tools(self) -> List[Tool]:
        """Get only core tools from this category."""
        return [tool for tool in self.tools if tool.is_core]


class ToolInfo:
    """Metadata for a tool."""

    def __init__(self, tool: BaseTool, space: str):
        self.tool = tool
        self.space = space

    tool: BaseTool
    space: str


class ToolRegistry:
    """Modern tool registry with category-based organization."""

    def __init__(self) -> None:
        self._categories: Dict[str, ToolCategory] = {}

    async def setup(self):
        self._initialize_categories()

    def _add_category(
        self,
        name: str,
        tools: Optional[List[BaseTool]] = None,
        core_tools: Optional[List[BaseTool]] = None,
        space: str = "general",
        require_integration: bool = False,
        integration_name: Optional[str] = None,
        is_delegated: bool = False,
    ):
        """Helper to create and register a category."""
        category = ToolCategory(
            name=name,
            space=space,
            require_integration=require_integration,
            integration_name=integration_name,
            is_delegated=is_delegated,
        )
        if core_tools:
            category.add_tools(core_tools, is_core=True)
        if tools:
            category.add_tools(tools)
        self._categories[name] = category

    def _initialize_categories(self):
        """Initialize core tool categories. Provider tools are loaded lazily."""

        self._add_category(
            "search",
            tools=[
                search_tool.web_search_tool,
                webpage_tool.fetch_webpages,
            ],
        )

        self._add_category(
            "documents",
            tools=[file_tools.query_file, document_tool.generate_document],
        )

        self._add_category("notifications", tools=[*notification_tool.tools])
        self._add_category("todos", tools=[*todo_tool.tools])
        self._add_category("reminders", tools=[*reminder_tool.tools])
        self._add_category("goal_tracking", tools=goal_tool.tools)
        self._add_category("support", tools=[support_tool.create_support_ticket])
        self._add_category("memory", tools=memory_tools.tools)
        self._add_category("integrations", tools=integration_tool.tools)
        self._add_category(
            "development",
            tools=[code_exec_tool.execute_code, flowchart_tool.create_flowchart],
        )
        self._add_category("creative", tools=[image_tool.generate_image])
        self._add_category("weather", tools=[weather_tool.get_weather])

        self._add_category(
            "google_calendar",
            tools=calendar_tool.tools,
            require_integration=True,
            integration_name="google_calendar",
            is_delegated=True,
            space="google_calendar",
        )

        self._add_category(
            "google_docs",
            tools=google_docs_tool.tools,
            require_integration=True,
            integration_name="google_docs",
        )

    async def register_mcp_tools(self, server_name: str = "deepwiki"):
        """
        Register MCP server tools.
        Connects to an MCP server and adds its tools to the registry.
        """
        if server_name in self._categories:
            return self._categories[server_name]

        try:
            from app.services.mcp.mcp_client import get_mcp_client

            # Use system user for unauthenticated MCP connections at startup
            mcp_client = get_mcp_client(user_id="_system")
            tools = await mcp_client.connect(server_name)

            if tools:
                self._add_category(
                    name=f"mcp_{server_name}",
                    tools=tools,
                    space="mcp",
                )
                await self._index_category_tools(f"mcp_{server_name}")
                logger.info(f"Registered {len(tools)} MCP tools from {server_name}")
                return self._categories[f"mcp_{server_name}"]
        except Exception as e:
            logger.error(f"Failed to register MCP tools from {server_name}: {e}")

    async def register_provider_tools(
        self,
        toolkit_name: str,
        space_name: str,
        specific_tools: list[str] | None = None,
    ):
        """
        Register provider tools on-demand when subagent is created.
        Tools are loaded from Composio and indexed in ChromaDB.
        """
        if toolkit_name in self._categories:
            return self._categories[toolkit_name]

        from app.services.composio.composio_service import get_composio_service

        logger.info(
            f"Registering provider tools for {toolkit_name} (space: {space_name})"
        )

        composio_service = get_composio_service()

        if specific_tools:
            tools = await composio_service.get_tools_by_name(specific_tools)
        else:
            tools = await composio_service.get_tools(tool_kit=toolkit_name)

        self._add_category(
            name=toolkit_name,
            tools=tools,
            require_integration=True,
            integration_name=toolkit_name,
            is_delegated=True,
            space=space_name,
        )

        await self._index_category_tools(toolkit_name)

        logger.info(f"Registered {len(tools)} tools for {toolkit_name}")
        return self._categories[toolkit_name]

    async def load_all_provider_tools(self):
        """
        Load all provider tools from OAuth integrations.
        This method loads tools for all integrations managed by composio
        that have subagent configurations and syncs them to the store.
        Tools are loaded in parallel for better performance.
        """
        from app.config.oauth_config import OAUTH_INTEGRATIONS

        async def load_provider(integration):
            toolkit_name = integration.composio_config.toolkit
            space_name = integration.subagent_config.tool_space
            specific_tools = integration.subagent_config.specific_tools

            # Skip if already loaded
            if toolkit_name in self._categories:
                return

            try:
                await self.register_provider_tools(
                    toolkit_name=toolkit_name,
                    space_name=space_name,
                    specific_tools=specific_tools,
                )
            except Exception as e:
                logger.error(f"Failed to load provider tools for {toolkit_name}: {e}")

        # Collect all integrations that need loading
        integrations_to_load = [
            integration
            for integration in OAUTH_INTEGRATIONS
            if (
                integration.managed_by == "composio"
                and integration.composio_config
                and integration.subagent_config
                and integration.subagent_config.has_subagent
            )
        ]

        # Load all providers in parallel
        await asyncio.gather(*[load_provider(i) for i in integrations_to_load])

    async def load_all_mcp_tools(self):
        """
        Load all tools from MCP-managed integrations.
        Similar to load_all_provider_tools but for MCP servers.
        """
        from app.config.oauth_config import OAUTH_INTEGRATIONS

        async def load_mcp_integration(integration):
            category_name = integration.id

            # Skip if already loaded
            if category_name in self._categories:
                return

            # Skip MCP integrations requiring auth at startup - load on user connect
            mcp_config = integration.mcp_config
            if mcp_config.requires_auth:
                logger.info(f"Skipping auth-required MCP {integration.id} at startup")
                return

            try:
                from app.services.mcp.mcp_client import get_mcp_client

                # Use system user for unauthenticated MCP connections at startup
                mcp_client = get_mcp_client(user_id="_system")
                tools = await mcp_client.connect(integration.id)

                if tools:
                    space = (
                        integration.subagent_config.tool_space
                        if integration.subagent_config
                        else "mcp"
                    )
                    self._add_category(
                        name=category_name,
                        tools=tools,
                        space=space,
                        integration_name=integration.id,
                    )
                    await self._index_category_tools(category_name)
                    logger.info(
                        f"Registered {len(tools)} MCP tools from {integration.id}"
                    )
            except Exception as e:
                logger.info(f"MCP {integration.id} not loaded at startup: {e}")

        # Collect all MCP integrations
        mcp_integrations = [
            integration
            for integration in OAUTH_INTEGRATIONS
            if integration.managed_by == "mcp" and integration.mcp_config
        ]

        # Load all MCP tools in parallel
        await asyncio.gather(*[load_mcp_integration(i) for i in mcp_integrations])

    async def _index_category_tools(self, category_name: str):
        """Index tools from a category into ChromaDB store."""
        from app.db.chroma.chroma_tools_store import index_tools_to_store

        category = self._categories.get(category_name)
        if not category:
            return

        tools_with_space = [(tool.tool, category.space) for tool in category.tools]
        await index_tools_to_store(tools_with_space)

    def get_category(self, name: str) -> Optional[ToolCategory]:
        """Get a specific category by name."""
        return self._categories.get(name)

    def get_category_by_space(self, space: str) -> Optional[ToolCategory]:
        """Get a category by its tool space value.

        Searches all categories and returns the first one where category.space matches.
        This handles dynamic category names like mcp_{integration}_{user_id}.
        """
        for category in self._categories.values():
            if category.space == space:
                return category
        return None

    def get_all_category_objects(
        self, ignore_categories: List[str] = []
    ) -> Dict[str, ToolCategory]:
        """Get all categories as ToolCategory objects."""
        return {
            name: category
            for name, category in self._categories.items()
            if name not in ignore_categories
        }

    async def load_user_mcp_tools(self, user_id: str) -> Dict[str, List[BaseTool]]:
        """
        Load all connected MCP tools for a specific user.

        Connects to each MCP server the user has authenticated with,
        retrieves tools, and adds them to the registry under user-specific categories.

        Returns dict mapping integration_id -> list of tools loaded.
        """
        from app.config.oauth_config import get_integration_by_id
        from app.services.mcp.mcp_client import get_mcp_client

        mcp_client = get_mcp_client(user_id=user_id)
        all_tools = await mcp_client.get_all_connected_tools()

        loaded: Dict[str, List[BaseTool]] = {}

        for integration_id, tools in all_tools.items():
            if not tools:
                continue

            # Category name includes user_id to keep tools separate
            category_name = f"mcp_{integration_id}_{user_id}"

            # Skip if already loaded for this user
            if category_name in self._categories:
                loaded[integration_id] = tools
                continue

            # Get space from integration config
            integration = get_integration_by_id(integration_id)
            space = "mcp"
            if integration and integration.subagent_config:
                space = integration.subagent_config.tool_space

            self._add_category(
                name=category_name,
                tools=tools,
                space=space,
                integration_name=integration_id,
            )
            await self._index_category_tools(category_name)
            loaded[integration_id] = tools
            logger.info(
                f"Loaded {len(tools)} MCP tools from {integration_id} for user {user_id}"
            )

        return loaded

    def get_user_mcp_tool_dict(self, user_id: str) -> Dict[str, BaseTool]:
        """
        Get tool dict for user's MCP tools only.

        Returns mapping of tool name -> tool instance for user-specific MCP tools.
        """
        tools: Dict[str, BaseTool] = {}
        prefix = f"mcp_"
        suffix = f"_{user_id}"

        for name, category in self._categories.items():
            if name.startswith(prefix) and name.endswith(suffix):
                for tool in category.tools:
                    tools[tool.name] = tool.tool

        return tools

    @cache
    def get_category_of_tool(self, tool_name: str) -> str:
        """Get the category of a specific tool by name."""
        for category in self._categories.values():
            for tool in category.tools:
                if tool.name == tool_name:
                    return category.name
        return "unknown"

    def get_all_tools_for_search(self, include_delegated: bool = True) -> List[Tool]:
        """
        Get all tool objects for semantic search (includes delegated tools).

        Returns:
            List of Tool objects for semantic search.
        """
        tools: List[Tool] = []
        for category in self._categories.values():
            if category.is_delegated and not include_delegated:
                continue
            tools.extend(category.tools)
        return tools

    def get_core_tools(self) -> List[Tool]:
        """
        Get all core tools across all categories.

        Returns:
            List of core Tool objects.
        """
        core_tools = []
        for category in self._categories.values():
            core_tools.extend(category.get_core_tools())
        return core_tools

    def _get_tool_dict_internal(self) -> Dict[str, BaseTool]:
        """Internal method to get current tool dict (used by DynamicToolDict)."""
        all_tools = self.get_all_tools_for_search()
        return {tool.name: tool.tool for tool in all_tools}

    def get_tool_dict(self) -> DynamicToolDict:
        """Get a dynamic dictionary mapping tool names to tool instances for agent binding.

        Returns a DynamicToolDict that provides live access to tools,
        allowing tools added after graph compilation to be accessible.
        """
        return DynamicToolDict(self)

    def get_tool_names(self) -> List[str]:
        """Get list of all tool names including delegated ones."""
        tools = self.get_all_tools_for_search()
        return [tool.name for tool in tools]


async def get_tool_registry() -> ToolRegistry:
    """
    Accessor for the global tool registry instance.

    Note: We can use sync access here because the tool registry is
    initialized with auto_initialize=True in the lazy provider.

    Returns:
        The global ToolRegistry instance.
    """
    tool_registry = await providers.aget("tool_registry")

    if tool_registry is None:
        raise RuntimeError("ToolRegistry is not available")

    return tool_registry


@lazy_provider(
    name="tool_registry",
    required_keys=[],
    strategy=MissingKeyStrategy.ERROR,
    auto_initialize=True,
)
async def init_tool_registry():
    tool_registry = ToolRegistry()
    await tool_registry.setup()
    return tool_registry
