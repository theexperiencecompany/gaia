import asyncio
from collections import defaultdict
from collections.abc import ItemsView, Iterator, KeysView, Mapping

from langchain_core.tools import BaseTool

from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from app.helpers.namespace_utils import derive_integration_namespace
from app.models.oauth_models import OAuthIntegration
from app.services.composio.composio_service import get_composio_service
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.mcp.mcp_tools_store import get_mcp_tools_store
from shared.py.wide_events import log


class DynamicToolDict(Mapping[str, BaseTool]):
    """
    A dict-like wrapper that provides live access to the tool registry.

    This allows tools added to the registry after graph compilation
    to be accessible to the agent.
    """

    def __init__(self, registry: "ToolRegistry"):
        self._registry = registry
        self._extra_tools: dict[str, BaseTool] = {}

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
            set(self._extra_tools.keys()) | set(self._registry._get_tool_dict_internal().keys())
        )

    def __contains__(self, key: object) -> bool:
        return key in self._extra_tools or key in self._registry._get_tool_dict_internal()

    def update(self, other: dict[str, BaseTool]) -> None:
        """Add extra tools (like handoff) that aren't in the registry."""
        self._extra_tools.update(other)

    def values(self):
        """Return all tool values for ToolNode initialization."""
        all_tools = dict(self._registry._get_tool_dict_internal())
        all_tools.update(self._extra_tools)
        return all_tools.values()

    def keys(self) -> KeysView[str]:
        """Return all tool names (registry + extras) as a KeysView."""
        all_tools = dict(self._registry._get_tool_dict_internal())
        all_tools.update(self._extra_tools)
        return all_tools.keys()

    def items(self) -> ItemsView[str, BaseTool]:
        """Return all (name, tool) pairs from the registry plus extras."""
        all_tools = dict(self._registry._get_tool_dict_internal())
        all_tools.update(self._extra_tools)
        return all_tools.items()


class _CatalogToolMeta:
    """Lightweight provider-tool metadata (name + description) used to index the
    Composio catalog at warmup *without* materializing a StructuredTool.

    Duck-types the ``.name``/``.description`` access that ``index_tools_to_store``
    needs, so it flows through the existing ChromaDB indexing path. The executable
    StructuredTool is built lazily, per provider, in ``register_provider_tools``
    when that provider's subagent is first created.
    """

    __slots__ = ("description", "name")

    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description


class Tool:
    """Simplified tool object that holds individual tool metadata."""

    def __init__(
        self,
        tool: BaseTool,
        name: str | None = None,
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
        integration_name: str | None = None,
        is_delegated: bool = False,
    ):
        self.name = name
        self.space = space
        self.require_integration = require_integration
        self.integration_name = integration_name
        self.is_delegated = is_delegated
        self.tools: list[Tool] = []

    def add_tool(self, tool: BaseTool, is_core: bool = False, name: str | None = None):
        """Add a tool to this category."""
        self.tools.append(Tool(tool=tool, name=name, is_core=is_core))

    def add_tools(self, tools: list[BaseTool], is_core: bool = False):
        """Add multiple tools to this category."""
        for tool in tools:
            self.add_tool(tool, is_core=is_core)

    def get_tool_objects(self) -> list[BaseTool]:
        """Get the actual tool objects for binding."""
        return [tool.tool for tool in self.tools]

    def get_core_tools(self) -> list[Tool]:
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
        self._categories: dict[str, ToolCategory] = {}
        self._user_mcp_categories: dict[str, set[str]] = defaultdict(set)

    async def setup(self):
        self._initialize_categories()

    def _add_category(
        self,
        name: str,
        tools: list[BaseTool] | None = None,
        core_tools: list[BaseTool] | None = None,
        space: str = "general",
        require_integration: bool = False,
        integration_name: str | None = None,
        is_delegated: bool = False,
    ):
        """Helper to create and register a category."""
        replacing = name in self._categories
        prior_tools_count = len(self._categories[name].tools) if replacing else 0
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
        log.set(
            tool_category={
                "name": name,
                "space": space,
                "tools_in": len(tools) if tools else 0,
                "core_tools_in": len(core_tools) if core_tools else 0,
                "final_count": len(category.tools),
                "replacing": replacing,
                "prior_tools_count": prior_tools_count,
            }
        )
        log.info(
            f"_add_category: '{name}' space='{space}' tools_in="
            f"{len(tools) if tools else 0} core_in="
            f"{len(core_tools) if core_tools else 0} final="
            f"{len(category.tools)} replacing={replacing} (was {prior_tools_count})"
        )

    def _initialize_categories(self):
        """Initialize core tool categories. Provider tools are loaded lazily."""

        # NOTE: Import tool modules lazily to avoid circular imports during app startup.
        from app.agents.tools import (
            code_exec_tool,
            context_tool,
            document_tool,
            file_tools,
            finish_task_tool,
            flowchart_tool,
            goal_tool,
            image_tool,
            integration_tool,
            memory_tools,
            notification_tool,
            reminder_tool,
            research_tool,
            skill_tools,
            support_tool,
            todo_tool,
            tracked_todo_tools,
            vfs_tools,
            weather_tool,
            webpage_tool,
            workflow_tool,
        )

        self._add_category(
            "search",
            tools=[
                webpage_tool.web_search_tool,
                webpage_tool.fetch_webpages,
                research_tool.deep_research,
            ],
        )

        self._add_category(
            "documents",
            tools=[file_tools.query_file, document_tool.generate_document],
        )

        self._add_category("notifications", tools=[*notification_tool.tools])
        self._add_category(
            "tracked_todos",
            tools=[*tracked_todo_tools.tools],
            space="tasks",
        )
        self._add_category(
            "todos",
            tools=[*todo_tool.tools],
            is_delegated=True,
            integration_name="todos",
            space="todos",
        )
        self._add_category(
            "reminders",
            tools=[*reminder_tool.tools],
            is_delegated=True,
            integration_name="reminders",
            space="reminders",
        )
        self._add_category(
            "goal_tracking",
            tools=goal_tool.tools,
            is_delegated=True,
            integration_name="goals",
            space="goals",
        )
        self._add_category(
            "skills",
            tools=skill_tools.tools,
            is_delegated=True,
            integration_name="skills",
            space="skills",
        )

        # General tools - directly accessible by executor
        self._add_category("workflows", tools=workflow_tool.tools)
        self._add_category("control", tools=[finish_task_tool.finish_task])
        self._add_category("support", tools=[support_tool.create_support_ticket])
        self._add_category("memory", tools=memory_tools.tools)
        self._add_category("filesystem", tools=vfs_tools.tools)
        self._add_category("integrations", tools=integration_tool.tools)
        self._add_category(
            "development",
            tools=[code_exec_tool.execute_code, flowchart_tool.create_flowchart],
        )
        self._add_category("creative", tools=[image_tool.generate_image])
        self._add_category("weather", tools=[weather_tool.get_weather])
        self._add_category("context", tools=[context_tool.gather_context])

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

        log.info(f"Registering provider tools for {toolkit_name} (space: {space_name})")

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

        log.info(f"Registered {len(tools)} tools for {toolkit_name}")
        return self._categories[toolkit_name]

    async def load_all_provider_tools(self):
        """
        Load all provider tools from OAuth integrations.
        This method loads tools for all integrations managed by composio
        that have subagent configurations and syncs them to the store.
        Tools are loaded in parallel for better performance.
        """

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
                log.error(f"Failed to load provider tools for {toolkit_name}: {e}")

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

    async def populate_provider_catalog(self) -> int:
        """Index provider-tool METADATA for retrieval and the /tools catalog
        *without* materializing executable StructuredTools.

        This replaces the old eager ``load_all_provider_tools()`` warmup path,
        which wrapped every one of the ~1.6k catalog tools into a StructuredTool
        (a Pydantic args-model + closure per tool, ~100KB each) and kept them
        resident for the whole process lifetime — the single largest contributor
        to backend RSS. Here we only:

          1. fetch raw tool metadata (name + description) per toolkit,
          2. index name+description into ChromaDB so retrieval works, and
          3. store name+description in Mongo so the /tools listing is complete.

        Executable tools are built lazily, per provider, when that provider's
        subagent is first created (``register_provider_tools``), so a process
        only ever holds the working set of tools it actually uses.
        """
        # index_tools_to_store lives in chroma_tools_store, which imports
        # get_tool_registry from this module — keep this one local to break the
        # import cycle (see _index_category_tools below).
        from app.db.chroma.chroma_tools_store import index_tools_to_store

        composio_service = get_composio_service()
        mcp_store = get_mcp_tools_store()

        integrations = [
            integration
            for integration in OAUTH_INTEGRATIONS
            if (
                integration.managed_by == "composio"
                and integration.composio_config
                and integration.subagent_config
                and integration.subagent_config.has_subagent
            )
        ]

        mongo_batch: list[tuple[str, list[dict]]] = []
        total = 0

        async def load_metadata(integration: OAuthIntegration) -> None:
            nonlocal total
            toolkit = integration.composio_config.toolkit
            space = integration.subagent_config.tool_space
            specific = integration.subagent_config.specific_tools
            try:
                raw_tools = await composio_service.get_raw_tools_metadata(
                    tool_kit=toolkit, specific_tools=specific
                )
            except Exception as e:
                log.error(f"Failed to load catalog metadata for {toolkit}: {e}")
                return

            metas = [
                _CatalogToolMeta(name=t.slug, description=getattr(t, "description", "") or "")
                for t in raw_tools
            ]
            if not metas:
                return

            # Reuse the existing indexing path; it only reads .name/.description
            # and is idempotent via the ChromaDB diff + Redis hash cache, so the
            # later per-provider register_provider_tools re-index is a no-op.
            try:
                await index_tools_to_store([(m, space) for m in metas])
            except Exception as e:
                log.error(f"Failed to index catalog metadata for {toolkit}: {e}")
                return

            mongo_batch.append(
                (
                    toolkit.lower(),
                    [{"name": m.name, "description": m.description} for m in metas],
                )
            )
            total += len(metas)

        # return_exceptions so one toolkit's failure can't abort the whole
        # population run and leave the catalog half-indexed.
        results = await asyncio.gather(
            *[load_metadata(i) for i in integrations], return_exceptions=True
        )
        for integration, result in zip(integrations, results):
            if isinstance(result, Exception):
                log.error(
                    "Catalog metadata population failed for "
                    f"{integration.composio_config.toolkit}: {result}"
                )

        if mongo_batch:
            try:
                await mcp_store.store_tools_batch(mongo_batch)
            except Exception as e:
                log.warning(f"Failed to store provider catalog metadata to Mongo: {e}")

        log.info(
            f"Provider catalog metadata indexed: {total} tools "
            f"across {len(integrations)} toolkits (no StructuredTools materialized)"
        )
        return total

    async def _index_category_tools(self, category_name: str):
        """Index tools from a category into ChromaDB store.

        Delegates all caching and diff logic to index_tools_to_store(),
        which uses namespace-based cache keys for consistency.

        All tools in a category share the same `space` (namespace) by design —
        _add_category assigns a single space to the entire category, so
        index_tools_to_store always receives a homogeneous list.
        """
        # Import here to avoid circular import
        from app.db.chroma.chroma_tools_store import index_tools_to_store

        category = self._categories.get(category_name)
        if not category:
            log.warning(
                f"_index_category_tools: category '{category_name}' not in registry, "
                f"known={sorted(self._categories.keys())[:20]}..."
            )
            return

        category_tools_count = len(category.tools)
        log.set(
            tool_index={
                "category": category_name,
                "space": category.space,
                "category_tools_count": category_tools_count,
            }
        )
        log.info(
            f"_index_category_tools: '{category_name}' space='{category.space}' "
            f"category.tools count={category_tools_count}"
        )

        tools_with_space = [(tool.tool, category.space) for tool in category.tools]
        if not tools_with_space:
            log.warning(
                f"_index_category_tools: category '{category_name}' has 0 tools "
                f"(space='{category.space}'), nothing to index — caller likely passed "
                f"empty tools to _add_category"
            )
            return

        await index_tools_to_store(tools_with_space)

    def get_category(self, name: str) -> ToolCategory | None:
        """Get a specific category by name."""
        return self._categories.get(name)

    def get_category_by_space(self, space: str) -> ToolCategory | None:
        """Get a category by its tool space value.

        Searches all categories and returns the first one where category.space matches.
        This handles dynamic category names like mcp_{integration}_{user_id}.
        """
        for category in self._categories.values():
            if category.space == space:
                return category
        return None

    def get_all_category_objects(
        self, ignore_categories: list[str] = []
    ) -> dict[str, ToolCategory]:
        """Get all categories as ToolCategory objects."""
        return {
            name: category
            for name, category in self._categories.items()
            if name not in ignore_categories
        }

    async def load_user_mcp_tools(self, user_id: str) -> dict[str, list[BaseTool]]:
        """
        Load all connected MCP tools for a specific user.

        Connects to each MCP server the user has authenticated with,
        retrieves tools, and adds them to the registry.

        Category naming: mcp_{integration_id} (without user_id)
        User association is tracked via _user_mcp_categories.

        Returns dict mapping integration_id -> list of tools loaded.
        """
        from app.config.oauth_config import get_integration_by_id
        from app.services.mcp.mcp_client import get_mcp_client

        mcp_client = await get_mcp_client(user_id=user_id)
        all_tools = await mcp_client.get_all_connected_tools()

        log.set(
            load_user_mcp_tools={
                "user_id": user_id,
                "integration_count": len(all_tools),
                "integrations": list(all_tools.keys()),
                "tool_counts": {iid: len(t) for iid, t in all_tools.items()},
            }
        )
        log.info(
            f"load_user_mcp_tools: user={user_id} got {len(all_tools)} integrations "
            f"with counts={ {iid: len(t) for iid, t in all_tools.items()} }"
        )

        loaded: dict[str, list[BaseTool]] = {}

        for integration_id, tools in all_tools.items():
            if not tools:
                log.warning(
                    f"load_user_mcp_tools: integration_id={integration_id} has empty "
                    f"tools list, skipping"
                )
                continue

            # Category name: mcp_{integration_id} (no user_id suffix)
            category_name = f"mcp_{integration_id}"

            # Track this category for the user
            self._user_mcp_categories[user_id].add(category_name)

            # Skip if already loaded (category already exists)
            if category_name in self._categories:
                existing_count = len(self._categories[category_name].tools)
                log.info(
                    f"load_user_mcp_tools: '{category_name}' already in registry "
                    f"(category.tools={existing_count} from earlier load), "
                    f"skipping re-add for user {user_id}"
                )
                loaded[integration_id] = tools
                continue

            # Get space from integration config
            integration = get_integration_by_id(integration_id)
            space = integration_id  # Default: unique namespace per integration
            has_subagent = False
            if integration and integration.subagent_config:
                space = integration.subagent_config.tool_space
                has_subagent = integration.subagent_config.has_subagent
            else:
                server_url = await IntegrationResolver.get_server_url(integration_id)
                space = derive_integration_namespace(integration_id, server_url, is_custom=True)

            self._add_category(
                name=category_name,
                tools=tools,
                space=space,
                integration_name=integration_id,
                is_delegated=has_subagent,
            )
            await self._index_category_tools(category_name)
            loaded[integration_id] = tools
            log.info(f"Loaded {len(tools)} MCP tools from {integration_id} for user {user_id}")

        return loaded

    def get_category_of_tool(self, tool_name: str) -> str:
        """Get the category of a specific tool by name."""
        for category in self._categories.values():
            for tool in category.tools:
                if tool.name == tool_name:
                    return category.name
        return "unknown"

    def get_all_tools_for_search(self, include_delegated: bool = True) -> list[Tool]:
        """
        Get all tool objects for semantic search (includes delegated tools).

        Returns:
            List of Tool objects for semantic search.
        """
        tools: list[Tool] = []
        for category in self._categories.values():
            if category.is_delegated and not include_delegated:
                continue
            tools.extend(category.tools)
        return tools

    def get_core_tools(self) -> list[Tool]:
        """
        Get all core tools across all categories.

        Returns:
            List of core Tool objects.
        """
        core_tools = []
        for category in self._categories.values():
            core_tools.extend(category.get_core_tools())
        return core_tools

    def get_core_categories(self) -> list[ToolCategory]:
        """
        Get all core categories (those that don't require integration).

        Core categories are the built-in tool categories that are always
        available, as opposed to integration-specific categories that
        require user authentication.

        Returns:
            List of core ToolCategory objects.
        """
        return [
            category for category in self._categories.values() if not category.require_integration
        ]

    def _get_tool_dict_internal(self) -> dict[str, BaseTool]:
        """Internal method to get current tool dict (used by DynamicToolDict)."""
        all_tools = self.get_all_tools_for_search()
        return {tool.name: tool.tool for tool in all_tools}

    def get_tool_dict(self) -> DynamicToolDict:
        """Get a dynamic dictionary mapping tool names to tool instances for agent binding.

        Returns a DynamicToolDict that provides live access to tools,
        allowing tools added after graph compilation to be accessible.
        """
        return DynamicToolDict(self)

    def get_tool_names(self) -> list[str]:
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
