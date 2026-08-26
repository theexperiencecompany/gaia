import asyncio
from collections.abc import ItemsView, Iterator, KeysView, Mapping, Sequence, ValuesView
from typing import cast

from langchain_core.tools import BaseTool

from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.constants.log_tags import LogTag
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from app.models.oauth_models import OAuthIntegration
from app.services.composio.composio_service import get_composio_service
from app.services.mcp.mcp_tools_service import RawToolMetadata, store_mcp_tools_batch
from shared.py.wide_events import log

# Desktop-executed tools (screenshot, clipboard, ...) — discovery and binding
# are gated to desktop-app conversations in retrieval.py.
DESKTOP_TOOL_CATEGORY: str = "desktop"
DESKTOP_TOOL_SPACE: str = "desktop"


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

    def values(self) -> ValuesView[BaseTool]:
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
        destructive: bool | None = None,
        always_gate: bool = False,
    ):
        self.tool = tool
        self.name = name or tool.name
        self.is_core = is_core
        # HIL destructive flag — the single source of truth for tool risk.
        # None = unclassified (custom/MCP tools until the LLM classifier decides);
        # True/False = reviewed (internal tools + curated integration slugs).
        self.destructive = destructive
        # Forced-ask stamp: this tool pauses for user approval in EVERY HIL mode,
        # ignoring ``always_allow`` and per-tool overrides. Stronger than
        # ``destructive`` (which only shapes auto-mode judging). For settings on
        # the user's own account and similar product invariants.
        self.always_gate = always_gate


class ToolCategory:
    """Category that holds tools and category-level metadata."""

    def __init__(
        self,
        name: str,
        space: str = "general",
        require_integration: bool = False,
        integration_name: str | None = None,
        is_delegated: bool = False,
        internal: bool = False,
    ):
        self.name = name
        self.space = space
        # True for integration-specific categories (Composio toolkits) that need
        # the user to have connected that integration; core built-in categories
        # leave it False. `get_core_categories` filters on this flag.
        self.require_integration = require_integration
        self.integration_name = integration_name
        self.is_delegated = is_delegated
        # Internal categories hold agent-only plumbing tools (sandbox, control
        # flow, instruction loading) that must never surface in the user-facing
        # tool/slash-command listings, but stay available to the executor.
        self.internal = internal
        self.tools: list[Tool] = []

    def add_tool(
        self,
        tool: BaseTool,
        is_core: bool = False,
        name: str | None = None,
        destructive: bool | None = None,
        always_gate: bool = False,
    ) -> None:
        """Add a tool to this category."""
        self.tools.append(
            Tool(
                tool=tool,
                name=name,
                is_core=is_core,
                destructive=destructive,
                always_gate=always_gate,
            )
        )

    def add_tools(
        self,
        tools: Sequence[BaseTool],
        is_core: bool = False,
        destructive_tools: set[str] | None = None,
        always_gate_tools: set[str] | None = None,
    ) -> None:
        """Add multiple tools to this category.

        ``destructive_tools`` is a curated set of tool names: when provided,
        every tool is stamped destructive by membership (so an empty set marks
        the whole category reviewed-safe); when ``None`` the tools stay
        unclassified and fall to the HIL LLM classifier at gate time.
        ``always_gate_tools`` stamps forced-ask members (see ``Tool.always_gate``).
        """
        gated = always_gate_tools or set()
        for tool in tools:
            destructive = None if destructive_tools is None else (tool.name in destructive_tools)
            self.add_tool(
                tool, is_core=is_core, destructive=destructive, always_gate=tool.name in gated
            )

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
        # name -> (category_name, Tool) index. Tool names are globally unique
        # (the executor's tool dict is keyed by name), so a flat map is safe;
        # it serves the per-tool-call lookups on the HIL gate path without
        # scanning every category.
        self._tools_by_name: dict[str, tuple[str, Tool]] = {}

    def setup(self) -> None:
        self._initialize_categories()

    def _add_category(
        self,
        name: str,
        tools: Sequence[BaseTool] | None = None,
        core_tools: Sequence[BaseTool] | None = None,
        space: str = "general",
        require_integration: bool = False,
        integration_name: str | None = None,
        is_delegated: bool = False,
        internal: bool = False,
        destructive_tools: set[str] | None = None,
        always_gate_tools: set[str] | None = None,
    ) -> None:
        """Helper to create and register a category.

        ``destructive_tools`` is the curated HIL risk set for this category
        (see ``ToolCategory.add_tools``). Every internal category MUST pass an
        explicit set (empty if none are destructive) so in-repo tools are never
        left unclassified; ``None`` is reserved for uncurated (custom MCP /
        provider) tools that the HIL LLM classifier resolves at gate time.
        ``always_gate_tools`` names members that ask in every HIL mode.
        """
        replacing = name in self._categories
        prior_tools_count = len(self._categories[name].tools) if replacing else 0
        category = ToolCategory(
            name=name,
            space=space,
            require_integration=require_integration,
            integration_name=integration_name,
            is_delegated=is_delegated,
            internal=internal,
        )
        if core_tools:
            category.add_tools(
                core_tools,
                is_core=True,
                destructive_tools=destructive_tools,
                always_gate_tools=always_gate_tools,
            )
        if tools:
            category.add_tools(
                tools, destructive_tools=destructive_tools, always_gate_tools=always_gate_tools
            )
        self._categories[name] = category
        if replacing:
            # Drop the replaced category's entries so removed tools don't linger.
            self._tools_by_name = {k: v for k, v in self._tools_by_name.items() if v[0] != name}
        for registered in category.tools:
            self._tools_by_name[registered.name] = (name, registered)
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
            f"{LogTag.TOOL} _add_category",
            category_name=name,
            space=space,
            tools_in=len(tools) if tools else 0,
            core_in=len(core_tools) if core_tools else 0,
            final=len(category.tools),
            replacing=replacing,
            prior_tools_count=prior_tools_count,
        )

    def _initialize_categories(self) -> None:
        """Initialize core tool categories. Provider tools are loaded lazily.

        HIL INVARIANT: every internal category passes an explicit
        ``destructive_tools`` set (empty when none are destructive) so no in-repo
        tool is ever left unclassified. The three destructive built-ins are
        code-reviewed: ``send_notification`` (external delivery),
        ``execute_workflow`` (autonomous run-now), ``connect_integration``
        (connects an external account). Everything else is reversible /
        user-owned / read-only / sandbox-local and therefore safe.
        """

        # NOTE: Import tool modules lazily to avoid circular imports during app startup.
        from app.agents.tools import (
            account_tools,
            context_tool,
            desktop_tools,
            download_tool,
            file_tools,
            finish_task_tool,
            flowchart_tool,
            image_tool,
            integration_instructions_tools,
            integration_tool,
            manual_tool,
            memory_tools,
            notification_tool,
            reminder_tool,
            research_tool,
            skill_tools,
            subscription_tool,
            support_tool,
            todo_tool,
            tracked_todo_tools,
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
                *download_tool.tools,
            ],
            destructive_tools=set(),
        )

        self._add_category(
            "documents",
            tools=[file_tools.search_uploaded_files],
            destructive_tools=set(),
        )

        self._add_category(
            "notifications",
            tools=[*notification_tool.tools],
            destructive_tools={"send_notification"},
        )
        # Account-center mutations: settings on the user's own account. The
        # settings tools are forced-ask — they change state the user owns
        # outright, so no approval mode or per-tool override may wave them
        # through. manage_linked_account is argument-gated instead (disconnect
        # asks, generate_link doesn't) — see hil/policy.ARGUMENT_GATED_TOOLS.
        self._add_category(
            "account",
            tools=[*account_tools.tools],
            destructive_tools=set(),
            always_gate_tools={
                "update_notification_settings",
                "update_preferences",
                "update_custom_instructions",
                "set_selected_voice",
            },
        )  # pragma: no mutate -- closing paren is whitespace-only (AST-equivalent)
        self._add_category(
            "tracked_todos",
            tools=[*tracked_todo_tools.tools],
            space="tasks",
            destructive_tools=set(),
        )
        self._add_category(
            "todos",
            tools=[*todo_tool.tools],
            is_delegated=True,
            integration_name="todos",
            space="todos",
            destructive_tools=set(),
        )
        self._add_category(
            "reminders",
            tools=[*reminder_tool.tools],
            is_delegated=True,
            integration_name="reminders",
            space="reminders",
            destructive_tools=set(),
        )
        self._add_category(
            "skills",
            tools=skill_tools.tools,
            is_delegated=True,
            integration_name="skills",
            space="skills",
            destructive_tools=set(),
        )

        # General tools - directly accessible by executor
        self._add_category(
            "workflows",
            tools=workflow_tool.tools,
            destructive_tools={"execute_workflow"},
        )
        self._add_category(
            "control",
            tools=[finish_task_tool.finish_task],
            internal=True,
            destructive_tools=set(),
        )
        self._add_category(
            "support",
            tools=[support_tool.create_support_ticket],
            destructive_tools=set(),
        )
        # A checkout link is inert until the user chooses to pay it, so nothing
        # here is destructive — gating "show me how to upgrade" behind an
        # approval prompt would be absurd.
        self._add_category("billing", tools=[*subscription_tool.tools], destructive_tools=set())
        self._add_category("manual", tools=[*manual_tool.tools], destructive_tools=set())
        self._add_category("memory", tools=memory_tools.tools, destructive_tools=set())
        self._add_category(
            "integrations",
            tools=integration_tool.tools,
            destructive_tools={"connect_integration"},
        )
        self._add_category(
            "integration_instructions",
            tools=[*integration_instructions_tools.tools],
            internal=True,
            destructive_tools=set(),
        )
        from app.agents.tools import coding

        # Sandbox coding tools (bash/read/write/edit) are agent-only plumbing
        # that act only inside the user's isolated sandbox.
        self._add_category(
            "development", tools=[*coding.tools], internal=True, destructive_tools=set()
        )
        self._add_category(
            "creative",
            tools=[image_tool.generate_image, flowchart_tool.create_flowchart],
            destructive_tools=set(),
        )
        self._add_category("weather", tools=[weather_tool.get_weather], destructive_tools=set())
        self._add_category("context", tools=[context_tool.gather_context], destructive_tools=set())
        # Desktop-executed tools live in their own space so discovery can be
        # gated to conversations that originate from the desktop app. They act on
        # the user's own machine and are reversible, so none are destructive.
        self._add_category(
            DESKTOP_TOOL_CATEGORY,
            tools=[*desktop_tools.tools],
            space=DESKTOP_TOOL_SPACE,
            destructive_tools=set(),
        )

    async def register_provider_tools(
        self,
        toolkit_name: str,
        space_name: str,
        specific_tools: list[str] | None = None,
        exclude_tools: list[str] | None = None,
    ) -> ToolCategory:
        """
        Register provider tools on-demand when subagent is created.
        Tools are loaded from Composio and indexed in ChromaDB.
        """
        if toolkit_name in self._categories:
            return self._categories[toolkit_name]

        log.info(
            f"{LogTag.TOOL} Registering provider tools",
            toolkit_name=toolkit_name,
            space_name=space_name,
        )

        composio_service = get_composio_service()

        if specific_tools:
            tools = await composio_service.get_tools_by_name(specific_tools)
            if exclude_tools:
                tools = [t for t in tools if t.name not in exclude_tools]
        else:
            tools = await composio_service.get_tools(
                tool_kit=toolkit_name, exclude_tools=exclude_tools
            )

        self._add_category(
            name=toolkit_name,
            tools=tools,
            require_integration=True,
            integration_name=toolkit_name,
            is_delegated=True,
            space=space_name,
            destructive_tools=integration_destructive_tools(toolkit_name),
        )

        await self._index_category_tools(toolkit_name)

        log.info(
            f"{LogTag.TOOL} Registered tools for toolkit",
            tool_count=len(tools),
            toolkit_name=toolkit_name,
        )
        return self._categories[toolkit_name]

    async def populate_provider_catalog(self) -> int:
        """Index provider-tool METADATA for retrieval and the /tools catalog
        *without* materializing executable StructuredTools.

        Replaces an eager warmup that wrapped every one of the ~1.6k catalog
        tools into a StructuredTool (a Pydantic args-model + closure per tool,
        ~100KB each) and kept them resident for the whole process lifetime —
        the single largest contributor to backend RSS. Here we only:

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

        mongo_batch: list[tuple[str, list[RawToolMetadata]]] = []
        total = 0

        async def load_metadata(integration: OAuthIntegration) -> None:
            nonlocal total
            toolkit = integration.composio_config.toolkit
            space = integration.subagent_config.tool_space
            specific = integration.subagent_config.specific_tools
            exclude = set(integration.subagent_config.exclude_tools or [])
            try:
                raw_tools = await composio_service.get_raw_tools_metadata(
                    tool_kit=toolkit, specific_tools=specific
                )
            except Exception as e:
                log.error(
                    f"{LogTag.TOOL} Failed to load catalog metadata",
                    toolkit=toolkit,
                    error_type=type(e).__name__,
                )
                return

            metas = [
                _CatalogToolMeta(name=t.slug, description=getattr(t, "description", "") or "")
                for t in raw_tools
                if t.slug not in exclude
            ]
            if not metas:
                return

            # Reuse the existing indexing path; it only reads .name/.description
            # and is idempotent via the ChromaDB diff + Redis hash cache, so the
            # later per-provider register_provider_tools re-index is a no-op.
            try:
                await index_tools_to_store([(m, space) for m in metas])
            except Exception as e:
                log.error(
                    f"{LogTag.TOOL} Failed to index catalog metadata",
                    toolkit=toolkit,
                    error_type=type(e).__name__,
                )
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
                    f"{LogTag.TOOL} Catalog metadata population failed",
                    toolkit=integration.composio_config.toolkit,
                    error_type=type(result).__name__,
                )

        if mongo_batch:
            try:
                await store_mcp_tools_batch(mongo_batch)
            except Exception as e:
                log.warning(
                    f"{LogTag.TOOL} Failed to store provider catalog metadata to Mongo",
                    error_type=type(e).__name__,
                )

        log.info(
            f"{LogTag.TOOL} Provider catalog metadata indexed (no StructuredTools materialized)",
            tool_count=total,
            toolkit_count=len(integrations),
        )
        return total

    async def _index_category_tools(self, category_name: str) -> None:
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
                f"{LogTag.TOOL} _index_category_tools: category not in registry",
                category_name=category_name,
                known_categories=sorted(self._categories.keys())[:20],
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
            f"{LogTag.TOOL} _index_category_tools",
            category_name=category_name,
            space=category.space,
            category_tools_count=category_tools_count,
        )

        tools_with_space = [(tool.tool, category.space) for tool in category.tools]
        if not tools_with_space:
            log.warning(
                f"{LogTag.TOOL} _index_category_tools: category has 0 tools, nothing to index — caller likely passed empty tools to _add_category",
                category_name=category_name,
                space=category.space,
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
        self, ignore_categories: list[str] | None = None
    ) -> dict[str, ToolCategory]:
        """Get all categories as ToolCategory objects."""
        ignore_categories = ignore_categories or []
        return {
            name: category
            for name, category in self._categories.items()
            if name not in ignore_categories
        }

    def get_category_of_tool(self, tool_name: str) -> str:
        """Get the category of a specific tool by name."""
        entry = self._tools_by_name.get(tool_name)
        return entry[0] if entry else "unknown"

    def get_tool_meta(self, tool_name: str) -> Tool | None:
        """Return the registry ``Tool`` wrapper for a tool name, or None.

        Served from the name index — this sits on the HIL gate's per-tool-call
        path, where a scan over every category × tool is measurable waste.
        """
        entry = self._tools_by_name.get(tool_name)
        return entry[1] if entry else None

    def is_tool_destructive(self, tool_name: str) -> bool | None:
        """HIL risk flag for a tool: True/False if reviewed, None if unclassified
        or absent from the registry."""
        meta = self.get_tool_meta(tool_name)
        return meta.destructive if meta else None

    def mark_tool_destructive(self, tool_name: str, value: bool) -> None:
        """Write an LLM classification back onto the live registry (custom tools)."""
        meta = self.get_tool_meta(tool_name)
        if meta is not None:
            meta.destructive = value

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


def integration_destructive_tools(name: str) -> set[str] | None:
    """Curated HIL destructive tools for an integration, matched by id or (for
    Composio) toolkit. ``None`` (uncurated) leaves the tools unclassified so the
    HIL LLM classifier resolves them at gate time (fail closed)."""
    for integration in OAUTH_INTEGRATIONS:
        toolkit = integration.composio_config.toolkit if integration.composio_config else None
        if integration.id == name or (toolkit and toolkit.lower() == name.lower()):
            return (
                None
                if integration.destructive_tools is None
                else set(integration.destructive_tools)
            )
    return None


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

    # providers.aget declares -> Any | None; init_tool_registry (below) always
    # registers a real ToolRegistry instance under this provider name.
    return cast(ToolRegistry, tool_registry)


@lazy_provider(
    name="tool_registry",
    required_keys=[],
    strategy=MissingKeyStrategy.ERROR,
    auto_initialize=True,
)
async def init_tool_registry() -> ToolRegistry:
    tool_registry = ToolRegistry()
    tool_registry.setup()
    return tool_registry
