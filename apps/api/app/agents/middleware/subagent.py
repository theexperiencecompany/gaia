"""
SubagentMiddleware — exposes spawn_subagent tool for lightweight parallel task execution.

Spawned subagents run a simple tool-calling loop (no full graph/checkpointer).
When a tool_registry + store are configured, subagents get `retrieve_tools`
for dynamic discovery instead of binding all tools upfront.
"""

import asyncio
import time
from collections.abc import Mapping
from typing import Annotated, Any, Optional, cast
from uuid import uuid4

from app.agents.core.subagents.token_budget import (
    _BUDGET_EXCEEDED_FOOTER,
    _BUDGET_EXCEEDED_PROMPT,
    SubagentTokenLimitError,
    TokenBudgetCallbackHandler,
)
from app.agents.prompts.spawn_subagent_prompts import (
    SPAWN_SUBAGENT_DESCRIPTION,
    SPAWN_SUBAGENT_SYSTEM_PROMPT,
)
from app.agents.tools.core.retrieval import get_retrieve_tools_function
from app.agents.tools.core.tool_runtime_config import ToolRuntimeConfig
from app.constants.llm import SUBAGENT_MAX_TOKENS, SUBAGENT_RECURSION_LIMIT
from app.utils.agent_utils import format_subagent_end_event, format_subagent_start_event
from langchain.agents.middleware.types import AgentMiddleware, AgentState, OmitFromInput
from langchain.tools import InjectedToolCallId
from langchain_core.language_models import LanguageModelLike
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.messages.tool import ToolCall
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool, tool
from langgraph.config import get_stream_writer
from langgraph.prebuilt import InjectedState
from langgraph.store.base import BaseStore
from langgraph.types import Command
from shared.py.wide_events import log

_RETRIEVE_TOOLS_NAME = "retrieve_tools"
_TOOL_CONCURRENCY = 8


async def _invoke_tool(
    tc: ToolCall,
    tools_by_name: dict[str, BaseTool],
    config: RunnableConfig,
    dynamic: bool,
) -> ToolMessage:
    """Invoke a single tool call, returning a ToolMessage with the result or error."""
    name = tc["name"]
    tc_id = tc["id"]

    if name not in tools_by_name:
        hint = " Use retrieve_tools to discover and bind tools first." if dynamic else ""
        return ToolMessage(
            content=f"Unknown tool: {name}.{hint}",
            tool_call_id=tc_id,
            name=name,
            status="error",
        )
    try:
        result = await tools_by_name[name].ainvoke({**tc, "type": "tool_call"}, config=config)
        return ToolMessage(content=str(result), tool_call_id=tc_id, name=name)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception(
            "Subagent tool invocation failed for tool '{}' (tool_call_id={})", name, tc_id
        )
        return ToolMessage(
            content="Tool error: internal failure while executing tool.",
            tool_call_id=tc_id,
            name=name,
            status="error",
        )


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
        max_turns: int = SUBAGENT_RECURSION_LIMIT,
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
        self._tool_runtime_config = tool_runtime_config or ToolRuntimeConfig(
            initial_tool_names=["vfs_read", "vfs_cmd"],
            enable_retrieve_tools=True,
            include_subagents_in_retrieve=False,
        )
        self.tools = [self._create_spawn_subagent_tool()]


    def _create_spawn_subagent_tool(self) -> BaseTool:
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
                return Command(update={"messages": [ToolMessage(
                    content="Error: Subagent LLM not configured",
                    tool_call_id=tool_call_id,
                    status="error",
                )]})

            try:
                writer = get_stream_writer()
                invocation_id = str(uuid4())
                parent_subagent_id: str | None = config.get("configurable", {}).get("parent_subagent_id")
                writer({"subagent_start": format_subagent_start_event(
                    subagent_name="Task Agent",
                    agent_type="spawned",
                    subagent_id=invocation_id,
                    parent_subagent_id=parent_subagent_id,
                )})
                _t0 = time.monotonic()
                result = await middleware._execute_subagent(
                    task, context, config,
                    inherited_tool_names=selected_tool_ids,
                    stream_writer=writer,
                    subagent_id=invocation_id,
                )
                _duration_ms = int((time.monotonic() - _t0) * 1000)
                writer({"subagent_end": format_subagent_end_event(
                    subagent_id=invocation_id,
                    duration_ms=_duration_ms,
                )})
                return Command(update={"messages": [ToolMessage(
                    content=result, tool_call_id=tool_call_id
                )]})
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"Subagent execution failed: {e}")
                return Command(update={"messages": [ToolMessage(
                    content=f"Subagent error: {e}",
                    tool_call_id=tool_call_id,
                    status="error",
                )]})

        return spawn_subagent


    async def _execute_subagent(
        self,
        task: str,
        context: str,
        config: RunnableConfig,
        inherited_tool_names: list[str] | None = None,
        stream_writer: Any = None,
        subagent_id: str | None = None,
    ) -> str:
        """Run a lightweight tool-calling loop for the subagent.

        A TokenBudgetCallbackHandler is injected so SubagentTokenLimitError
        fires from on_llm_end when the budget is exceeded, stopping the loop
        cleanly without starting a new one.
        """
        if self._llm is None:
            raise ValueError("LLM not configured for subagent execution")

        patched_config: dict = self._inject_budget_callback(config)
        llm: Any = self._llm.with_config(configurable=patched_config.get("configurable", {}))

        tools_by_name, dynamic, retrieve_tool = self._build_child_toolset(
            config=patched_config, inherited_tool_names=inherited_tool_names
        )
        bound_tool_names: set[str] = set(tools_by_name.keys())
        llm_with_tools = llm.bind_tools(list(tools_by_name.values())) if tools_by_name else llm

        user_content = f"Context:\n{context}\n\nTask:\n{task}" if context else f"Task:\n{task}"
        messages: list[Any] = [
            SystemMessage(content=self._system_prompt),
            HumanMessage(content=user_content),
        ]

        try:
            return await self._tool_calling_loop(
                llm=llm,
                llm_with_tools=llm_with_tools,
                messages=messages,
                tools_by_name=tools_by_name,
                bound_tool_names=bound_tool_names,
                dynamic=dynamic,
                retrieve_tool=retrieve_tool,
                config=patched_config,
                stream_writer=stream_writer,
                subagent_id=subagent_id,
            )
        except SubagentTokenLimitError as e:
            log.warning("spawn_subagent token limit reached", tokens_used=e.tokens_used, limit=e.limit)
            messages.append(HumanMessage(content=_BUDGET_EXCEEDED_PROMPT))
            final = cast(AIMessage, await llm.ainvoke(messages, config=patched_config))
            content = str(final.content) if final.content else "Token limit reached."
            return content + _BUDGET_EXCEEDED_FOOTER

    async def _tool_calling_loop(
        self,
        llm: Any,
        llm_with_tools: Any,
        messages: list[Any],
        tools_by_name: dict[str, BaseTool],
        bound_tool_names: set[str],
        dynamic: bool,
        retrieve_tool: StructuredTool | None,
        config: Any,
        stream_writer: Any = None,
        subagent_id: str | None = None,
    ) -> str:
        """ReAct loop: call LLM → execute tools → repeat until done or max turns."""
        semaphore = asyncio.Semaphore(_TOOL_CONCURRENCY)

        for _turn in range(self._max_turns):
            response = cast(AIMessage, await llm_with_tools.ainvoke(messages, config=config))
            messages.append(response)

            if not response.tool_calls:
                return str(response.content) if response.content else "Task completed."

            regular_calls: list[ToolCall] = []
            for tc in response.tool_calls:
                if tc["name"] == _RETRIEVE_TOOLS_NAME and dynamic and retrieve_tool:
                    await self._handle_retrieve_tools(
                        tc=tc,
                        retrieve_tool=retrieve_tool,
                        tools_by_name=tools_by_name,
                        bound_tool_names=bound_tool_names,
                        messages=messages,
                    )
                    llm_with_tools = llm.bind_tools(list(tools_by_name.values()))
                else:
                    regular_calls.append(tc)

            if regular_calls:
                async def _limited(tc: ToolCall) -> ToolMessage:
                    async with semaphore:
                        return await _invoke_tool(tc, tools_by_name, config, dynamic)

                tool_messages = await asyncio.gather(*[_limited(tc) for tc in regular_calls])
                messages.extend(tool_messages)

                # Emit tool_data + tool_output events so the frontend can render
                # this subagent's tool calls inside its SubagentThread block.
                if stream_writer and subagent_id:
                    for tc, tm in zip(regular_calls, tool_messages):
                        tool_name: str = tc["name"]
                        stream_writer({"tool_data": {
                            "tool_name": "tool_calls_data",
                            "tool_category": tool_name,
                            "subagent_id": subagent_id,
                            "data": {
                                "tool_name": tool_name,
                                "tool_category": tool_name,
                                "message": tool_name.replace("_", " ").title(),
                                "tool_call_id": tc["id"],
                                "inputs": tc.get("args", {}),
                            },
                            "timestamp": None,
                        }})
                        raw_output = tm.content
                        output_str = (
                            raw_output[:3000]
                            if isinstance(raw_output, str)
                            else str(raw_output)[:3000]
                        )
                        stream_writer({"tool_output": {
                            "tool_call_id": tm.tool_call_id,
                            "output": output_str,
                            "subagent_id": subagent_id,
                        }})

        # Max turns reached — one final answer call without tools
        final = await llm.ainvoke(messages, config=config)
        if isinstance(final, AIMessage) and final.content:
            return str(final.content)
        return str(final) if final else "Max turns reached."

    async def _handle_retrieve_tools(
        self,
        tc: ToolCall,
        retrieve_tool: StructuredTool,
        tools_by_name: dict[str, BaseTool],
        bound_tool_names: set[str],
        messages: list[Any],
    ) -> None:
        """Execute a retrieve_tools call and bind the returned tools."""
        tc_id = tc["id"]
        try:
            result = await retrieve_tool.ainvoke(tc["args"])
            newly_bound = self._bind_tools_from_registry(
                result.get("tools_to_bind", []), tools_by_name, bound_tool_names
            )
            if newly_bound:
                log.info(f"Subagent bound {len(newly_bound)} tools: {newly_bound}")
            content = "\n".join(result.get("response", [])) or "No tools found."
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error(f"Subagent retrieve_tools error: {e}")
            content = f"retrieve_tools error: {e}"

        messages.append(ToolMessage(content=content, tool_call_id=tc_id, name=_RETRIEVE_TOOLS_NAME))


    def _build_child_toolset(
        self,
        config: Any,
        inherited_tool_names: list[str] | None = None,
    ) -> tuple[dict[str, BaseTool], bool, StructuredTool | None]:
        """Build the tool map for a spawned subagent."""
        retrieve_tool = self._build_retrieve_tool(config)
        dynamic = retrieve_tool is not None and self._tool_registry is not None

        tools_by_name: dict[str, BaseTool] = {}
        bound_tool_names: set[str] = set()

        self._bind_tools_from_registry(
            self._tool_runtime_config.initial_tool_names, tools_by_name, bound_tool_names
        )
        if inherited_tool_names:
            self._bind_tools_from_registry(inherited_tool_names, tools_by_name, bound_tool_names)
        if dynamic and retrieve_tool:
            tools_by_name[_RETRIEVE_TOOLS_NAME] = retrieve_tool

        # Defensive fallback: bind everything if nothing resolved
        if not tools_by_name:
            tools_by_name = {t.name: t for t in self._collect_tools()}

        return tools_by_name, dynamic, retrieve_tool

    def _build_retrieve_tool(self, config: RunnableConfig) -> StructuredTool | None:
        """Build a retrieve_tools tool bound to the current store and config."""
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
        ) -> Any:
            return await inner_fn(store=store, config=config, query=query, exact_tool_names=exact_tool_names)

        retrieve_tools.__doc__ = inner_fn.__doc__
        return StructuredTool.from_function(coroutine=retrieve_tools, name=_RETRIEVE_TOOLS_NAME)

    def _collect_tools(self) -> list[BaseTool]:
        """Collect all eligible tools from available_tools and tool_registry."""
        tools: list[BaseTool] = []
        for t in self._available_tools:
            if hasattr(t, "name") and t.name not in self._excluded_tools:
                tools.append(t)
        if self._tool_registry:
            for name, t in self._tool_registry.items():
                if name not in self._excluded_tools:
                    tools.append(t)
        return tools

    def _bind_tools_from_registry(
        self,
        names: list[str],
        tools_by_name: dict[str, BaseTool],
        bound_tool_names: set[str],
    ) -> list[str]:
        """Resolve tool names from the registry into tools_by_name. Returns newly bound names."""
        if not self._tool_registry:
            return []
        newly_bound: list[str] = []
        for name in names:
            if name in bound_tool_names or name in self._excluded_tools:
                continue
            if (t := self._tool_registry.get(name)) is not None:
                tools_by_name[name] = t
                bound_tool_names.add(name)
                newly_bound.append(name)
        return newly_bound

    def _inject_budget_callback(self, config: RunnableConfig) -> dict:
        """Return a new config dict with a TokenBudgetCallbackHandler appended."""
        cb = TokenBudgetCallbackHandler(SUBAGENT_MAX_TOKENS)
        raw = config.get("callbacks")
        existing: list[Any] = list(raw) if isinstance(raw, list) else []
        return {**config, "callbacks": [*existing, cb]}


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
