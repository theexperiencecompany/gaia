import asyncio
from typing import Annotated, Awaitable, Callable, Optional, TypedDict

from langgraph.prebuilt import InjectedStore
from langgraph.store.base import BaseStore


class RetrieveToolsResult(TypedDict):
    """Result from retrieve_tools function.

    Attributes:
        tools_to_bind: Tool IDs to actually bind to the model (for execution)
        response: Tool names/info to return to the agent (for display)
    """

    tools_to_bind: list[str]
    response: list[str]


def get_retrieve_tools_function(
    tool_space: str = "general",
    include_subagents: bool = True,
    limit: int = 25,
) -> Callable[..., Awaitable[RetrieveToolsResult]]:
    """Get a retrieve_tools function configured for specific context.

    This unified function handles both tool discovery (semantic search) and tool binding.
    - When `query` is provided: Returns tool names for discovery (not bound)
    - When `exact_tool_names` is provided: Binds and returns validated tool names

    Args:
        tool_space: Namespace to search for tools
        include_subagents: Whether to include subagent results in search
        limit: Maximum number of tool results for semantic search

    Returns:
        Configured retrieve_tools coroutine that returns RetrieveToolsResult
    """

    async def retrieve_tools(
        store: Annotated[BaseStore, InjectedStore],
        query: Optional[str] = None,
        exact_tool_names: Optional[list[str]] = None,
    ) -> RetrieveToolsResult:
        """Discover available tools or load specific tools by exact name.

        This is your primary interface to the tool ecosystem. It supports TWO modes:

        --------------------------------
        DISCOVERY MODE (query)
        --------------------------------
        Use natural language to semantically search for relevant tools.

        IMPORTANT BEHAVIOR:
        - Discovery results are LIMITED and NOT exhaustive
        - Not all relevant tools may be returned in a single query
        - Absence of a tool in results does NOT mean it does not exist
        - You are expected to retry with different wording if needed

        You may:
        - Rephrase queries
        - Try broader or narrower intent
        - Use multiple intents in a single query (comma-separated)

        Examples of valid queries:
        - "send email"
        - "email operations"
        - "send email, delete draft"
        - "create pull request, list branches"

        The query is semantic, not keyword-based. Comma-separated intents
        are treated as a single semantic search and are encouraged when
        exploring related capabilities.

        Discovery mode ONLY returns tool names. Tools are NOT loaded.

        --------------------------------
        BINDING MODE (exact_tool_names)
        --------------------------------
        Load tools by their exact names.

        - Use this ONLY after discovery or when exact names are already known
        - Invalid or unknown tool names are ignored
        - Successfully validated tools become available for execution

        --------------------------------
        RECOMMENDED WORKFLOW
        --------------------------------
        1. Call retrieve_tools(query="your intent") to discover tools
        2. Review returned tool names
        3. Retry discovery with alternate queries if needed
        4. Call retrieve_tools(exact_tool_names=[...]) to bind tools
        5. Execute bound tools

        --------------------------------
        TOOL NAME FORMATS
        --------------------------------
        - Regular tools: "GMAIL_SEND_DRAFT", "CREATE_TODO"
        - Subagent tools: "subagent:gmail", "subagent:notion"

        Note:
        - Subagent tools require delegation via the `handoff` tool
        - Discovery may return subagents alongside regular tools

        Args:
            query:
                Natural language description of intent for discovery.
                Results are limited and best-effort.
                Retry with different phrasing if needed.

            exact_tool_names:
                Exact tool names to load and bind for execution.

        Returns:
            RetrieveToolsResult with:
            - tools_to_bind: tools that are loaded and executable
            - response: tool names discovered or validated

        """
        from app.agents.tools.core.registry import get_tool_registry

        if not query and not exact_tool_names:
            raise ValueError(
                "Either 'query' (for discovery) or 'exact_tool_names' (for binding) is required."
            )

        tool_registry = await get_tool_registry()
        available_tool_names = tool_registry.get_tool_names()

        # BINDING MODE: Validate and bind exact tool names
        if exact_tool_names:
            validated_tool_names = [
                tool_name
                for tool_name in exact_tool_names
                if tool_name in available_tool_names
            ]
            return RetrieveToolsResult(
                tools_to_bind=validated_tool_names,
                response=validated_tool_names,
            )

        # DISCOVERY MODE: Semantic search for tools
        if include_subagents:
            tool_results, subagent_results = await asyncio.gather(
                store.asearch((tool_space,), query=query, limit=limit),
                store.asearch(("subagents",), query=query, limit=10),
            )
        else:
            tool_results = await store.asearch((tool_space,), query=query, limit=limit)
            subagent_results = []

        all_results = []

        for result in tool_results:
            if result.key in available_tool_names:
                all_results.append({"id": result.key, "score": result.score})

        for result in subagent_results:
            all_results.append({"id": result.key, "score": result.score})

        all_results.sort(key=lambda x: x["score"], reverse=True)

        discovered_tools = [r["id"] for r in all_results]
        return RetrieveToolsResult(
            tools_to_bind=[],
            response=discovered_tools,
        )

    return retrieve_tools
