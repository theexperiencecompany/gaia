"""Shared orchestrator framework for provider specific subgraphs.

ARCHITECTURE OVERVIEW:
This framework implements a message-history-based orchestrator pattern where:

1. ORCHESTRATOR: Main agent that either executes directly OR hands off to specialized nodes
2. SPECIALIZED NODES: Each node has its own prompt and tools
3. FINALIZER: Compiles results from complete message history

KEY FEATURES:
- Orchestrator decides each step: execute directly or delegate to a node
- Handoff via JSON: {"name": "node_name", "instruction": "task"}
- Each node has specialized prompts (not one monolithic prompt)
- Full message history (including tool calls) flows through all nodes
- Finalizer provides structured compilation

MESSAGE FLOW:
- Orchestrator receives all messages and decides next action
- If handoff JSON detected, route to specialized node
- Node execution adds messages to central history
- Control returns to orchestrator
- If no handoff/tool call, execution is complete
- Finalizer sees complete conversation to compile final output

BENEFITS:
- No upfront planning overhead - orchestrator decides dynamically
- Tool calls are never lost - they're in the message history
- Each node can make informed decisions based on what previous steps did
- Natural conversation flow while maintaining specialized behavior per node
- Finalizer has complete context to produce comprehensive summaries

USAGE:
Use build_orchestrator_subgraph() with OrchestratorSubgraphConfig to create
a configured subgraph with automatic message filtering and cleanup hooks.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Union,
    cast,
)

from app.agents.core.nodes.filter_messages import create_filter_messages_node
from app.agents.core.nodes.trim_messages_node import trim_messages_node
from app.agents.llm.client import init_llm
from app.constants.general import ORCHESTRATOR_MAX_ITERATIONS
from langchain_core.language_models import LanguageModelLike
from langchain_core.language_models.chat_models import (
    BaseChatModel,
)
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, create_react_agent
from langgraph.store.base import BaseStore
from pydantic import BaseModel, Field


class NodeHandoff(BaseModel):
    """Model for orchestrator handoff to specialized node."""

    name: str = Field(description="The name of the node to hand off to")
    instruction: str = Field(description="The specific instruction for the node")


# Finalizer Prompt Template
FINALIZER_HUMAN_PROMPT = """
You have access to the complete conversation history above, including all tool calls, inputs, and outputs from each step.
Please compile this information into a comprehensive summary for the main agent following your specialized instructions."""


class OrchestratorState(MessagesState):
    """Simplified state for orchestrator pattern."""

    _next_node: Optional[str]
    _node_instruction: Optional[str]
    is_complete: bool
    _orchestrator_iterations: int


HookType = Union[
    Callable[[OrchestratorState, RunnableConfig, BaseStore], OrchestratorState],
    Callable[
        [OrchestratorState, RunnableConfig, BaseStore], Awaitable[OrchestratorState]
    ],
]
NodeHandler = Callable[
    [
        str,
        Optional[RunnableConfig],
        Optional[BaseStore],
        Sequence[AnyMessage],
    ],
    Awaitable[Any],
]

handoff_parser = PydanticOutputParser(pydantic_object=NodeHandoff)


@dataclass
class OrchestratorNodeConfig:
    name: str
    description: str
    system_prompt: str
    tools: Optional[Sequence[BaseTool]] = None


@dataclass
class OrchestratorSubgraphConfig:
    provider_name: str
    agent_name: str
    node_configs: Sequence[OrchestratorNodeConfig]
    finalizer_prompt: Optional[str] = None
    orchestrator_tools: Optional[Sequence[BaseTool]] = None
    llm: Optional[LanguageModelLike] = None


class OrchestratorGraph:
    """LangGraph-backed orchestrator with dynamic node handoff."""

    def __init__(
        self,
        provider_name: str,
        agent_name: str,
        *,
        node_configs: Sequence[OrchestratorNodeConfig],
        orchestrator_tools: Optional[Sequence[BaseTool]] = None,
        llm: Optional[LanguageModelLike] = None,
        finalizer_prompt: Optional[str] = None,
        pre_llm_hooks: Optional[Sequence[HookType]] = None,
        end_graph_hooks: Optional[Sequence[HookType]] = None,
    ):
        self.provider_name = provider_name
        self.agent_name = agent_name
        self._orchestrator_tools = orchestrator_tools or []
        self._finalizer_prompt = finalizer_prompt
        self._has_finalizer = finalizer_prompt is not None
        self.llm = llm or init_llm()
        self._pre_llm_hooks = pre_llm_hooks or []
        self._end_graph_hooks = end_graph_hooks or []
        self._nodes: Dict[str, NodeHandler] = {}
        self._node_descriptions: Dict[str, str] = {}

        for node_config in node_configs:
            if node_config.name in self._nodes:
                raise ValueError(f"Duplicate node name detected: {node_config.name}")
            self._nodes[node_config.name] = self._create_prompt_node(node_config)
            self._node_descriptions[node_config.name] = node_config.description

        self._graph = self._build_orchestrator_graph()

    async def _orchestrator_step(
        self, state: OrchestratorState, config: RunnableConfig, store: BaseStore
    ) -> OrchestratorState:
        iterations = state.get("_orchestrator_iterations", 0)
        if iterations >= ORCHESTRATOR_MAX_ITERATIONS:
            error_msg = AIMessage(
                content="Orchestrator recursion limit reached (20 iterations). Forcing finalization.",
                additional_kwargs={
                    "orchestrator_role": "orchestrator",
                    "visible_to": {self.agent_name},
                },
            )
            state["messages"] = [*state["messages"], error_msg]
            state["is_complete"] = True
            return state

        state["_orchestrator_iterations"] = iterations + 1

        for hook in self._pre_llm_hooks:
            result = hook(state, config, store)
            if inspect.iscoroutine(result):
                state = await result  # type: ignore
            else:
                state = result  # type: ignore

        messages = state.get("messages", [])

        if self._orchestrator_tools:
            bound_llm = self._bind_tools(self.llm, self._orchestrator_tools)
            response = await self._invoke_llm(bound_llm, messages, config)
        else:
            response = await self._invoke_llm(self.llm, messages, config)

        response_message = (
            cast(AIMessage, response)
            if isinstance(response, BaseMessage)
            else AIMessage(content=str(response))
        )

        content = self._extract_content(response)
        handoff = self._try_parse_handoff(content)

        # Mark handoff messages for later deletion
        if handoff:
            response_message.additional_kwargs["orchestrator_role"] = "handoff"
            response_message.additional_kwargs["visible_to"] = {self.agent_name}
        else:
            response_message.additional_kwargs["orchestrator_role"] = "orchestrator"
            # If no finalizer, make orchestrator's final response visible to main_agent
            if self._has_finalizer:
                response_message.additional_kwargs["visible_to"] = {self.agent_name}
            else:
                response_message.additional_kwargs["visible_to"] = {
                    "main_agent",
                    self.agent_name,
                }

        state["messages"] = [*state["messages"], response_message]

        if handoff:
            if handoff.name not in self._nodes:
                error_msg = AIMessage(
                    content=f"Error: Unknown node '{handoff.name}'. Available nodes: {', '.join(self._node_descriptions.keys())}",
                    additional_kwargs={
                        "orchestrator_role": "orchestrator",
                        "visible_to": {self.agent_name},
                    },
                )
                state["messages"] = [*state["messages"], error_msg]
                state["is_complete"] = False
                return state

            state["_next_node"] = handoff.name
            state["_node_instruction"] = handoff.instruction
            return state

        has_tool_calls = isinstance(response_message, AIMessage) and bool(
            response_message.tool_calls
        )

        if has_tool_calls:
            state["is_complete"] = False
        else:
            state["is_complete"] = True

        return state

    def _try_parse_handoff(self, content: str) -> Optional[NodeHandoff]:
        try:
            return handoff_parser.parse(content)
        except Exception:
            return None

    def _extract_content(self, response: Union[str, BaseMessage]) -> str:
        if isinstance(response, str):
            return response
        if isinstance(response, BaseMessage):
            return response.text()
        return str(response)

    def _should_continue(self, state: OrchestratorState) -> str:
        if state.get("is_complete", False):
            # If no finalizer, skip directly to end hooks or END
            if not self._has_finalizer:
                return "end"
            return "finalize"

        next_node = state.get("_next_node")
        if next_node:
            return next_node

        # Check for tool calls
        messages = state.get("messages", [])
        if messages:
            last_message = messages[-1]
            if isinstance(last_message, AIMessage) and last_message.tool_calls:
                return "tools"

        return "orchestrator"

    def _create_node_wrapper(
        self,
        node_name: str,
        node_func: NodeHandler,
    ) -> Callable[[OrchestratorState, RunnableConfig], Awaitable[OrchestratorState]]:
        async def node_wrapper(
            state: OrchestratorState,
            config: RunnableConfig,
            *,
            store: BaseStore | None = None,
        ) -> OrchestratorState:
            instruction = state.get("_node_instruction", "")
            if not instruction:
                instruction = "Execute the requested operation."

            try:
                result = await node_func(
                    instruction, config, store, state.get("messages", [])
                )

                new_messages = result.get("messages", [])

                for msg in new_messages:
                    # Mark node messages
                    if not msg.additional_kwargs.get("orchestrator_role"):
                        msg.additional_kwargs["orchestrator_role"] = "node"
                        msg.additional_kwargs["visible_to"] = {self.agent_name}

                state.setdefault("messages", []).extend(new_messages)

            except Exception as e:
                error_msg = AIMessage(
                    content=f"Error in node {node_name}: {str(e)}",
                    additional_kwargs={
                        "orchestrator_role": "node",
                        "visible_to": {self.agent_name},
                    },
                )
                state.setdefault("messages", []).append(error_msg)

            state["_next_node"] = None
            state["_node_instruction"] = None
            return state

        return node_wrapper

    async def _finalization_step(
        self, state: OrchestratorState, config: RunnableConfig, store: BaseStore
    ) -> OrchestratorState:
        if not self._has_finalizer or not self._finalizer_prompt:
            return state

        for hook in self._pre_llm_hooks:
            result = hook(state, config, store)
            if inspect.iscoroutine(result):
                state = await result  # type: ignore
            else:
                state = result  # type: ignore

        messages = state.get("messages", [])

        finalizer_system = SystemMessage(
            content=self._finalizer_prompt,
            additional_kwargs={
                "orchestrator_role": "finalizer_system",
                "visible_to": {self.agent_name},
            },
        )
        finalizer_human = HumanMessage(
            content=FINALIZER_HUMAN_PROMPT,
            additional_kwargs={
                "orchestrator_role": "finalizer_human",
                "visible_to": {self.agent_name},
            },
        )

        finalizer_messages: List[AnyMessage] = [finalizer_system]
        finalizer_messages.extend(messages)
        finalizer_messages.append(finalizer_human)

        response = await self._invoke_llm(self.llm, finalizer_messages)
        finalizer_content = self._extract_content(response)

        finalizer_message = AIMessage(
            content=f"{self.agent_name}: \n\n{finalizer_content}",
            additional_kwargs={
                "orchestrator_role": "finalizer",
                "visible_to": {"main_agent", self.agent_name},
            },
        )
        state["messages"] = [*state["messages"], finalizer_message]

        state["is_complete"] = True
        return state

    def _build_orchestrator_graph(
        self,
    ) -> StateGraph[OrchestratorState, None, OrchestratorState, OrchestratorState]:
        workflow: StateGraph[
            OrchestratorState, None, OrchestratorState, OrchestratorState
        ] = StateGraph(OrchestratorState)  # type: ignore[assignment]
        workflow.add_node("orchestrator", self._orchestrator_step)

        # Only add finalizer if prompt is provided
        if self._has_finalizer:
            workflow.add_node("finalizer", self._finalization_step)

        # Add tools node if orchestrator has tools
        if self._orchestrator_tools:
            tools_node = ToolNode(list(self._orchestrator_tools))
            workflow.add_node("tools", tools_node)

        if self._end_graph_hooks:

            async def end_hooks_node(
                state: OrchestratorState, config: RunnableConfig, store: BaseStore
            ) -> OrchestratorState:
                for hook in self._end_graph_hooks:
                    result = hook(state, config, store)
                    if inspect.iscoroutine(result):
                        state = await result  # type: ignore
                    else:
                        state = result  # type: ignore
                return state

            workflow.add_node("end_graph_hooks", end_hooks_node)

        for node_name, node_func in self._nodes.items():
            workflow.add_node(
                node_name,
                cast(Any, self._create_node_wrapper(node_name, node_func)),
            )

        workflow.set_entry_point("orchestrator")

        # Build path map for conditional edges
        path_map: Dict[str, str] = {
            "orchestrator": "orchestrator",
            **{node_name: node_name for node_name in self._nodes.keys()},
        }
        if self._has_finalizer:
            path_map["finalize"] = "finalizer"
        else:
            # When no finalizer, "end" goes to hooks or END
            if self._end_graph_hooks:
                path_map["end"] = "end_graph_hooks"
            else:
                path_map["end"] = END
        if self._orchestrator_tools:
            path_map["tools"] = "tools"

        workflow.add_conditional_edges(
            "orchestrator",
            self._should_continue,
            cast(Any, path_map),
        )

        # Add edge from tools back to orchestrator
        if self._orchestrator_tools:
            workflow.add_edge("tools", "orchestrator")

        for node_name in self._nodes.keys():
            workflow.add_edge(node_name, "orchestrator")

        # Connect finalizer to end hooks or END (only if finalizer exists)
        if self._has_finalizer:
            if self._end_graph_hooks:
                workflow.add_edge("finalizer", "end_graph_hooks")
                workflow.add_edge("end_graph_hooks", END)
            else:
                workflow.add_edge("finalizer", END)
        elif self._end_graph_hooks:
            # No finalizer but has end hooks - already handled in path_map
            workflow.add_edge("end_graph_hooks", END)

        return workflow

    def _create_prompt_node(self, node_config: OrchestratorNodeConfig) -> NodeHandler:
        """Create a prompt-based node with tool call handling using create_react_agent."""
        tools: list[BaseTool] = list(node_config.tools or [])

        node_agent = create_react_agent(
            model=self.llm,
            tools=tools,
            name=f"{self.agent_name}_{node_config.name}",
        )

        async def node(
            instruction: str,
            runtime_config: Optional[RunnableConfig] = None,
            store: Optional[BaseStore] = None,
            previous_messages: Sequence[AnyMessage] = (),
        ) -> Dict[str, Any]:
            messages = list(previous_messages)

            temp_state: OrchestratorState = {"messages": messages}  # type: ignore
            for hook in self._pre_llm_hooks:
                result = hook(temp_state, runtime_config or {}, store)  # type: ignore
                if inspect.iscoroutine(result):
                    temp_state = await result  # type: ignore
                else:
                    temp_state = result  # type: ignore
            messages = list(temp_state.get("messages", []))

            system_message = SystemMessage(
                content=node_config.system_prompt,
            )

            human_message = HumanMessage(
                content=instruction,
            )

            final_messages = messages + [system_message, human_message]
            initial_state = {"messages": final_messages}

            graph_config: RunnableConfig = cast(
                RunnableConfig, dict(runtime_config or {})
            )

            invoke_kwargs: Dict[str, Any] = {
                "config": {**graph_config, "recursion_limit": 12}
            }
            if store is not None:
                invoke_kwargs["store"] = store

            result_state = await node_agent.ainvoke(initial_state, **invoke_kwargs)
            final_messages_result = result_state.get("messages", [])

            new_messages = final_messages_result[len(final_messages) :]

            response_message = next(
                (msg for msg in reversed(new_messages) if isinstance(msg, AIMessage)),
                None,
            )
            text = response_message.text() if response_message else ""

            return {"output": text, "messages": new_messages, "success": True}

        return node

    def _bind_tools(self, llm, tools: Sequence[BaseTool]):
        if isinstance(llm, BaseChatModel):
            return llm.bind_tools(tools)

        raise ValueError("Provided LLM does not support tool binding")

    async def _invoke_llm(
        self,
        llm: LanguageModelLike,
        messages: List[AnyMessage],
        config: Optional[RunnableConfig] = None,
    ) -> BaseMessage | str:
        return await llm.ainvoke(messages, config=config)


def _create_cleanup_hook(agent_name: str) -> HookType:
    """Create a cleanup hook that removes orchestrator-specific messages and normalizes names.

    This hook:
    1. Removes orchestrator system prompts (will be re-added in next request)
    2. Removes AI messages that are just handoff JSON
    3. Removes finalizer system and human messages
    4. Keeps only finalizer AI messages (the actual summary)
    5. Adds agent_name to all remaining orchestrator messages
    """

    def cleanup_messages(
        state: OrchestratorState, config: RunnableConfig, store: BaseStore
    ) -> OrchestratorState:
        try:
            messages = state.get("messages", [])
            cleaned_messages = []

            for msg in messages:
                orchestrator_role = msg.additional_kwargs.get("orchestrator_role")

                # Skip orchestrator-created messages that should be removed
                if orchestrator_role in [
                    "orchestrator_system",  # Orchestrator system prompt
                    "handoff",  # Handoff AI messages
                    "finalizer_system",  # Finalizer system prompt
                    "finalizer_human",  # Finalizer human instruction
                ]:
                    continue

                # Keep all non-orchestrator messages unchanged
                if not orchestrator_role:
                    cleaned_messages.append(msg)
                    continue

                if orchestrator_role in ["orchestrator", "node", "finalizer"]:
                    visible_to = msg.additional_kwargs.get(
                        "visible_to", set(agent_name)
                    )

                    msg.additional_kwargs["visible_to"] = visible_to
                    cleaned_messages.append(msg)

            return {**state, "messages": cleaned_messages}  # type: ignore[return-value]

        except Exception as e:
            from app.config.loggers import chat_logger as logger

            logger.error(f"Error in cleanup hook: {e}")
            return state

    return cleanup_messages


def build_orchestrator_subgraph(
    config: OrchestratorSubgraphConfig,
):
    """Build an orchestrator subgraph with automatic filter, trim, and delete hooks.

    Args:
        config: Configuration for the subgraph

    Returns:
        Compiled CompiledGraph with OrchestratorState and built-in message filtering and cleanup
    """
    filter_node = create_filter_messages_node(
        agent_name=config.agent_name,
        allow_memory_system_messages=True,
    )
    cleanup_hook = _create_cleanup_hook(config.agent_name)

    graph = OrchestratorGraph(
        provider_name=config.provider_name,
        agent_name=config.agent_name,
        node_configs=config.node_configs,
        orchestrator_tools=config.orchestrator_tools,
        llm=config.llm,
        finalizer_prompt=config.finalizer_prompt,
        pre_llm_hooks=[filter_node, cast(HookType, trim_messages_node)],
        end_graph_hooks=[cleanup_hook],
    )

    return graph._graph.compile()
