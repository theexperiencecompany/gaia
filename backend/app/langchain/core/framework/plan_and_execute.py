import asyncio
import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    TypedDict,
    cast,
)

from app.langchain.llm.client import init_llm
from langchain_core.language_models import LanguageModelLike
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field


# Pydantic models for structured output
class PlanStep(BaseModel):
    """Individual step in the execution plan"""

    step_id: int = Field(description="Unique identifier for the step")
    node_name: str = Field(description="Name of the node to execute")
    instructions: str = Field(description="Detailed instructions for this step")
    context: str = Field(description="Additional context or parameters needed")
    dependencies: List[int] = Field(
        default=[], description="List of step IDs this step depends on"
    )


class ExecutionPlan(BaseModel):
    """Complete execution plan with all steps"""

    steps: List[PlanStep] = Field(description="List of execution steps in order")
    description: str = Field(description="Overall description of the plan")


class ExecutionResult(BaseModel):
    """Result from executing a single step"""

    step_id: int
    success: bool
    output: Any
    error: Optional[str] = None


@dataclass(frozen=True)
class PlanExecuteNodeConfig:
    """Configuration for prompt-driven execution nodes."""

    name: str
    description: str
    system_prompt: str


ExecutionContext = Dict[str, Any]
HumanMessageFormatter = Callable[[ExecutionContext], str]
TaskExtractor = Callable[[List[BaseMessage]], str]
ContextExtractor = Callable[[List[BaseMessage]], str]
QueryBuilder = Callable[[str, str], str]
ResponseBuilder = Callable[[Dict[str, Any]], AIMessage]


# State management
class PlanExecuteState(TypedDict):
    """State for the plan and execute graph"""

    # Input
    query: str
    manual_plan: Optional[ExecutionPlan]
    available_nodes: Dict[str, str]  # node_name -> description
    include_previous_outputs: bool

    # Planning phase
    plan: Optional[ExecutionPlan]

    # Execution phase
    current_step: int
    execution_results: List[ExecutionResult]
    completed_steps: List[int]
    ready_steps: List[int]  # Steps ready for execution (dependencies satisfied)
    pending_steps: List[int]  # Steps waiting on dependencies
    in_progress_steps: List[int]  # Steps currently executing
    step_execution_contexts: Dict[int, Dict[str, Any]]  # Execution contexts by step ID
    step_node_mappings: Dict[int, str]  # Maps step IDs to node names

    # Dynamic routing
    _next_node: Optional[str]  # Next node to route to
    _execution_context: Optional[Dict[str, Any]]  # Current execution context

    # Output
    final_result: Optional[Any]
    is_complete: bool


class PlanExecuteAgentState(TypedDict, total=False):
    """Generic agent state wrapper used by provider subgraphs."""

    messages: List[BaseMessage]
    metadata: Dict[str, Any]
    plan_execute_scratchpad: Dict[str, Any]


@dataclass(frozen=True)
class PlanExecuteSubgraphConfig:
    """Configuration required to build a provider-specific subgraph."""

    provider_name: str
    agent_name: str
    planner_prompt: str
    node_configs: Sequence[PlanExecuteNodeConfig]
    llm: LanguageModelLike
    history_window: int = 6
    human_message_formatter: Optional[HumanMessageFormatter] = None
    task_extractor: Optional[TaskExtractor] = None
    context_extractor: Optional[ContextExtractor] = None
    query_builder: Optional[QueryBuilder] = None
    response_builder: Optional[ResponseBuilder] = None


def _shorten_text(value: Any, max_length: int = 500) -> str:
    text = str(value).strip()
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."


def _format_previous_results(results: Iterable[Any]) -> str:
    lines: List[str] = []
    for result in results:
        if hasattr(result, "model_dump"):
            payload = result.model_dump()
        elif isinstance(result, dict):
            payload = result
        else:
            payload = {"output": str(result)}

        step_id = payload.get("step_id", "unknown")
        success = payload.get("success", True)
        output = _shorten_text(payload.get("output", ""), 350)
        status = "success" if success else "failed"
        lines.append(f"- Step {step_id} [{status}] {output}")

    return "\n".join(lines)


def _default_human_message_formatter(execution_context: ExecutionContext) -> str:
    instruction = str(execution_context.get("instructions", "")).strip()
    contextual_notes = str(execution_context.get("context", "")).strip()
    previous_results = execution_context.get("previous_results", [])

    sections: List[str] = []
    if instruction:
        sections.append(f"Instruction: {instruction}")
    if contextual_notes:
        sections.append(f"Additional context: {contextual_notes}")
    if previous_results:
        formatted = _format_previous_results(previous_results)
        if formatted:
            sections.append("Relevant previous results:\n" + formatted)

    if sections:
        return "\n\n".join(sections)
    return "Execute the requested operation."


def _coerce_message_content(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "\n".join(parts).strip()
    return str(content).strip()


def _build_plan_error(provider_name: str, error_message: str) -> Dict[str, Any]:
    return {
        "provider": provider_name,
        "plan_description": f"{provider_name} plan execution failed",
        "total_steps": 0,
        "completed_steps": 0,
        "successful_steps": 0,
        "failed_steps": 0,
        "results": [],
        "error": error_message,
    }


def _format_step_lines(results: Iterable[Any]) -> List[str]:
    lines: List[str] = []
    for entry in results:
        if hasattr(entry, "model_dump"):
            payload = entry.model_dump()
        elif isinstance(entry, dict):
            payload = entry
        else:
            payload = {"output": str(entry)}

        step_id = payload.get("step_id", "?")
        node_name = payload.get("node", "unknown")
        success = payload.get("success", True)
        output = _shorten_text(payload.get("output", ""), 350)
        status = "success" if success else "failed"
        lines.append(f"- Step {step_id} ({node_name}) [{status}]: {output}")

    return lines


def _summarize_plan_result(provider_name: str, plan_result: Dict[str, Any]) -> str:
    if not plan_result:
        return f"The {provider_name} subagent did not return any results."

    description = plan_result.get(
        "plan_description", f"{provider_name} plan results"
    ).strip()
    successful = plan_result.get("successful_steps", 0)
    failed = plan_result.get("failed_steps", 0)
    total = plan_result.get("total_steps", successful + failed)
    lines = [description]
    lines.append(f"Steps: {successful} succeeded, {failed} failed, {total} total")

    step_lines = _format_step_lines(plan_result.get("results", []))
    if step_lines:
        lines.append("Step results:")
        lines.extend(step_lines)

    error_text = plan_result.get("error")
    if error_text:
        lines.append(f"Error: {error_text}")

    content = "\n".join(line for line in lines if line).strip()
    if not content:
        return f"{provider_name} subagent completed without additional details."
    return content


def _default_task_extractor(agent_name: str) -> TaskExtractor:
    def extractor(messages: List[BaseMessage]) -> str:
        for message in reversed(messages):
            if isinstance(message, HumanMessage) and (
                message.name is None or message.name == agent_name
            ):
                instruction = message.text()
                if instruction:
                    return instruction
        return ""

    return extractor


def _default_context_extractor(
    agent_name: str, history_window: int
) -> ContextExtractor:
    def extractor(messages: List[BaseMessage]) -> str:
        if not messages:
            return ""

        context_entries: List[str] = []
        for message in messages[-history_window:]:
            if isinstance(message, ToolMessage):
                continue
            if isinstance(message, HumanMessage) and message.name == agent_name:
                continue
            if isinstance(message, SystemMessage) and message.name == agent_name:
                continue

            content = _coerce_message_content(message)
            if not content:
                continue

            speaker = message.name or (
                message.__class__.__name__.replace("Message", "").lower()
            )
            context_entries.append(f"{speaker}: {content}")

        return "\n".join(context_entries).strip()

    return extractor


def _default_query_builder(task: str, context: str) -> str:
    task = task.strip()
    context = context.strip()
    if not task:
        return context
    if context:
        return f"Task:\n{task}\n\nConversation Context:\n{context}"
    return task


def _default_response_builder(provider_name: str, agent_name: str) -> ResponseBuilder:
    def builder(plan_result: Dict[str, Any]) -> AIMessage:
        content = _summarize_plan_result(provider_name, plan_result)
        return AIMessage(
            content=content,
            name=agent_name,
            additional_kwargs={"plan_result": plan_result},
        )

    return builder


class FlexiblePlanExecuteGraph(ABC):
    """
    A flexible and reusable Plan and Execute graph using LangGraph
    Abstract base class that can be extended for different implementations
    """

    def __init__(
        self,
        provider_name: str,
        *,
        llm: Optional[LanguageModelLike] = None,
    ):
        """
        Initialize the Plan and Execute graph

        Args:
            provider_name: Name of the provider implementing this framework
        """

        self.llm = llm or init_llm()
        self.provider_name = provider_name
        self.specialized_nodes: Dict[str, Callable] = {}
        self._initialize_operation_nodes()
        self.graph = self._build_parallel_graph()

    @abstractmethod
    def _initialize_operation_nodes(self):
        """Initialize the operation nodes for this provider. Must be implemented by subclasses."""
        pass

    @abstractmethod
    def get_planner_prompt(self) -> str:
        """Get the planner system prompt. Must be implemented by subclasses."""
        pass

    def register_operation_node(self, name: str, func: Callable, description: str):
        """Register an operation node with name, function and description"""
        self.specialized_nodes[name] = func
        # Update the graph with the new node
        self.graph = self._build_parallel_graph()

    def get_available_nodes(self) -> Dict[str, str]:
        """Get available operation nodes with descriptions"""
        return {
            name: f"Specialized node for {name}"
            for name in self.specialized_nodes.keys()
        }

    def _planning_step(self, state: PlanExecuteState) -> PlanExecuteState:
        """Planning phase - create or use manual plan"""
        # Use manual plan if provided
        if state.get("manual_plan"):
            state["plan"] = state["manual_plan"]
            state["current_step"] = 0
            self._prepare_step_execution(state)
            return state

        # Generate plan using LLM
        if not self.llm:
            raise ValueError("LLM required for automatic planning")

        # Prepare available nodes description
        nodes_description = "\n".join(
            [f"- {name}: {desc}" for name, desc in state["available_nodes"].items()]
        )

        # Set up the PydanticOutputParser
        parser = PydanticOutputParser(pydantic_object=ExecutionPlan)
        format_instructions = parser.get_format_instructions()

        # Create template with parser instructions integrated
        template = PromptTemplate(
            template="{planner_prompt}\n\n{format_instructions}",
            input_variables=["planner_prompt"],
            partial_variables={"format_instructions": format_instructions},
        )

        # Format planner prompt
        planner_prompt = self.get_planner_prompt().format(
            provider_name=self.provider_name,
            available_nodes=nodes_description,
            query=state["query"],
        )

        # Apply template to integrate format instructions
        formatted_prompt = template.format(planner_prompt=planner_prompt)

        # Format prompt with parser instructions
        messages = [
            SystemMessage(content=formatted_prompt),
            HumanMessage(content=f"User Request: {state['query']}"),
        ]

        # Get plan from LLM
        raw_response = self.llm.invoke(messages)
        content = self._extract_content(raw_response)

        # Parse the plan using the PydanticOutputParser
        plan = parser.parse(content)
        state["plan"] = plan

        # Initialize execution tracking
        state["current_step"] = 0
        self._prepare_step_execution(state)

        return state

    def _extract_content(self, response) -> str:
        """Extract content from LLM response."""
        if isinstance(response, str):
            return response
        elif hasattr(response, "content"):
            return response.content
        else:
            return str(response)

    def _prepare_step_execution(self, state: PlanExecuteState) -> None:
        """Prepare step execution by identifying ready and pending steps"""
        plan = state["plan"]
        if not plan:
            return

        # Initialize tracking structures
        state["ready_steps"] = []
        state["pending_steps"] = []
        state["in_progress_steps"] = []
        state["step_execution_contexts"] = {}
        state["step_node_mappings"] = {}

        # Identify ready and pending steps
        for step in plan.steps:
            # Map step ID to node name for execution routing
            state["step_node_mappings"][step.step_id] = step.node_name

            # Prepare execution context
            execution_context = {
                "instructions": step.instructions,
                "context": step.context,
                "step_id": step.step_id,
                "dependencies": step.dependencies,
            }
            state["step_execution_contexts"][step.step_id] = execution_context

            # Determine if step is ready or pending
            if not step.dependencies or all(
                dep in state["completed_steps"] for dep in step.dependencies
            ):
                state["ready_steps"].append(step.step_id)
            else:
                state["pending_steps"].append(step.step_id)

    def _execution_step(self, state: PlanExecuteState) -> PlanExecuteState:
        """Main execution coordinator"""
        plan = state.get("plan")
        if not plan:
            state["is_complete"] = True
            return state

        # Check if all steps are completed
        total_steps = len(plan.steps)
        completed_count = len(state.get("completed_steps", []))

        if completed_count >= total_steps:
            state["is_complete"] = True
            return state

        # Update ready steps based on completed dependencies
        self._update_ready_steps(state)

        # If we have ready steps, execute one of them
        ready_steps = state.get("ready_steps", [])
        if ready_steps:
            # Get the first ready step
            step_id = ready_steps[0]

            # Move from ready to in-progress
            state["ready_steps"].remove(step_id)
            state["in_progress_steps"].append(step_id)

            # Get the node name for this step
            node_name = state["step_node_mappings"].get(step_id)
            if not node_name:
                raise ValueError(f"No node mapping for step {step_id}")

            # Get execution context
            execution_context = state["step_execution_contexts"].get(step_id, {})

            # Add previous outputs if configured
            if state["include_previous_outputs"]:
                # Get results from dependency steps
                dependencies = execution_context.get("dependencies", [])
                execution_context["previous_results"] = [
                    result
                    for result in state.get("execution_results", [])
                    if result.step_id in dependencies
                ]

            # Set routing information
            state["_next_node"] = node_name
            state["_execution_context"] = execution_context

            return state
        else:
            # No ready steps available, either we're done or waiting on dependencies
            pending_steps = state.get("pending_steps", [])
            in_progress = state.get("in_progress_steps", [])

            if not pending_steps and not in_progress and completed_count < total_steps:
                # This is an error state - we have steps that can't be executed
                raise ValueError(
                    f"Execution deadlock: {total_steps - completed_count} steps remaining but none ready or in progress"
                )

        return state

    def _update_ready_steps(self, state: PlanExecuteState) -> None:
        """Update which steps are ready based on completed dependencies"""
        completed_steps = state.get("completed_steps", [])
        pending_steps = state.get("pending_steps", [])

        # Check pending steps to see if any are now ready
        newly_ready = []
        still_pending = []

        for step_id in pending_steps:
            dependencies = (
                state["step_execution_contexts"]
                .get(step_id, {})
                .get("dependencies", [])
            )
            if all(dep in completed_steps for dep in dependencies):
                newly_ready.append(step_id)
            else:
                still_pending.append(step_id)

        # Update state
        state["pending_steps"] = still_pending
        state["ready_steps"].extend(newly_ready)

    def _create_node_wrapper(self, node_name: str) -> Callable:
        """Create a wrapper for specialized nodes"""

        def node_wrapper(state: PlanExecuteState) -> PlanExecuteState:
            execution_context = state.get("_execution_context") or {}
            node_func = self.specialized_nodes[node_name]
            step_id = execution_context.get("step_id")

            if not step_id:
                raise ValueError(
                    f"Missing step_id in execution context for {node_name}"
                )

            try:
                result = node_func(execution_context)
                if inspect.isawaitable(result):
                    loop = asyncio.new_event_loop()
                    try:
                        result = loop.run_until_complete(result)  # type: ignore[assignment]
                    finally:
                        loop.close()

                execution_result = ExecutionResult(
                    step_id=step_id,
                    success=True,
                    output=result,
                    error=None,
                )

                state["execution_results"].append(execution_result)
            except Exception as error:
                execution_result = ExecutionResult(
                    step_id=step_id,
                    success=False,
                    output=None,
                    error=str(error),
                )
                state["execution_results"].append(execution_result)
            finally:
                state["completed_steps"].append(step_id)

                if step_id in state.get("in_progress_steps", []):
                    state["in_progress_steps"].remove(step_id)

                state["_execution_context"] = None

            return state

        return node_wrapper

    def _should_continue_execution(self, state: PlanExecuteState) -> str:
        """Determine next step in execution with support for parallel execution"""
        # If execution is complete, finalize
        if state.get("is_complete", False):
            return "finalize"

        # Route to specific node if set for current step
        if state.get("_next_node"):
            next_node = state["_next_node"]
            state["_next_node"] = None  # Clear the routing
            return next_node if next_node else "continue"

        # Otherwise continue with execution coordinator
        return "continue"

    def _finalization_step(self, state: PlanExecuteState) -> PlanExecuteState:
        """Finalize the execution and compile results"""
        plan = state.get("plan")
        if not plan:
            state["final_result"] = {"error": "No execution plan was created"}
            state["is_complete"] = True
            return state

        # Compile final result from all execution results
        all_results = state.get("execution_results", [])
        successful_results = [r for r in all_results if r.success]
        failed_results = [r for r in all_results if not r.success]

        # Simplified but comprehensive final result
        final_result = {
            "provider": self.provider_name,
            "plan_description": plan.description,
            "total_steps": len(plan.steps),
            "completed_steps": len(state.get("completed_steps", [])),
            "successful_steps": len(successful_results),
            "failed_steps": len(failed_results),
            "results": [
                {
                    "step_id": r.step_id,
                    "node": state["step_node_mappings"].get(r.step_id, "unknown"),
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

    def _build_parallel_graph(self):
        """Build the LangGraph workflow with support for parallel execution"""
        workflow = StateGraph(PlanExecuteState)

        # Add core planning and execution nodes
        workflow.add_node("planner", self._planning_step)
        workflow.add_node("executor", self._execution_step)
        workflow.add_node("finalizer", self._finalization_step)

        # Add specialized nodes
        for node_name in self.specialized_nodes.keys():
            workflow.add_node(node_name, self._create_node_wrapper(node_name))

        # Define workflow edges
        workflow.set_entry_point("planner")
        workflow.add_edge("planner", "executor")

        # Conditional edges from executor
        workflow.add_conditional_edges(
            "executor",
            self._should_continue_execution,
            {
                "continue": "executor",
                "finalize": "finalizer",
                **{node_name: node_name for node_name in self.specialized_nodes.keys()},
            },
        )

        # Add edges from specialized nodes back to executor
        for node_name in self.specialized_nodes.keys():
            workflow.add_edge(node_name, "executor")

        workflow.add_edge("finalizer", END)

        return workflow.compile()

    def execute(
        self,
        query: str,
        manual_plan: Optional[ExecutionPlan] = None,
        include_previous_outputs: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute the plan and execute workflow

        Args:
            query: The task query to plan and execute
            manual_plan: Optional pre-defined plan to use instead of LLM planning
            include_previous_outputs: Whether to include previous step outputs in context

        Returns:
            Final execution results
        """
        # Get node descriptions
        available_nodes = {}
        for name in self.specialized_nodes.keys():
            # For each node, create a descriptive entry
            available_nodes[name] = f"Specialized node for {name}"

        # Prepare initial state with empty tracking structures
        # Initialize with properly formatted dict
        initial_state = {
            "query": query,
            "manual_plan": manual_plan,
            "available_nodes": available_nodes,
            "include_previous_outputs": include_previous_outputs,
            "plan": None,
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
            "final_result": None,
            "is_complete": False,
        }

        # Execute the graph
        # Cast initial state to PlanExecuteState for type compatibility
        typed_state = cast(PlanExecuteState, initial_state)
        result = self.graph.invoke(typed_state)
        return result["final_result"]


class PromptDrivenPlanExecuteGraph(FlexiblePlanExecuteGraph):
    """Plan/execute graph that uses prompt-driven operation nodes."""

    def __init__(
        self,
        provider_name: str,
        planner_prompt: str,
        *,
        node_configs: Sequence[PlanExecuteNodeConfig],
        llm: Optional[LanguageModelLike] = None,
        human_message_formatter: Optional[HumanMessageFormatter] = None,
    ):
        self._planner_prompt = planner_prompt
        self._node_configs = list(node_configs)
        self._human_message_formatter = (
            human_message_formatter or _default_human_message_formatter
        )
        super().__init__(provider_name=provider_name, llm=llm)

    def _initialize_operation_nodes(self):
        for config in self._node_configs:
            self.register_operation_node(
                name=config.name,
                func=self._create_prompt_node(config),
                description=config.description,
            )

    def get_planner_prompt(self) -> str:
        return self._planner_prompt

    def _create_prompt_node(
        self, node_config: PlanExecuteNodeConfig
    ) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
        def node(execution_context: Dict[str, Any]) -> Dict[str, Any]:
            human_content = self._human_message_formatter(execution_context).strip()
            if not human_content:
                human_content = "Execute the requested operation."

            messages = [
                SystemMessage(content=node_config.system_prompt),
                HumanMessage(content=human_content),
            ]

            try:
                response = self.llm.invoke(messages)
                result_text = (
                    response.text()
                    if isinstance(response, BaseMessage)
                    else str(response)
                )
                return {"output": result_text, "success": True}
            except Exception as exc:  # pragma: no cover - external service dependency
                error_text = str(exc)
                return {"output": error_text, "success": False, "error": error_text}

        return node


def build_plan_execute_subgraph(
    config: PlanExecuteSubgraphConfig,
) -> CompiledStateGraph:
    """Compile a provider-specific plan/execute subgraph using shared utilities."""

    graph = PromptDrivenPlanExecuteGraph(
        provider_name=config.provider_name,
        planner_prompt=config.planner_prompt,
        node_configs=config.node_configs,
        llm=config.llm,
        human_message_formatter=config.human_message_formatter,
    )

    task_extractor = config.task_extractor or _default_task_extractor(config.agent_name)
    context_extractor = config.context_extractor or _default_context_extractor(
        config.agent_name, config.history_window
    )
    query_builder = config.query_builder or _default_query_builder
    response_builder = config.response_builder or _default_response_builder(
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
            plan_result = _build_plan_error(
                config.provider_name,
                f"Missing task description for {config.provider_name.lower()} subagent",
            )
        else:
            try:
                plan_result = graph.execute(
                    query=query,
                    include_previous_outputs=True,
                )
            except Exception as exc:  # pragma: no cover - external service dependency
                plan_result = _build_plan_error(config.provider_name, str(exc))

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
