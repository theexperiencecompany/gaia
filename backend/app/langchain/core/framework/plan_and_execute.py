"""Shared plan-and-execute framework for provider specific subgraphs."""

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

from app.agents.llm.client import init_llm
from app.utils.plan_and_execute_utils import default_human_message_formatter
from langchain_core.language_models import LanguageModelLike
from langchain_core.language_models.chat_models import (
    BaseChatModel,
)
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import create_react_agent
from langgraph.store.base import BaseStore
from pydantic import BaseModel, Field

DEFAULT_BASE_PLANNER_PROMPT = """
You are a planning agent that creates execution plans for {provider_name} operations.

PLANNING SPECIFICATIONS:
1. Break down the user request into discrete, executable steps
2. Each step should target a specific node based on its capabilities
3. Steps can have dependencies on previous steps (use step_id references)
4. Include relevant context for each step
5. Ensure steps are logically ordered and dependencies are correctly specified

Create a detailed execution plan with clear step descriptions and proper node assignments.
"""


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
    dependencies: List[int] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    description: str = ""
    steps: List[ExecutionStep] = Field(default_factory=list)


class ExecutionContext(TypedDict, total=False):
    instructions: str
    context: Dict[str, Any]
    step_id: int
    dependencies: List[int]
    metadata: Dict[str, Any]
    previous_results: List[ExecutionResult]


class PlanExecuteState(TypedDict, total=False):
    messages: List[BaseMessage]
    manual_plan: Optional[ExecutionPlan]
    available_nodes: Dict[str, str]
    include_previous_outputs: bool
    metadata: Dict[str, Any]
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


HumanMessageFormatter = Callable[[ExecutionContext], str]
TaskExtractor = Callable[[Sequence[BaseMessage]], str]
ContextExtractor = Callable[[Sequence[BaseMessage]], str]
QueryBuilder = Callable[[str, str], str]
ResponseBuilder = Callable[[Dict[str, Any]], BaseMessage]

HookType = Union[
    Callable[[PlanExecuteState, RunnableConfig, BaseStore], PlanExecuteState],
    Callable[
        [PlanExecuteState, RunnableConfig, BaseStore], Awaitable[PlanExecuteState]
    ],
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
    human_message_formatter: Optional[HumanMessageFormatter] = None
    task_extractor: Optional[TaskExtractor] = None
    context_extractor: Optional[ContextExtractor] = None
    query_builder: Optional[QueryBuilder] = None
    response_builder: Optional[ResponseBuilder] = None
    history_window: int = 6
    base_planner_prompt: Optional[str] = None
    pre_plan_hooks: Optional[List[HookType]] = None
    end_graph_hooks: Optional[List[HookType]] = None


class PromptDrivenPlanExecuteGraph:
    """LangGraph-backed planner/executor with support for prompt and runnable nodes."""

    NodeHandler = Callable[
        [ExecutionContext, Optional[RunnableConfig], Optional[BaseStore]],
        Awaitable[Any],
    ]

    def __init__(
        self,
        provider_name: str,
        agent_name: str,
        planner_prompt: str,
        *,
        node_configs: Sequence[PlanExecuteNodeConfig],
        llm: Optional[LanguageModelLike] = None,
        human_message_formatter: Optional[HumanMessageFormatter] = None,
        pre_plan_hooks: Optional[List[HookType]] = None,
        end_graph_hooks: Optional[List[HookType]] = None,
    ):
        self.provider_name = provider_name
        self.agent_name = agent_name
        self._planner_prompt = planner_prompt
        self.llm = llm or init_llm()
        self._human_message_formatter = (
            human_message_formatter or default_human_message_formatter
        )
        self._pre_plan_hooks = pre_plan_hooks or []
        self._end_graph_hooks = end_graph_hooks or []
        self._nodes: Dict[str, PromptDrivenPlanExecuteGraph.NodeHandler] = {}
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
        for hook in self._pre_plan_hooks:
            result = hook(state, config, store)
            if inspect.iscoroutine(result):
                state = await result  # type: ignore
            else:
                state = result  # type: ignore

        manual_plan = state.get("manual_plan")
        if manual_plan is not None:
            state["plan"] = manual_plan
            state["current_step"] = 0
            self._prepare_step_execution(state)
            return state

        available_nodes = state.get("available_nodes") or {}
        nodes_description = "\n".join(
            f"- {name}: {desc}" for name, desc in available_nodes.items()
        )

        parser = PydanticOutputParser(pydantic_object=ExecutionPlan)
        format_instructions = parser.get_format_instructions()

        template = PromptTemplate(
            template="{planner_prompt}\n\n{format_instructions}",
            input_variables=["planner_prompt"],
            partial_variables={"format_instructions": format_instructions},
        )

        planner_prompt = self._planner_prompt.format(
            provider_name=self.provider_name,
            available_nodes=nodes_description,
        )

        formatted_prompt = template.format(planner_prompt=planner_prompt)

        state["messages"][-2] = SystemMessage(content=formatted_prompt)  # type: ignore

        metadata = state.get("metadata", {})
        raw_response = await self._invoke_llm(self.llm, state["messages"], metadata)  # type: ignore
        content = self._extract_content(raw_response)

        plan = parser.parse(content)
        state["plan"] = plan
        state["current_step"] = 0
        self._prepare_step_execution(state)

        # Create planner output message with agent_name_planner for preservation
        planner_message = AIMessage(
            content=f"Created execution plan with {len(plan.steps)} steps",
            name=self.agent_name,
        )
        state.setdefault("messages", []).append(planner_message)

        return state

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

        metadata = state.get("metadata", {})

        for step in plan.steps:
            state["step_node_mappings"][step.step_id] = step.node_name

            execution_context: ExecutionContext = {
                "instructions": step.instructions,
                "context": step.context,
                "step_id": step.step_id,
                "dependencies": step.dependencies,
                "metadata": metadata,
            }
            state.setdefault("step_execution_contexts", {})[step.step_id] = (
                execution_context
            )

            if not step.dependencies or all(
                dep in state.get("completed_steps", []) for dep in step.dependencies
            ):
                state.setdefault("ready_steps", []).append(step.step_id)
            else:
                state.setdefault("pending_steps", []).append(step.step_id)

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

            if state.get("include_previous_outputs", True):
                dependencies = execution_context.get("dependencies", [])
                execution_context["previous_results"] = [
                    result
                    for result in state.get("execution_results", [])
                    if result.step_id in dependencies
                ]

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
        completed_steps = state.get("completed_steps", [])
        pending_steps = state.get("pending_steps", [])
        execution_contexts = state.get("step_execution_contexts") or {}

        newly_ready: List[int] = []
        still_pending: List[int] = []

        for step_id in pending_steps:
            dependencies = execution_contexts.get(step_id, {}).get("dependencies", [])
            if all(dep in completed_steps for dep in dependencies):
                newly_ready.append(step_id)
            else:
                still_pending.append(step_id)

        state["pending_steps"] = still_pending
        state.setdefault("ready_steps", []).extend(newly_ready)

    def _create_node_wrapper(
        self,
        node_name: str,
        node_func: PromptDrivenPlanExecuteGraph.NodeHandler,
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
                result = await node_func(ctx, config, store)
                execution_result = ExecutionResult(
                    step_id=step_id,
                    success=True,
                    output=result,
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

    def _finalization_step(self, state: PlanExecuteState) -> PlanExecuteState:
        plan = state.get("plan")
        if not plan:
            state["final_result"] = {"error": "No plan found"}
            state["is_complete"] = True
            return state

        all_results = state.get("execution_results", [])
        failed_steps = [r for r in all_results if not r.success]
        successful_steps = [r for r in all_results if r.success]

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
                    "node": (state.get("step_node_mappings") or {}).get(
                        r.step_id, "unknown"
                    ),
                    "success": r.success,
                    "output": r.output,
                    "error": r.error,
                }
                for r in all_results
            ],
        }

        # Create finalizer output message with agent_name_finalizer for preservation
        if failed_steps:
            status_msg = f"Plan execution completed with {len(failed_steps)} failed steps out of {len(all_results)} total steps"
        else:
            status_msg = (
                f"Plan execution completed successfully with {len(all_results)} steps"
            )

        finalizer_message = AIMessage(
            content=status_msg,
            name=self.agent_name,
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

    def _create_prompt_node(
        self, node_config: PlanExecuteNodeConfig
    ) -> PromptDrivenPlanExecuteGraph.NodeHandler:
        """Create a prompt-based node with tool call handling using create_react_agent."""
        tools: list[BaseTool] = list(node_config.tools or [])

        node_agent = create_react_agent(
            model=self.llm,
            tools=tools,
            prompt=node_config.system_prompt,
            name=f"{self.agent_name}_{node_config.name}",
        )

        async def node(
            execution_context: ExecutionContext,
            runtime_config: Optional[RunnableConfig] = None,
            store: Optional[BaseStore] = None,
        ) -> Dict[str, Any]:
            human_content = self._human_message_formatter(execution_context).strip()
            if not human_content:
                human_content = "Execute the requested operation."

            messages = [HumanMessage(content=human_content)]
            initial_state = {"messages": messages}

            graph_config: RunnableConfig = cast(
                RunnableConfig, dict(runtime_config or {})
            )
            metadata = execution_context.get("metadata") or {}
            if metadata:
                existing_metadata = graph_config.get("metadata") or {}
                graph_config["metadata"] = {**existing_metadata, **metadata}

                model_configurations = metadata.get("model_configurations")
                if isinstance(model_configurations, dict):
                    configurable_section = dict(graph_config.get("configurable") or {})
                    configurable_section["model_configurations"] = model_configurations
                    graph_config["configurable"] = configurable_section

            invoke_kwargs: Dict[str, Any] = {"config": graph_config}
            if store is not None:
                invoke_kwargs["store"] = store

            result_state = await node_agent.ainvoke(initial_state, **invoke_kwargs)
            final_messages = result_state.get("messages", [])
            response_message = next(
                (msg for msg in reversed(final_messages) if isinstance(msg, AIMessage)),
                None,
            )
            text = response_message.text() if response_message else ""
            return {"output": text, "success": True}

        return node

    def _bind_tools(self, llm, tools: Sequence[BaseTool]):
        if isinstance(llm, BaseChatModel):
            return llm.bind_tools(tools)

        raise ValueError("Provided LLM does not support tool binding")

    async def _invoke_llm(
        self,
        llm: LanguageModelLike,
        messages: List[BaseMessage],
        metadata: Dict[str, Any],
    ) -> BaseMessage | str:
        config: Optional[RunnableConfig] = None
        if metadata:
            config = {"metadata": metadata}
        return await llm.ainvoke(messages, config=config)


def build_plan_execute_subgraph(
    config: PlanExecuteSubgraphConfig,
) -> StateGraph:
    """Build a plan-and-execute subgraph.

    Args:
        config: Configuration for the subgraph

    Returns:
        CompiledStateGraph if config.return_compiled is True, otherwise StateGraph
    """
    # Use base prompt if provided, otherwise use the default base planner prompt
    base_prompt = config.base_planner_prompt
    if base_prompt is None:
        base_prompt = DEFAULT_BASE_PLANNER_PROMPT

    # Combine base prompt with specific prompt
    effective_prompt = f"{base_prompt}\n\n{config.planner_prompt}"

    graph = PromptDrivenPlanExecuteGraph(
        provider_name=config.provider_name,
        agent_name=config.agent_name,
        planner_prompt=effective_prompt,
        node_configs=config.node_configs,
        llm=config.llm,
        human_message_formatter=config.human_message_formatter,
        pre_plan_hooks=config.pre_plan_hooks,
        end_graph_hooks=config.end_graph_hooks,
    )

    return graph._graph
