import asyncio
import inspect
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, TypedDict, cast

from app.langchain.llm.client import init_llm
from langchain_core.language_models import LanguageModelLike
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.graph import END, StateGraph
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
