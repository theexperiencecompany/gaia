from typing import Annotated, Awaitable, Callable

from app.config.oauth_config import OAUTH_INTEGRATIONS
from langchain_core.tools import BaseTool
from langgraph.prebuilt import InjectedStore
from langgraph.store.base import BaseStore


async def map_tools_to_handoff_tools(
    tool_names: list[str], current_tool_space: str = "general"
) -> dict[str, str]:
    """Map tool names to their corresponding handoff tools if they belong to a subagent.

    Args:
        tool_names: List of tool names selected by user
        current_tool_space: The current agent's tool space (default: "general")

    Returns:
        Dict mapping original tool names to handoff tool names.
        Only includes tools that should be delegated (not in current tool space).
    """
    from app.agents.tools.core.registry import get_tool_registry

    tool_registry = await get_tool_registry()
    tool_to_handoff = {}

    # Build mapping of tool_space to handoff_tool_name
    space_to_handoff = {}
    for integration in OAUTH_INTEGRATIONS:
        if integration.subagent_config and integration.subagent_config.has_subagent:
            space = integration.subagent_config.tool_space
            handoff = integration.subagent_config.handoff_tool_name
            space_to_handoff[space] = handoff

    for tool_name in tool_names:
        category_name = tool_registry.get_category_of_tool(tool_name)
        if not category_name:
            continue

        category = tool_registry.get_category(category_name)
        if not category:
            continue

        # Only delegate if tool is delegated AND not in current tool space
        if (
            category.is_delegated
            and category.space != "general"
            and category.space != current_tool_space
        ):
            handoff_tool = space_to_handoff.get(category.space)
            if handoff_tool:
                tool_to_handoff[tool_name] = handoff_tool

    return tool_to_handoff


def get_retrieve_tools_function(
    tool_space: str = "general",
    include_core_tools: bool = True,
    additional_tools: list[BaseTool] = [],
    limit: int = 5,
) -> Callable[..., Awaitable[list[str]]]:
    """
    Get a function to retrieve tools based on a search query.

    Args:
        tool_space: Namespace prefix for the tools.
        exclude_tools: List of tool names to exclude from results.
        include_core_tools: Whether to include core tools in the results.

    Returns:
        A function that retrieves tools based on the provided parameters.
    """

    async def retrieve_tools(
        store: Annotated[BaseStore, InjectedStore],
        query: str = "",
        exclude_tools: list[str] = [],
        exact_tool_names: list[str] = [],
    ) -> list[str]:
        """Retrieve tools to use based on exact tool names or semantic search queries.

        This is your primary tool discovery mechanism. Use this function to find the specific tools
        you need for any task. You must provide either exact_tool_names OR query (or both).

        EXACT TOOL NAMES (PRIMARY METHOD):
        Use this when you know the exact tool name from the system prompt or previous context.
        This is the most direct and reliable method when you're certain of the tool name.

        SEMANTIC SEARCH (FALLBACK METHOD):
        Use natural language queries to describe what you want to accomplish when you don't know
        the exact tool names. The system uses vector similarity to find the most relevant tools
        based on your intent.

        Semantic Query Guidelines:
        • Analyze user's intent: "What is the user trying to accomplish?"
        • Use descriptive, action-oriented queries: "send email", "create calendar event", "search contacts"
        • Try category + action format: "gmail send", "notion create", "twitter post", "calendar view"
        • Use synonyms and related terms if first attempt doesn't work
        • Don't hesitate to call this function multiple times for different functionalities
        • Be persistent - if you know a tool should exist, try different query variations

        Suggested query patterns:
        • Email: "mail send", "gmail compose", "email draft", "contact search"
        • Calendar: "calendar create", "schedule event", "calendar view", "meeting search"
        • Todos: "todo create", "task update", "todo delete", "task search"
        • Notion: "notion create page", "notion database", "notion search", "workspace manage"
        • Twitter: "twitter post", "social media", "tweet create", "twitter search"
        • LinkedIn: "linkedin post", "professional network", "career content"
        • Research: "web search", "deep research", "fetch webpage"
        • Documents: "google docs", "document create", "file generate"
        • Code: "execute code", "run script", "code sandbox"
        • Weather: "weather check", "current weather"
        • Images: "generate image", "create visual"
        • Flowcharts: "create flowchart", "diagram generate"

        Args:
            query: Natural language description of what you want to accomplish.
                   Use when you don't know exact tool names. Use descriptive terms and try
                   different phrasings if initial search fails. Can be empty if using exact_tool_names.
            exclude_tools: List of tool names to exclude from results.
            exact_tool_names: List of EXACT tool names to include directly in results.
                             Use when you know the exact tool name from system prompt STRICTLY.
                             Examples:
                             - "GMAIL_SEND_DRAFT", "GMAIL_CREATE_EMAIL_DRAFT"
                             - "NOTION_CREATE_DATABASE", "NOTION_ADD_PAGE_CONTENT"
                             - "TWITTER_CREATION_OF_A_POST", "TWITTER_USER_LOOKUP_ME"

        Returns:
            List of tool names that match the search criteria.

        Usage Examples:
        • retrieve_tools(exact_tool_names=["GMAIL_SEND_DRAFT"]) - Get specific tool when you know the name
        • retrieve_tools(query="send email") - Find email sending tools when you don't know exact names
        • retrieve_tools(exact_tool_names=["NOTION_SPECIFIC_TOOL"], query="notion database") - Combine both

        Workflow Strategy:
        1. Start with exact_tool_names if you know the precise tool names from system prompt
        2. Fallback to semantic queries when you don't know exact names
        3. Try multiple query variations if first semantic attempt doesn't find expected tools
        4. Retrieve ALL necessary tools before starting task execution
        5. Call this function multiple times for different tool categories as needed
        """
        from app.agents.tools.core.registry import get_tool_registry

        # Validate that at least one search method is provided
        if not query and not exact_tool_names:
            raise ValueError(
                "Must provide either 'query' for semantic search or 'exact_tool_names' for direct tool retrieval"
            )

        # Lazy import to avoid circular dependency

        tool_registry = await get_tool_registry()
        tool_ids = set()

        # Get all available tool names for validation
        available_tool_names = tool_registry.get_tool_names()

        # Search for matching tools based on query (if provided)
        if query:
            results = await store.asearch((tool_space,), query=query, limit=limit)
            # Validate that tools from search results actually exist in registry
            query_tool_ids = [
                result.key for result in results if result.key in available_tool_names
            ]
            tool_ids.update(query_tool_ids)

        if include_core_tools:
            # Filter core tools based on exclusions
            filtered_core_tools = [
                tool
                for tool in tool_registry.get_core_tools()
                if tool.name not in exclude_tools
            ]

            # Core tools are essential tools that should be accessible regardless of semantic search results
            core_tool_ids = [tool.name for tool in filtered_core_tools]

            tool_ids.update(core_tool_ids)

        # Include any additional specified tools (validate they exist)
        if additional_tools:
            additional_tool_ids = [
                tool.name
                for tool in additional_tools
                if tool.name not in exclude_tools and tool.name in available_tool_names
            ]
            tool_ids.update(additional_tool_ids)

        # Add exact tool names if specified (validate they exist in registry)
        if exact_tool_names:
            exact_tool_ids = [
                tool_name
                for tool_name in exact_tool_names
                if tool_name not in exclude_tools
                and tool_name not in tool_ids
                and tool_name in available_tool_names
            ]

            # Replace delegated tools with their handoff tools (unless in same tool_space)
            handoff_replacements = await map_tools_to_handoff_tools(
                exact_tool_ids, current_tool_space=tool_space
            )

            # Add non-delegated tools directly
            for tool_name in exact_tool_ids:
                if tool_name not in handoff_replacements:
                    tool_ids.add(tool_name)

            # Add handoff tools for delegated tools
            tool_ids.update(handoff_replacements.values())
            # tool_ids.update(exact_tool_ids)

        return list(tool_ids)

    return retrieve_tools
