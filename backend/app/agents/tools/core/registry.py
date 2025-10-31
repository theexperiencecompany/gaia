import asyncio
from functools import cache
from typing import Dict, List, Optional

from app.agents.core.subagents.handoff_tools import get_handoff_tools
from app.agents.tools import (
    calendar_tool,
    code_exec_tool,
    document_tool,
    file_tools,
    flowchart_tool,
    goal_tool,
    google_docs_tool,
    image_tool,
    memory_tools,
    notification_tool,
    reminder_tool,
    search_tool,
    support_tool,
    todo_tool,
    weather_tool,
    webpage_tool,
)
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from app.services.composio.composio_service import (
    get_composio_service,
)
from langchain_core.tools import BaseTool


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

    def __init__(self):
        self._categories: Dict[str, ToolCategory] = {}
        self._mcp_categories: Dict[str, str] = {}  # tool_name -> mcp_server_name

    async def setup(self):
        await self._initialize_categories()

    async def _initialize_categories(self):
        """Initialize all tool categories with their metadata and tools."""
        composio_service = get_composio_service()

        # Helper function to create and register categories
        def add_category(
            name: str,
            tools: Optional[List[BaseTool]] = None,
            core_tools: Optional[List[BaseTool]] = None,
            space: str = "general",
            require_integration: bool = False,
            integration_name: Optional[str] = None,
            is_delegated: bool = False,
        ):
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

        # Core categories (no integration required)
        add_category(
            "search",
            core_tools=[
                search_tool.web_search_tool,
                # search_tool.deep_research_tool,
                webpage_tool.fetch_webpages,
            ],
        )

        add_category(
            "documents",
            core_tools=[file_tools.query_file],
            tools=[document_tool.generate_document],
        )

        add_category(
            "delegation",
            core_tools=get_handoff_tools(["gmail", "notion", "twitter", "linkedin"]),
        )

        add_category("notifications", tools=[*notification_tool.tools])
        add_category("productivity", tools=[*todo_tool.tools, *reminder_tool.tools])
        add_category("goal_tracking", tools=goal_tool.tools)
        add_category("support", tools=[support_tool.create_support_ticket])
        add_category("memory", tools=memory_tools.tools)
        add_category(
            "development",
            tools=[code_exec_tool.execute_code, flowchart_tool.create_flowchart],
        )
        add_category("creative", tools=[image_tool.generate_image])
        add_category("weather", tools=[weather_tool.get_weather])

        # Integration-required categories
        add_category(
            "calendar",
            tools=calendar_tool.tools,
            require_integration=True,
            integration_name="google_calendar",
        )

        add_category(
            "google_docs",
            tools=google_docs_tool.tools,
            require_integration=True,
            integration_name="google_docs",
        )

        # Provider categories (integration required + delegated)
        provider_configs = [
            ("twitter", "TWITTER"),
            ("notion", "NOTION"),
            ("linkedin", "LINKEDIN"),
            ("google_sheets", "GOOGLE_SHEETS"),
            ("gmail", "GMAIL"),
        ]

        async def add_provider_category(
            name: str,
        ):
            tools = await composio_service.get_tools(tool_kit=name)
            add_category(
                name,
                tools=tools,
                require_integration=True,
                integration_name=name,
                is_delegated=True,
                space=name,
            )

        # Parallelize provider category addition
        await asyncio.gather(
            *[add_provider_category(name) for name, _ in provider_configs]
        )

    def get_category(self, name: str) -> Optional[ToolCategory]:
        """Get a specific category by name."""
        return self._categories.get(name)

    def get_all_category_objects(
        self, ignore_categories: List[str] = []
    ) -> Dict[str, ToolCategory]:
        """Get all categories as ToolCategory objects."""
        return {
            name: category
            for name, category in self._categories.items()
            if name not in ignore_categories
        }

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

    def get_tool_dict(self) -> Dict[str, BaseTool]:
        """Get a dictionary mapping tool names to tool instances for agent binding.

        This excludes delegated tools that should only be available via sub-agents.
        """
        all_tools = self.get_all_tools_for_search()
        return {tool.name: tool.tool for tool in all_tools}

    def get_tool_names(self) -> List[str]:
        """Get list of all tool names including delegated ones."""
        tools = self.get_all_tools_for_search()
        return [tool.name for tool in tools]

    async def add_mcp_handoff_tools(self, user_id: str) -> None:
        """
        Add MCP handoff tools to the delegation category.

        Args:
            user_id: User identifier
        """
        from app.agents.core.subagents.handoff_tools import get_mcp_handoff_tools
        from app.config.loggers import common_logger as logger

        try:
            mcp_handoff_tools = await get_mcp_handoff_tools(user_id)

            if mcp_handoff_tools:
                delegation_category = self._categories.get("delegation")
                if delegation_category:
                    delegation_category.add_tools(mcp_handoff_tools, is_core=True)
                    logger.info(
                        f"Added {len(mcp_handoff_tools)} MCP handoff tools to delegation category"
                    )

        except Exception as e:
            logger.error(f"Failed to add MCP handoff tools: {e}")

    async def register_mcp_tools(
        self, server_name: str, tools: List[BaseTool], user_id: Optional[str] = None
    ) -> None:
        """
        Register tools from an MCP server dynamically.

        Args:
            server_name: Name of the MCP server
            tools: List of tools from the MCP server
            user_id: Optional user ID for user-specific tool registration
        """
        from app.config.loggers import common_logger as logger

        category_name = f"mcp_{server_name}"

        # Create or update MCP server category
        if category_name not in self._categories:
            logger.info(f"Creating new MCP category: {category_name}")
            category = ToolCategory(
                name=category_name,
                space=f"mcp_{server_name}",
                require_integration=False,
                integration_name=None,
                is_delegated=True,  # MCP servers are delegated to subagents
            )
            self._categories[category_name] = category
        else:
            category = self._categories[category_name]

        # Add tools to category
        for tool in tools:
            category.add_tool(tool, is_core=False)
            self._mcp_categories[tool.name] = server_name

        logger.info(
            f"Registered {len(tools)} tools from MCP server '{server_name}' in category '{category_name}'"
        )

    async def unregister_mcp_server(self, server_name: str) -> None:
        """
        Unregister all tools from an MCP server.

        Args:
            server_name: Name of the MCP server to unregister
        """
        from app.config.loggers import common_logger as logger

        category_name = f"mcp_{server_name}"

        if category_name in self._categories:
            del self._categories[category_name]
            logger.info(f"Unregistered MCP server category: {category_name}")

        # Clean up tool mappings
        tools_to_remove = [
            tool_name
            for tool_name, srv_name in self._mcp_categories.items()
            if srv_name == server_name
        ]
        for tool_name in tools_to_remove:
            del self._mcp_categories[tool_name]

    def get_mcp_server_for_tool(self, tool_name: str) -> Optional[str]:
        """
        Get the MCP server name for a specific tool.

        Args:
            tool_name: Name of the tool

        Returns:
            MCP server name or None if not an MCP tool
        """
        return self._mcp_categories.get(tool_name)


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
    auto_initialize=False,
)
async def init_tool_registry():
    tool_registry = ToolRegistry()
    await tool_registry.setup()
    return tool_registry
