"""Shared plan-and-execute framework for provider specific subgraphs."""

from __future__ import annotations

import asyncio
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
    Tuple,
    TypedDict,
    Union,
    cast,
)

from app.langchain.llm.client import init_llm
from langchain_core.language_models import LanguageModelLike
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.utils.runnable import RunnableCallable
from pydantic import BaseModel, Field

from backend.app.utils.plan_and_execute_utils import (
    build_plan_error,
    default_context_extractor,
    default_human_message_formatter,
    default_query_builder,
    default_response_builder,
    default_task_extractor,
)


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
    query: str
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


@dataclass
class PlanExecuteNodeConfig:
    name: str
    description: str
    system_prompt: str
    tools: Optional[Sequence[Any]] = None


@dataclass
class PlanExecuteRunnableNode:
    name: str
    description: str
    runnable: Union[
        Callable[[ExecutionContext], Any],
        Callable[[ExecutionContext], Awaitable[Any]],
        RunnableCallable,
        CompiledStateGraph,
    ]


NodeDefinition = Union[
    PlanExecuteNodeConfig,
    PlanExecuteRunnableNode,
    RunnableCallable,
    CompiledStateGraph,
    Callable[[ExecutionContext], Any],
    Callable[[ExecutionContext], Awaitable[Any]],
]


@dataclass
class PlanExecuteSubgraphConfig:
    provider_name: str
    agent_name: str
    planner_prompt: str
    node_configs: Sequence[NodeDefinition]
    llm: Optional[LanguageModelLike] = None
    human_message_formatter: Optional[HumanMessageFormatter] = None
    task_extractor: Optional[TaskExtractor] = None
    context_extractor: Optional[ContextExtractor] = None
    query_builder: Optional[QueryBuilder] = None
    response_builder: Optional[ResponseBuilder] = None
    history_window: int = 6


class PromptDrivenPlanExecuteGraph:
    """LangGraph-backed planner/executor with support for prompt and runnable nodes."""

    NodeHandler = Callable[[ExecutionContext], Awaitable[Any]]

    def __init__(
        self,
        provider_name: str,
        planner_prompt: str,
        *,
        node_configs: Sequence[NodeDefinition],
        llm: Optional[LanguageModelLike] = None,
        human_message_formatter: Optional[HumanMessageFormatter] = None,
    ):
        self.provider_name = provider_name
        self._planner_prompt = planner_prompt
        self.llm = llm or init_llm()
        self._human_message_formatter = (
            human_message_formatter or default_human_message_formatter
        )
        self._nodes: Dict[str, PromptDrivenPlanExecuteGraph.NodeHandler] = {}
        self._node_descriptions: Dict[str, str] = {}

        for definition in node_configs:
            name, description, handler = self._resolve_node_definition(definition)
            if name in self._nodes:
                raise ValueError(f"Duplicate node name detected: {name}")
            self._nodes[name] = handler
            self._node_descriptions[name] = description

        self._graph = self._build_parallel_graph()

    async def _planning_step(self, state: PlanExecuteState) -> PlanExecuteState:
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

        query = state.get("query", "")
        planner_prompt = self._planner_prompt.format(
            provider_name=self.provider_name,
            available_nodes=nodes_description,
            query=query,
        )

        formatted_prompt = template.format(planner_prompt=planner_prompt)
        messages = [
            SystemMessage(content=formatted_prompt),
            HumanMessage(content=f"User Request: {query}"),
        ]

        metadata = state.get("metadata", {})
        raw_response = await self._invoke_llm(self.llm, messages, metadata)
        content = self._extract_content(raw_response)

        plan = parser.parse(content)
        state["plan"] = plan
        state["current_step"] = 0
        self._prepare_step_execution(state)
        return state

    def _extract_content(self, response: Any) -> str:
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
            state: PlanExecuteState, config: RunnableConfig
        ) -> PlanExecuteState:
            execution_context = state.get("_execution_context") or {}
            step_id = execution_context.get("step_id")

            if step_id is None:
                raise ValueError(
                    f"Missing step_id in execution context for {node_name}"
                )

            try:
                result = await node_func(execution_context)
                execution_result = ExecutionResult(
                    step_id=step_id, success=True, output=result
                )
                state.setdefault("execution_results", []).append(execution_result)
            except Exception as error:
                execution_result = ExecutionResult(
                    step_id=step_id, success=False, output=None, error=str(error)
                )
                state.setdefault("execution_results", []).append(execution_result)
            finally:
                state.setdefault("completed_steps", []).append(step_id)
                _ = config
                in_progress = state.get("in_progress_steps") or []
                if step_id in in_progress:
                    in_progress.remove(step_id)
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
            state["final_result"] = {"error": "No execution plan was created"}
            state["is_complete"] = True
            return state

        all_results = state.get("execution_results", [])
        final_result = {
            "provider": self.provider_name,
            "plan_description": plan.description,
            "total_steps": len(plan.steps),
            "completed_steps": len(state.get("completed_steps", [])),
            "successful_steps": len([r for r in all_results if r.success]),
            "failed_steps": len([r for r in all_results if not r.success]),
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

        state["final_result"] = final_result
        state["is_complete"] = True
        return state

    def _build_parallel_graph(self) -> CompiledStateGraph:
        workflow = StateGraph(PlanExecuteState)
        workflow.add_node("planner", self._planning_step)
        workflow.add_node("executor", self._execution_step)
        workflow.add_node("finalizer", self._finalization_step)

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

        workflow.add_edge("finalizer", END)

        return workflow.compile()

    async def aexecute(
        self,
        *,
        query: str,
        manual_plan: Optional[ExecutionPlan] = None,
        include_previous_outputs: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        state: PlanExecuteState = {
            "query": query,
            "manual_plan": manual_plan,
            "available_nodes": dict(self._node_descriptions),
            "include_previous_outputs": include_previous_outputs,
            "metadata": metadata or {},
            "current_step": 0,
            "execution_results": [],
            "completed_steps": [],
            "ready_steps": [],
            "pending_steps": [],
            "in_progress_steps": [],
            "step_execution_contexts": {},
            "step_node_mappings": {},
            "_next_node": None,
            "_execution_context": None,
            "is_complete": False,
        }

        result = await self._graph.ainvoke(state)
        return result.get("final_result", {})

    def execute(
        self,
        *,
        query: str,
        manual_plan: Optional[ExecutionPlan] = None,
        include_previous_outputs: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.aexecute(
                    query=query,
                    manual_plan=manual_plan,
                    include_previous_outputs=include_previous_outputs,
                    metadata=metadata,
                )
            )
        else:
            if loop.is_running():
                raise RuntimeError(
                    "execute() cannot be called inside an existing event loop; use aexecute() instead."
                )
            return loop.run_until_complete(
                self.aexecute(
                    query=query,
                    manual_plan=manual_plan,
                    include_previous_outputs=include_previous_outputs,
                    metadata=metadata,
                )
            )

    def _create_prompt_node(
        self, node_config: PlanExecuteNodeConfig
    ) -> PromptDrivenPlanExecuteGraph.NodeHandler:
        async def node(execution_context: ExecutionContext) -> Dict[str, Any]:
            human_content = self._human_message_formatter(execution_context).strip()
            if not human_content:
                human_content = "Execute the requested operation."

            messages = [
                SystemMessage(content=node_config.system_prompt),
                HumanMessage(content=human_content),
            ]

            metadata = execution_context.get("metadata", {})
            llm = self.llm

            if node_config.tools:
                llm = self._bind_tools(llm, node_config.tools)

            response = await self._invoke_llm(llm, messages, metadata)
            text = self._extract_content(response)
            return {"output": text, "success": True}

        return node

    def _resolve_node_definition(
        self,
        definition: NodeDefinition,
    ) -> Tuple[str, str, PromptDrivenPlanExecuteGraph.NodeHandler]:
        if isinstance(definition, PlanExecuteNodeConfig):
            handler = self._create_prompt_node(definition)
            return definition.name, definition.description, handler

        if isinstance(definition, PlanExecuteRunnableNode):
            handler = self._wrap_runnable(definition.runnable)
            return definition.name, definition.description, handler

        if isinstance(definition, RunnableCallable):
            name = getattr(definition, "name", None) or "runnable_node"
            description = getattr(definition, "description", "") or name
            handler = self._wrap_runnable(definition)
            return name, description, handler

        if isinstance(definition, CompiledStateGraph):
            name_attr = getattr(definition, "name", None)
            name = (
                name_attr
                if isinstance(name_attr, str) and name_attr
                else "compiled_subgraph"
            )
            description_attr = getattr(definition, "description", None)
            description = (
                description_attr
                if isinstance(description_attr, str) and description_attr
                else f"Subgraph node {name}"
            )
            handler = self._wrap_runnable(definition)
            return name, description, handler

        if callable(definition):
            name = getattr(definition, "__name__", "callable_node")
            description = (getattr(definition, "__doc__", "") or name).strip()
            handler = self._wrap_runnable(definition)
            return name, description, handler

        raise TypeError(f"Unsupported node definition: {definition!r}")

    def _wrap_runnable(
        self,
        runnable: Union[
            Callable[[ExecutionContext], Any],
            Callable[[ExecutionContext], Awaitable[Any]],
            RunnableCallable,
            CompiledStateGraph,
        ],
    ) -> PromptDrivenPlanExecuteGraph.NodeHandler:
        async def handler(execution_context: ExecutionContext) -> Any:
            if isinstance(runnable, RunnableCallable):
                return await runnable.ainvoke(execution_context)
            if isinstance(runnable, CompiledStateGraph):
                return await runnable.ainvoke(execution_context)

            result = runnable(execution_context)
            if inspect.isawaitable(result):
                return await result
            return result

        return handler

    def _bind_tools(self, llm: LanguageModelLike, tools: Sequence[Any]) -> Any:
        if not hasattr(llm, "bind_tools"):
            raise ValueError("Provided LLM does not support tool binding")

        normalized_tools = [self._normalize_tool(tool) for tool in tools]
        bindable_llm = cast(Any, llm)
        return bindable_llm.bind_tools(normalized_tools)

    def _normalize_tool(self, tool: Any) -> BaseTool:
        if isinstance(tool, BaseTool):
            return tool
        if callable(tool):
            return StructuredTool.from_function(tool)
        raise TypeError(f"Unsupported tool type: {type(tool)!r}")

    async def _invoke_llm(
        self,
        llm: Any,
        messages: List[BaseMessage],
        metadata: Dict[str, Any],
    ) -> Any:
        config: Optional[RunnableConfig] = None
        if metadata:
            config = {"metadata": metadata}
        if hasattr(llm, "ainvoke"):
            return await llm.ainvoke(messages, config=config)
        if config is not None:
            return llm.invoke(messages, config=config)
        return llm.invoke(messages)


def build_plan_execute_subgraph(
    config: PlanExecuteSubgraphConfig,
) -> CompiledStateGraph:
    graph = PromptDrivenPlanExecuteGraph(
        provider_name=config.provider_name,
        planner_prompt=config.planner_prompt,
        node_configs=config.node_configs,
        llm=config.llm,
        human_message_formatter=config.human_message_formatter,
    )

    task_extractor = config.task_extractor or default_task_extractor(config.agent_name)
    context_extractor = config.context_extractor or default_context_extractor(
        config.agent_name, config.history_window
    )
    query_builder = config.query_builder or default_query_builder
    response_builder = config.response_builder or default_response_builder(
        config.provider_name, config.agent_name
    )

    def prepare_state(state: PlanExecuteAgentState) -> PlanExecuteAgentState:
        messages = list(state.get("messages", []))
        task_description = task_extractor(messages)
        conversation_context = context_extractor(messages)
        query = query_builder(task_description, conversation_context)

        state["plan_execute_scratchpad"] = {
            "task": task_description,
            "context": conversation_context,
            "query": query,
        }
        return state

    def execute_plan(state: PlanExecuteAgentState) -> PlanExecuteAgentState:
        scratchpad = state.get("plan_execute_scratchpad", {})
        query = scratchpad.get("query", "").strip()

        if not query:
            plan_result = build_plan_error(
                config.provider_name,
                f"Missing task description for {config.provider_name.lower()} subagent",
            )
        else:
            try:
                plan_result = graph.execute(
                    query=query,
                    include_previous_outputs=True,
                )
            except Exception as exc:
                plan_result = build_plan_error(config.provider_name, str(exc))

        scratchpad["result"] = plan_result
        state["plan_execute_scratchpad"] = scratchpad
        return state

    def finalize(state: PlanExecuteAgentState) -> PlanExecuteAgentState:
        scratchpad = state.get("plan_execute_scratchpad", {})
        plan_result = scratchpad.get("result", {})
        response_message = response_builder(plan_result)

        messages = list(state.get("messages", []))
        messages.append(response_message)
        state["messages"] = messages

        state.pop("plan_execute_scratchpad", None)
        return state

    builder = StateGraph(PlanExecuteAgentState)
    builder.add_node("prepare", prepare_state)
    builder.add_node("plan_execute", execute_plan)
    builder.add_node("finalize", finalize)

    builder.set_entry_point("prepare")
    builder.add_edge("prepare", "plan_execute")
    builder.add_edge("plan_execute", "finalize")

    return builder.compile(checkpointer=False, name=config.agent_name)
