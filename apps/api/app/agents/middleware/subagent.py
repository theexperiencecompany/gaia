"""
SubagentMiddleware - Provides spawn_subagent tool for lightweight parallel task execution.

Spawned subagents run a simple tool-calling loop (no full graph/checkpointer).
When a tool_registry + store are configured, subagents get `retrieve_tools`
for dynamic discovery instead of binding all tools upfront.
"""

from collections.abc import Mapping
from typing import Annotated, Any, Optional

from app.agents.prompts.spawn_subagent_prompts import (
    SPAWN_SUBAGENT_DESCRIPTION,
    SPAWN_SUBAGENT_SYSTEM_PROMPT,
)
from app.agents.tools.core.retrieval import (
    get_retrieve_tools_function,
)
from app.agents.tools.core.tool_runtime_config import ToolRuntimeConfig
from app.config.loggers import app_logger as logger
from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    OmitFromInput,
)
from langchain.tools import InjectedToolCallId
from langchain_core.language_models import LanguageModelLike
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool, tool
from langgraph.prebuilt import InjectedState
from langgraph.store.base import BaseStore
from langgraph.types import Command

_RETRIEVE_TOOLS_NAME = "retrieve_tools"


class SubagentState(AgentState[Any]):
    """State schema for subagent middleware."""

    active_subagents: Annotated[list[str], OmitFromInput]


class SubagentMiddleware(AgentMiddleware[SubagentState, Any]):
    """Middleware that exposes a spawn_subagent tool for focused subtask execution."""

    state_schema = SubagentState

    def __init__(
        self,
        llm: LanguageModelLike | None = None,
        available_tools: list[BaseTool] | None = None,
        tool_registry: Mapping[str, BaseTool] | None = None,
        max_turns: int = 5,
        system_prompt: str = SPAWN_SUBAGENT_SYSTEM_PROMPT,
        excluded_tool_names: set[str] | None = None,
        tool_space: str = "general",
        store: BaseStore | None = None,
        tool_runtime_config: ToolRuntimeConfig | None = None,
    ):
        super().__init__()
        self._llm = llm
        self._available_tools = available_tools or []
        self._tool_registry = tool_registry
        self._max_turns = max_turns
        self._system_prompt = system_prompt
        self._excluded_tools = excluded_tool_names or set()
        self._excluded_tools.add("spawn_subagent")
        self._tool_space = tool_space
        self._store: BaseStore | None = store
        self._tool_runtime_config = (
            tool_runtime_config
            if tool_runtime_config
            else ToolRuntimeConfig(
                initial_tool_names=["vfs_read"],
                enable_retrieve_tools=True,
                include_subagents_in_retrieve=False,
            )
        )

        self.tools = [self._create_spawn_subagent_tool()]

    def _create_spawn_subagent_tool(self):
        middleware = self

        @tool(description=SPAWN_SUBAGENT_DESCRIPTION)
        async def spawn_subagent(
            task: str,
            tool_call_id: Annotated[str, InjectedToolCallId],
            selected_tool_ids: Annotated[list[str], InjectedState("selected_tool_ids")],
            config: RunnableConfig,
            context: str = "",
        ) -> Command[Any]:
            """Spawn a subagent to handle a subtask with focused execution."""
            if middleware._llm is None:
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                content="Error: Subagent LLM not configured",
                                tool_call_id=tool_call_id,
                                status="error",
                            )
                        ]
                    }
                )

            try:
                result = await middleware._execute_subagent(
                    task,
                    context,
                    config,
                    inherited_tool_names=selected_tool_ids,
                )
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                content=result,
                                tool_call_id=tool_call_id,
                            )
                        ]
                    }
                )
            except Exception as e:
                logger.error("Subagent execution failed: {}", str(e))
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                content=f"Subagent error: {str(e)}",
                                tool_call_id=tool_call_id,
                                status="error",
                            )
                        ]
                    }
                )

        return spawn_subagent

    def _build_retrieve_tool(
        self,
        config: RunnableConfig,
    ) -> StructuredTool | None:
        """Build a retrieve_tools StructuredTool with pre-bound store/config.

        Returns None if store is not configured.
        """
        if not self._tool_runtime_config.enable_retrieve_tools or self._store is None:
            return None

        store = self._store
        inner_fn = get_retrieve_tools_function(
            tool_space=self._tool_space,
            include_subagents=self._tool_runtime_config.include_subagents_in_retrieve,
        )

        async def retrieve_tools(
            query: Optional[str] = None,
            exact_tool_names: Optional[list[str]] = None,
        ):
            return await inner_fn(
                store=store,
                config=config,
                query=query,
                exact_tool_names=exact_tool_names,
            )

        retrieve_tools.__doc__ = inner_fn.__doc__

        return StructuredTool.from_function(
            coroutine=retrieve_tools,
            name=_RETRIEVE_TOOLS_NAME,
        )

    def _collect_tools(self) -> list[BaseTool]:
        """Collect all eligible tools from available_tools and tool_registry."""
        tools: list[BaseTool] = []

        for t in self._available_tools:
            if hasattr(t, "name") and t.name not in self._excluded_tools:
                tools.append(t)

        if self._tool_registry:
            for name, registry_tool in self._tool_registry.items():
                if name not in self._excluded_tools:
                    tools.append(registry_tool)

        return tools

    def _bind_tools_from_registry(
        self,
        names: list[str],
        tools_by_name: dict[str, BaseTool],
        bound_tool_names: set[str],
    ) -> list[str]:
        """Resolve tool names from registry into tools_by_name. Returns newly bound names."""
        newly_bound: list[str] = []
        if not self._tool_registry:
            return newly_bound

        for name in names:
            if name in bound_tool_names or name in self._excluded_tools:
                continue
            tool_instance = self._tool_registry.get(name)
            if tool_instance is not None:
                tools_by_name[name] = tool_instance
                bound_tool_names.add(name)
                newly_bound.append(name)

        return newly_bound

    async def _execute_subagent(
        self,
        task: str,
        context: str,
        config: RunnableConfig,
        inherited_tool_names: Optional[list[str]] = None,
    ) -> str:
        """Run a lightweight tool-calling loop for the subagent."""
        if self._llm is None:
            raise ValueError("LLM not configured for subagent execution")

        llm = self._llm

        tools_by_name, dynamic, retrieve_tool = self._build_child_toolset(
            config=config,
            inherited_tool_names=inherited_tool_names,
        )
        bound_tool_names: set[str] = set(tools_by_name.keys())

        llm_with_tools = (
            llm.bind_tools(list(tools_by_name.values()))  # type: ignore[union-attr, attr-defined]
            if tools_by_name
            else llm
        )

        # Build initial messages
        messages: list[Any] = [SystemMessage(content=self._system_prompt)]
        user_content = (
            f"Context:\n{context}\n\nTask:\n{task}" if context else f"Task:\n{task}"
        )
        messages.append(HumanMessage(content=user_content))

        # Tool-calling loop
        for _turn in range(self._max_turns):
            response: AIMessage = await llm_with_tools.ainvoke(messages)  # type: ignore[assignment]
            messages.append(response)

            if not response.tool_calls:
                return str(response.content) if response.content else "Task completed."

            for tc in response.tool_calls:
                name = tc["name"]
                tc_id = tc["id"]

                # --- retrieve_tools: discover/bind tools dynamically ---
                if (
                    name == _RETRIEVE_TOOLS_NAME
                    and dynamic
                    and retrieve_tool is not None
                ):
                    try:
                        result = await retrieve_tool.ainvoke(tc["args"])
                        newly_bound = self._bind_tools_from_registry(
                            result.get("tools_to_bind", []),
                            tools_by_name,
                            bound_tool_names,
                        )
                        if newly_bound:
                            logger.info(
                                f"Subagent bound {len(newly_bound)} tools: {newly_bound}"
                            )

                        content = (
                            "\n".join(result.get("response", [])) or "No tools found."
                        )
                    except Exception as e:
                        logger.error("Subagent retrieve_tools error: {}", str(e))
                        content = f"retrieve_tools error: {e}"

                    messages.append(
                        ToolMessage(content=content, tool_call_id=tc_id, name=name)
                    )

                    # Rebind LLM with updated tool set
                    llm_with_tools = llm.bind_tools(list(tools_by_name.values()))  # type: ignore[union-attr, attr-defined]
                    continue

                # --- Regular tool execution ---
                if name in tools_by_name:
                    try:
                        result = await tools_by_name[name].ainvoke(
                            {**tc, "type": "tool_call"}, config=config
                        )
                        messages.append(
                            ToolMessage(
                                content=str(result), tool_call_id=tc_id, name=name
                            )
                        )
                    except Exception as e:
                        messages.append(
                            ToolMessage(
                                content=f"Tool error: {e}",
                                tool_call_id=tc_id,
                                name=name,
                                status="error",
                            )
                        )
                    continue

                # --- Unknown tool ---
                hint = (
                    " Use retrieve_tools to discover and bind tools first."
                    if dynamic
                    else ""
                )
                messages.append(
                    ToolMessage(
                        content=f"Unknown tool: {name}.{hint}",
                        tool_call_id=tc_id,
                        name=name,
                        status="error",
                    )
                )

        # Max turns reached — get final answer without tools
        final = await llm.ainvoke(messages)  # type: ignore[union-attr]
        if isinstance(final, AIMessage) and final.content:
            return str(final.content)
        return str(final) if final else "Max turns reached."

    def _build_child_toolset(
        self,
        config: RunnableConfig,
        inherited_tool_names: Optional[list[str]] = None,
    ) -> tuple[dict[str, BaseTool], bool, StructuredTool | None]:
        """Build child subagent tool map from runtime config and parent state."""
        retrieve_tool = self._build_retrieve_tool(config)
        dynamic = retrieve_tool is not None and self._tool_registry is not None

        tools_by_name: dict[str, BaseTool] = {}
        bound_tool_names: set[str] = set()

        # Bind configured initial tools first (regular tools, not special behavior tools).
        self._bind_tools_from_registry(
            self._tool_runtime_config.initial_tool_names,
            tools_by_name,
            bound_tool_names,
        )

        # Inherit tools currently bound by the parent agent in this turn.
        if inherited_tool_names:
            self._bind_tools_from_registry(
                inherited_tool_names,
                tools_by_name,
                bound_tool_names,
            )

        if dynamic and retrieve_tool is not None:
            tools_by_name[_RETRIEVE_TOOLS_NAME] = retrieve_tool  # type: ignore[assignment]

        # If nothing resolved (defensive fallback), bind all eligible tools.
        if not tools_by_name:
            all_tools = self._collect_tools()
            tools_by_name = {t.name: t for t in all_tools}

        return tools_by_name, dynamic, retrieve_tool

    def set_llm(self, llm: LanguageModelLike) -> None:
        self._llm = llm

    def set_store(self, store: BaseStore) -> None:
        self._store = store

    def set_tools(
        self,
        tools: list[BaseTool] | None = None,
        registry: Mapping[str, BaseTool] | None = None,
        excluded_tool_names: set[str] | None = None,
        tool_space: str | None = None,
        tool_runtime_config: ToolRuntimeConfig | None = None,
    ) -> None:
        if tools is not None:
            self._available_tools = tools
        if registry is not None:
            self._tool_registry = registry
        if excluded_tool_names is not None:
            self._excluded_tools.update(excluded_tool_names)
            self._excluded_tools.add("spawn_subagent")
        if tool_space is not None:
            self._tool_space = tool_space
        if tool_runtime_config is not None:
            self._tool_runtime_config = tool_runtime_config
