"""Shared plan-and-execute framework for provider specific subgraphs.

ARCHITECTURE OVERVIEW:
This framework implements a message-history-based plan-and-execute pattern where:

1. PLANNER: Creates a step-by-step execution plan
2. EXECUTOR: Runs each step sequentially with full conversation context
3. SPECIALIZED NODES: Each node has its own prompt and tools
4. FINALIZER: Compiles results from complete message history

KEY DIFFERENCES FROM STANDARD AGENTIC FLOW:
- Explicit planner/executor separation
- Each node has specialized prompts (not one monolithic prompt)
- Full message history (including tool calls) flows through steps
- Finalizer provides structured compilation

MESSAGE FLOW:
- Planning phase stores planning messages
- Each step receives ALL previous messages (not just summaries)
- Tool calls are naturally preserved in message history
- Subsequent steps can see previous tool calls and their results
- Finalizer sees complete conversation to compile final output

BENEFITS:
- No prompt engineering needed to "pass context" between steps
- Tool calls are never lost - they're in the message history
- Each node can make informed decisions based on what previous steps did
- Natural conversation flow while maintaining specialized behavior per node
- Finalizer has complete context to produce comprehensive summaries

USAGE:
Use build_plan_execute_subgraph() with PlanExecuteSubgraphConfig to create
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
    TypedDict,
    Union,
    cast,
)

from app.agents.core.nodes import trim_messages_node
from app.agents.core.nodes.filter_messages import create_filter_messages_node
from app.agents.llm.client import init_llm
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
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import create_react_agent
from langgraph.store.base import BaseStore
from pydantic import BaseModel, Field

BASE_NODE_INSTRUCTION = """IMPORTANT EXECUTION CONTEXT:
You are executing a specific step within a multi-step plan. The delegation chain is: User → Main Agent → Sub-graph → You (Current Node).

KEY CONSTRAINTS:
- You CANNOT directly communicate with users or ask them questions
- You are part of an automated execution pipeline
- The sub-graph has created a step-by-step plan, and you are executing one specific step
- You can see the full conversation history including previous steps' tool calls and outputs

YOUR RESPONSIBILITIES:
- Execute your assigned task completely and accurately using the specialized tools and context available to you
- Review previous steps' outputs and tool calls to inform your decisions
- When finished, briefly explain what you did and the outcome
- Include actionable results: IDs, statuses, key data points, relevant details
- Your output and tool calls will be visible to subsequent steps
- Be clear, concise, and provide sufficient context for next steps"""

_DEFAULT_BASE_PLANNER_PROMPT = """
You are a planning agent that creates execution plans.

PLANNING SPECIFICATIONS:
1. Break down the user request into discrete, executable steps
2. Each step should target a specific node based on its capabilities
3. Include relevant context for each step
4. Ensure steps are logically ordered for sequential execution
5. Each step will have access to outputs from all previous steps

Create a detailed execution plan with clear step descriptions and proper node assignments.

{provider_planner_prompt}

{format_instructions}
"""

DEFAULT_BASE_PLANNER_PROMPT_TEMPLATE = PromptTemplate(
    input_variables=["provider_planner_prompt", "format_instructions"],
    template=_DEFAULT_BASE_PLANNER_PROMPT,
)

_NODE_ENHANCED_PROMPT_TEMPLATE = """{base_instruction}

{node_system_prompt}

CURRENT EXECUTION:
You are currently executing Step {step_id} of the plan."""


class ExecutionResult:
    """Mutable execution result container."""

    def __init__(
        self, step_id: int, success: bool, output: Any, error: Optional[str] = None
    ):
        self.step_id = step_id
        self.success = success
        self.output = output
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "success": self.success,
            "output": self.output,
            "error": self.error,
        }


class ExecutionStep(BaseModel):
    step_id: int
    node_name: str
    instructions: str
    context: Dict[str, Any] = Field(default_factory=dict)


class ExecutionPlan(BaseModel):
    description: str = ""
    steps: List[ExecutionStep] = Field(default_factory=list)


class ExecutionContext(TypedDict, total=False):
    instructions: str
    context: Dict[str, Any]
    step_id: int


class PlanExecuteState(MessagesState, total=False):
    available_nodes: Dict[str, str]
    include_previous_outputs: bool
    plan: ExecutionPlan
    current_step: int
    execution_results: List[ExecutionResult]
    completed_steps: List[int]
    ready_steps: List[int]
    pending_steps: List[int]
    in_progress_steps: List[int]
    step_execution_contexts: Dict[int, ExecutionContext]
    step_node_mappings: Dict[int, str]
    _next_node: Optional[str]
    _execution_context: Optional[ExecutionContext]
    final_result: Dict[str, Any]
    is_complete: bool


class PlanExecuteAgentState(TypedDict, total=False):
    messages: List[BaseMessage]
    plan_execute_scratchpad: Dict[str, Any]


HookType = Union[
    Callable[[PlanExecuteState, RunnableConfig, BaseStore], PlanExecuteState],
    Callable[
        [PlanExecuteState, RunnableConfig, BaseStore], Awaitable[PlanExecuteState]
    ],
]
NodeHandler = Callable[
    [
        ExecutionContext,
        Optional[RunnableConfig],
        Optional[BaseStore],
        Sequence[AnyMessage],
    ],
    Awaitable[Any],
]


@dataclass
class PlanExecuteNodeConfig:
    name: str
    description: str
    system_prompt: str
    tools: Optional[Sequence[BaseTool]] = None


@dataclass
class PlanExecuteSubgraphConfig:
    provider_name: str
    agent_name: str
    planner_prompt: str
    node_configs: Sequence[PlanExecuteNodeConfig]
    llm: Optional[LanguageModelLike] = None
    finalizer_prompt: Optional[str] = None


class PromptDrivenPlanExecuteGraph:
    """LangGraph-backed planner/executor with support for prompt and runnable nodes."""

    _parser = PydanticOutputParser(pydantic_object=ExecutionPlan)

    def __init__(
        self,
        provider_name: str,
        agent_name: str,
        planner_prompt: str,
        *,
        node_configs: Sequence[PlanExecuteNodeConfig],
        llm: Optional[LanguageModelLike] = None,
        finalizer_prompt: Optional[str] = None,
        pre_llm_hooks: Optional[Sequence[HookType]] = None,
        end_graph_hooks: Optional[Sequence[HookType]] = None,
    ):
        self.provider_name = provider_name
        self.agent_name = agent_name
        self._planner_prompt = planner_prompt
        self._finalizer_prompt = finalizer_prompt
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

        self._graph = self._build_parallel_graph()

    async def _planning_step(
        self, state: PlanExecuteState, config: RunnableConfig, store: BaseStore
    ) -> PlanExecuteState:
        # Apply pre_plan_hooks for message filtering
        for hook in self._pre_llm_hooks:
            result = hook(state, config, store)
            if inspect.iscoroutine(result):
                state = await result  # type: ignore
            else:
                state = result  # type: ignore

        # Overriding system prompt sent by handoff tool
        state["messages"][-2] = SystemMessage(content=self._planner_prompt)  # type: ignore

        response = await self._invoke_llm(self.llm, state["messages"])

        content = self._extract_content(response)

        plan = self._parser.parse(content)
        state["plan"] = plan
        state["current_step"] = 0
        self._prepare_step_execution(state)

        # Create planner output message with agent_name_planner for preservation
        planner_response = None
        if isinstance(response, BaseMessage):
            planner_response = cast(AIMessage, response)
            planner_response.name = self.agent_name
        else:
            planner_response = AIMessage(
                content=content,
                name=self.agent_name,
            )

        return {"messages": [planner_response]}

    def _extract_content(self, response: Union[str, BaseMessage]) -> str:
        if isinstance(response, str):
            return response
        if isinstance(response, BaseMessage):
            return response.text()
        return str(response)

    def _prepare_step_execution(self, state: PlanExecuteState) -> None:
        plan = state.get("plan")
        if not plan:
            return

        state["ready_steps"] = []
        state["pending_steps"] = []
        state["in_progress_steps"] = []
        state["step_execution_contexts"] = {}
        state["step_node_mappings"] = {}

        for step in plan.steps:
            state["step_node_mappings"][step.step_id] = step.node_name

            execution_context: ExecutionContext = {
                "instructions": step.instructions,
                "context": step.context,
                "step_id": step.step_id,
            }
            state.setdefault("step_execution_contexts", {})[step.step_id] = (
                execution_context
            )

            # All steps start as ready (sequential execution)
            state.setdefault("ready_steps", []).append(step.step_id)

    def _execution_step(self, state: PlanExecuteState) -> PlanExecuteState:
        plan = state.get("plan")
        if not plan:
            state["is_complete"] = True
            return state

        total_steps = len(plan.steps)
        completed_count = len(state.get("completed_steps", []))

        if completed_count >= total_steps:
            state["is_complete"] = True
            return state

        self._update_ready_steps(state)

        ready_steps = state.get("ready_steps") or []
        if ready_steps:
            step_id = ready_steps[0]
            ready_steps.remove(step_id)
            state.setdefault("in_progress_steps", []).append(step_id)

            node_name = (state.get("step_node_mappings") or {}).get(step_id)
            if not node_name:
                raise ValueError(f"No node mapping for step {step_id}")

            execution_context = (state.get("step_execution_contexts") or {}).get(
                step_id, {}
            )

            state["_next_node"] = node_name
            state["_execution_context"] = execution_context
            return state

        pending_steps = state.get("pending_steps", [])
        in_progress = state.get("in_progress_steps", [])

        if not pending_steps and not in_progress and completed_count < total_steps:
            raise ValueError(
                f"Execution deadlock: {total_steps - completed_count} steps remaining but none ready or in progress"
            )

        return state

    def _update_ready_steps(self, state: PlanExecuteState) -> None:
        # Sequential execution: move pending steps to ready as previous steps complete
        pending_steps = state.get("pending_steps", [])

        if pending_steps:
            # Make the next pending step ready
            next_step = pending_steps.pop(0)
            state.setdefault("ready_steps", []).append(next_step)

    def _create_node_wrapper(
        self,
        node_name: str,
        node_func: NodeHandler,
    ) -> Callable[[PlanExecuteState, RunnableConfig], Awaitable[PlanExecuteState]]:
        async def node_wrapper(
            state: PlanExecuteState,
            config: RunnableConfig,
            *,
            store: BaseStore | None = None,
        ) -> PlanExecuteState:
            ctx = state.get("_execution_context")
            if not ctx:
                return state

            step_id = ctx.get("step_id", -1)
            try:
                # Pass current messages to node, get back new messages
                result = await node_func(ctx, config, store, state.get("messages", []))

                # Result contains new messages from agent execution
                new_messages = result.get("messages", [])
                output_text = result.get("output", "")

                # Set agent_name on all AI and Human messages from node execution
                for msg in new_messages:
                    if isinstance(msg, (AIMessage, HumanMessage)):
                        if not msg.name:
                            msg.name = self.agent_name

                # Add all new messages (including tool calls) to state
                state.setdefault("messages", []).extend(new_messages)

                execution_result = ExecutionResult(
                    step_id=step_id,
                    success=True,
                    output=output_text,
                )

            except Exception as e:
                execution_result = ExecutionResult(
                    step_id=step_id,
                    success=False,
                    output=None,
                    error=str(e),
                )

            state.setdefault("execution_results", []).append(execution_result)
            state.setdefault("completed_steps", []).append(step_id)
            state["_next_node"] = None
            state["_execution_context"] = None
            return state

        return node_wrapper

    def _should_continue_execution(self, state: PlanExecuteState) -> str:
        if state.get("is_complete", False):
            return "finalize"
        next_node = state.get("_next_node")
        if next_node:
            state["_next_node"] = None
            return next_node
        return "continue"

    async def _finalization_step(
        self, state: PlanExecuteState, config: RunnableConfig, store: BaseStore
    ) -> PlanExecuteState:
        # Apply pre_llm_hooks for message filtering before finalization
        for hook in self._pre_llm_hooks:
            result = hook(state, config, store)
            if inspect.iscoroutine(result):
                state = await result  # type: ignore
            else:
                state = result  # type: ignore

        plan = state.get("plan")
        if not plan:
            state["final_result"] = {"error": "No plan found"}
            state["is_complete"] = True
            return state

        all_results = state.get("execution_results", [])
        failed_steps = [r for r in all_results if not r.success]
        successful_steps = [r for r in all_results if r.success]
        step_node_mappings = state.get("step_node_mappings") or {}
        messages = state.get("messages", [])

        # If no finalizer prompt, use simple formatting (backward compatibility)
        if not self._finalizer_prompt:
            final_result = {
                "provider": self.provider_name,
                "plan_description": plan.description,
                "total_steps": len(plan.steps),
                "completed_steps": len(state.get("completed_steps", [])),
                "successful_steps": len(successful_steps),
                "failed_steps": len(failed_steps),
                "results": [
                    {
                        "step_id": r.step_id,
                        "node": step_node_mappings.get(r.step_id, "unknown"),
                        "success": r.success,
                        "output": r.output,
                        "error": r.error,
                    }
                    for r in all_results
                ],
                "message_count": len(messages),
            }

            if failed_steps:
                status_msg = f"Plan execution completed with {len(failed_steps)} failed steps out of {len(all_results)} total steps. Full conversation with {len(messages)} messages preserved."
            else:
                status_msg = f"Plan execution completed successfully with {len(all_results)} steps. Full conversation with {len(messages)} messages preserved including all tool calls."

            finalizer_message = AIMessage(
                content=status_msg,
                name=f"{self.agent_name},main_agent",
            )
            state.setdefault("messages", []).append(finalizer_message)
            state["final_result"] = final_result
            state["is_complete"] = True
            return state

        # LLM-powered finalization with finalizer_prompt
        # The finalizer sees the ENTIRE conversation history including all tool calls
        # This allows it to understand exactly what happened and compile accordingly

        # Build a summary header for context
        execution_summary = []
        for i, step in enumerate(plan.steps, 1):
            step_result = next(
                (r for r in all_results if r.step_id == step.step_id), None
            )
            node_name = step_node_mappings.get(step.step_id, "unknown")

            step_info = f"""Step {i}: {node_name} - {step.instructions}
Status: {"Success" if step_result and step_result.success else "Failed"}
"""
            if step_result:
                if step_result.success:
                    step_info += f"Output: {step_result.output}\n"
                else:
                    step_info += f"Error: {step_result.error}\n"
            execution_summary.append(step_info)

        execution_details = "\n".join(execution_summary)

        # Create human message explaining the task
        human_content = f"""PLAN EXECUTION COMPLETED

Plan Description: {plan.description}
Total Steps: {len(plan.steps)}
Completed Steps: {len(state.get("completed_steps", []))}
Successful Steps: {len(successful_steps)}
Failed Steps: {len(failed_steps)}

STEP SUMMARY:

{execution_details}

You have access to the complete conversation history above, including all tool calls, inputs, and outputs from each step.
Please compile this information into a comprehensive summary for the main agent following your specialized instructions."""

        # Start with system prompt, then full message history, then finalization request
        finalizer_messages: List[AnyMessage] = [
            SystemMessage(content=self._finalizer_prompt),
        ]
        # Add all execution messages (contains full context with tool calls)
        finalizer_messages.extend(messages)
        # Add the finalization request
        finalizer_messages.append(HumanMessage(content=human_content))

        response = await self._invoke_llm(self.llm, finalizer_messages)
        finalizer_content = self._extract_content(response)

        # Store the comprehensive final result
        final_result = {
            "provider": self.provider_name,
            "plan_description": plan.description,
            "total_steps": len(plan.steps),
            "completed_steps": len(state.get("completed_steps", [])),
            "successful_steps": len(successful_steps),
            "failed_steps": len(failed_steps),
            "compiled_summary": finalizer_content,
            "message_count": len(messages),
            "tool_calls_preserved": True,
            "raw_results": [
                {
                    "step_id": r.step_id,
                    "node": step_node_mappings.get(r.step_id, "unknown"),
                    "success": r.success,
                    "output": r.output,
                    "error": r.error,
                }
                for r in all_results
            ],
        }

        # Create finalizer message with comprehensive compiled summary
        # The finalizer has seen all tool calls and messages, so its summary is well-informed
        finalizer_message = AIMessage(
            content=finalizer_content,
            name=f"{self.agent_name},main_agent",
        )
        state.setdefault("messages", []).append(finalizer_message)

        state["final_result"] = final_result
        state["is_complete"] = True
        return state

    def _build_parallel_graph(
        self,
    ) -> StateGraph[PlanExecuteState, None, PlanExecuteState, PlanExecuteState]:
        workflow = StateGraph(PlanExecuteState)
        workflow.add_node("planner", self._planning_step)
        workflow.add_node("executor", self._execution_step)
        workflow.add_node("finalizer", self._finalization_step)

        # Add end_graph_hooks node if hooks are provided
        if self._end_graph_hooks:

            async def end_hooks_node(
                state: PlanExecuteState, config: RunnableConfig, store: BaseStore
            ) -> PlanExecuteState:
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

        workflow.set_entry_point("planner")
        workflow.add_edge("planner", "executor")

        workflow.add_conditional_edges(
            "executor",
            self._should_continue_execution,
            {
                "continue": "executor",
                "finalize": "finalizer",
                **{node_name: node_name for node_name in self._nodes.keys()},
            },
        )

        for node_name in self._nodes.keys():
            workflow.add_edge(node_name, "executor")

        # Connect finalizer to end_graph_hooks or END
        if self._end_graph_hooks:
            workflow.add_edge("finalizer", "end_graph_hooks")
            workflow.add_edge("end_graph_hooks", END)
        else:
            workflow.add_edge("finalizer", END)

        return workflow

    def _create_prompt_node(self, node_config: PlanExecuteNodeConfig) -> NodeHandler:
        """Create a prompt-based node with tool call handling using create_react_agent."""
        tools: list[BaseTool] = list(node_config.tools or [])

        # Create react agent without system prompt - we'll add it manually
        node_agent = create_react_agent(
            model=self.llm,
            tools=tools,
            name=f"{self.agent_name}_{node_config.name}",
        )

        async def node(
            execution_context: ExecutionContext,
            runtime_config: Optional[RunnableConfig] = None,
            store: Optional[BaseStore] = None,
            previous_messages: Sequence[AnyMessage] = (),
        ) -> Dict[str, Any]:
            # Start with all previous messages (full conversation history)
            messages = list(previous_messages)

            # Apply pre_llm_hooks for message filtering before node execution
            temp_state: PlanExecuteState = {"messages": messages}  # type: ignore
            for hook in self._pre_llm_hooks:
                result = hook(temp_state, runtime_config or {}, store)  # type: ignore
                if inspect.iscoroutine(result):
                    temp_state = await result  # type: ignore
                else:
                    temp_state = result  # type: ignore
            messages = list(temp_state.get("messages", []))

            # Get step context
            step_id = execution_context.get("step_id", 0)
            step_instruction = execution_context.get("instructions", "")
            if not step_instruction:
                step_instruction = "Execute the requested operation."

            # Add step context if available
            step_context = execution_context.get("context", {})
            if step_context:
                context_str = "\n".join(f"{k}: {v}" for k, v in step_context.items())
                step_instruction = (
                    f"{step_instruction}\n\nAdditional Context:\n{context_str}"
                )

            # Use template to create enhanced prompt with step info
            enhanced_prompt = _NODE_ENHANCED_PROMPT_TEMPLATE.format(
                base_instruction=BASE_NODE_INSTRUCTION,
                node_system_prompt=node_config.system_prompt,
                step_id=step_id,
            )

            # Add system message
            system_message = SystemMessage(
                content=enhanced_prompt,
                name=self.agent_name,
            )

            # Add human message with step instruction
            human_message = HumanMessage(
                content=step_instruction,
                name=self.agent_name,
            )

            # Construct final message list: previous messages + system + instruction
            final_messages = messages + [system_message, human_message]
            initial_state = {"messages": final_messages}

            graph_config: RunnableConfig = cast(
                RunnableConfig, dict(runtime_config or {})
            )

            invoke_kwargs: Dict[str, Any] = {"config": graph_config}
            if store is not None:
                invoke_kwargs["store"] = store

            result_state = await node_agent.ainvoke(initial_state, **invoke_kwargs)
            final_messages_result = result_state.get("messages", [])

            # Get only the NEW messages generated by this node execution
            # (everything after the input messages we provided)
            new_messages = final_messages_result[len(final_messages) :]

            # Extract final text output from last AI message
            response_message = next(
                (msg for msg in reversed(new_messages) if isinstance(msg, AIMessage)),
                None,
            )
            text = response_message.text() if response_message else ""

            # Return both the text output and all new messages (including tool calls)
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


def build_plan_execute_subgraph(
    config: PlanExecuteSubgraphConfig,
) -> StateGraph:
    """Build a plan-and-execute subgraph with automatic filter, trim, and delete hooks.

    Args:
        config: Configuration for the subgraph

    Returns:
        StateGraph with built-in message filtering and cleanup
    """
    # Combine base prompt with specific prompt
    planner_prompt = DEFAULT_BASE_PLANNER_PROMPT_TEMPLATE.format(
        provider_planner_prompt=config.planner_prompt,
        format_instructions=PromptDrivenPlanExecuteGraph._parser.get_format_instructions(),
    )

    # Create common nodes
    filter_node = create_filter_messages_node(
        agent_name=config.agent_name,
        allow_memory_system_messages=True,
    )

    graph = PromptDrivenPlanExecuteGraph(
        provider_name=config.provider_name,
        agent_name=config.agent_name,
        planner_prompt=planner_prompt,
        node_configs=config.node_configs,
        llm=config.llm,
        finalizer_prompt=config.finalizer_prompt,
        pre_llm_hooks=[filter_node, trim_messages_node],
        end_graph_hooks=[],
    )

    return graph._graph
