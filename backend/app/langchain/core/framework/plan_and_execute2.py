from typing import Annotated, Any, Callable, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph, add_messages
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
    execution_time: Optional[float] = None


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
    execution_results: Annotated[List[ExecutionResult], add_messages]
    completed_steps: List[int]

    # Output
    final_result: Optional[Any]
    is_complete: bool


class FlexiblePlanExecuteGraph:
    """
    A flexible and reusable Plan and Execute graph using LangGraph
    """

    def __init__(
        self,
        specialized_nodes: Dict[str, Callable],
        default_planner_prompt: str,
        llm: Any,
    ):
        """
        Initialize the Plan and Execute graph

        Args:
            llm: Language model for planning (optional if using manual plans)
            specialized_nodes: Dictionary of available execution nodes
            default_planner_prompt: Custom planner prompt template
        """
        self.llm = llm
        self.specialized_nodes = specialized_nodes or {}
        self.planner_prompt = default_planner_prompt or self._default_planner_prompt()
        self.graph = self._build_graph()

    def _default_planner_prompt(self) -> str:
        """Default prompt template for the planner"""
        return """
You are an expert task planner. Create a detailed execution plan for the given query.

Available specialized nodes and their capabilities:
{available_nodes}

Requirements:
1. Break down the task into clear, sequential steps
2. Each step must use one of the available nodes
3. Provide detailed instructions and context for each step
4. Consider dependencies between steps
5. Be specific about what each step should accomplish

Query: {query}

Create a comprehensive plan that efficiently uses the available nodes to accomplish the task.
"""

    def add_specialized_node(self, name: str, func: Callable, description: str):
        """Add a new specialized execution node"""
        self.specialized_nodes[name] = func
        # Rebuild graph to include new node
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow"""
        workflow = StateGraph(PlanExecuteState)

        # Add nodes
        workflow.add_node("planner", self._planning_step)
        workflow.add_node("executor", self._execution_step)
        workflow.add_node("finalizer", self._finalization_step)

        # Add specialized nodes
        for node_name in self.specialized_nodes.keys():
            workflow.add_node(node_name, self._create_node_wrapper(node_name))

        # Define edges
        workflow.set_entry_point("planner")
        workflow.add_edge("planner", "executor")

        # Conditional edges from executor
        workflow.add_conditional_edges(
            "executor",
            self._should_continue_execution,
            {
                "continue": "executor",
                "execute_node": "executor",  # This will be dynamically routed
                "finalize": "finalizer",
            },
        )

        # Add edges from specialized nodes back to executor
        for node_name in self.specialized_nodes.keys():
            workflow.add_edge(node_name, "executor")

        workflow.add_edge("finalizer", END)

        return workflow.compile()

    def _planning_step(self, state: PlanExecuteState) -> PlanExecuteState:
        """Planning phase - create or use manual plan"""

        # Use manual plan if provided
        if state.get("manual_plan"):
            state["plan"] = state["manual_plan"]
            state["current_step"] = 0
            return state

        # Generate plan using LLM
        if not self.llm:
            raise ValueError("LLM required for automatic planning")

        # Prepare available nodes description
        nodes_description = "\n".join(
            [f"- {name}: {desc}" for name, desc in state["available_nodes"].items()]
        )

        # Format prompt
        formatted_prompt = self.planner_prompt.format(
            available_nodes=nodes_description, query=state["query"]
        )

        # Get structured output from LLM
        try:
            # This would use your LLM with structured output
            # Example implementation:
            response = self.llm.with_structured_output(ExecutionPlan).invoke(
                formatted_prompt
            )
            state["plan"] = response
            state["current_step"] = 0
        except Exception as e:
            # Fallback to manual parsing if structured output fails
            raw_response = self.llm.invoke(formatted_prompt)
            state["plan"] = self._parse_plan_from_text(
                raw_response.content, state["available_nodes"]
            )
            state["current_step"] = 0

        return state

    def _execution_step(self, state: PlanExecuteState) -> PlanExecuteState:
        """Main execution coordinator"""
        plan = state["plan"]
        current_step = state["current_step"]

        # Check if all steps are completed
        if current_step >= len(plan.steps):
            state["is_complete"] = True
            return state

        # Get current step
        step = plan.steps[current_step]

        # Check dependencies
        if not all(dep_id in state["completed_steps"] for dep_id in step.dependencies):
            # Skip this step for now, try next one
            state["current_step"] += 1
            return state

        # Prepare context for execution
        execution_context = {
            "instructions": step.instructions,
            "context": step.context,
            "step_id": step.step_id,
        }

        # Add previous outputs if configured
        if state["include_previous_outputs"]:
            execution_context["previous_results"] = [
                result
                for result in state["execution_results"]
                if result.step_id in step.dependencies
            ]

        # Route to appropriate specialized node
        state["_next_node"] = step.node_name
        state["_execution_context"] = execution_context

        return state

    def _create_node_wrapper(self, node_name: str) -> Callable:
        """Create a wrapper for specialized nodes"""

        def node_wrapper(state: PlanExecuteState) -> PlanExecuteState:
            execution_context = state.get("_execution_context", {})
            node_func = self.specialized_nodes[node_name]

            try:
                # Execute the specialized node
                result = node_func(execution_context)

                # Record execution result
                execution_result = ExecutionResult(
                    step_id=execution_context["step_id"], success=True, output=result
                )

                state["execution_results"].append(execution_result)
                state["completed_steps"].append(execution_context["step_id"])
                state["current_step"] += 1

            except Exception as e:
                # Record execution failure
                execution_result = ExecutionResult(
                    step_id=execution_context["step_id"],
                    success=False,
                    output=None,
                    error=str(e),
                )

                state["execution_results"].append(execution_result)
                # Still mark as completed but with error
                state["completed_steps"].append(execution_context["step_id"])
                state["current_step"] += 1

            return state

        return node_wrapper

    def _should_continue_execution(self, state: PlanExecuteState) -> str:
        """Determine next step in execution"""
        if state.get("is_complete", False):
            return "finalize"

        # Route to specific node if set
        if state.get("_next_node"):
            next_node = state["_next_node"]
            state["_next_node"] = None  # Clear the routing
            return next_node

        return "continue"

    def _finalization_step(self, state: PlanExecuteState) -> PlanExecuteState:
        """Finalize the execution and compile results"""

        # Compile final result from all execution results
        successful_results = [r for r in state["execution_results"] if r.success]
        failed_results = [r for r in state["execution_results"] if not r.success]

        final_result = {
            "plan_description": state["plan"].description,
            "total_steps": len(state["plan"].steps),
            "successful_steps": len(successful_results),
            "failed_steps": len(failed_results),
            "results": [r.output for r in successful_results],
            "errors": [r.error for r in failed_results if r.error],
        }

        state["final_result"] = final_result
        state["is_complete"] = True

        return state

    def _parse_plan_from_text(
        self, text: str, available_nodes: Dict[str, str]
    ) -> ExecutionPlan:
        """Fallback parser for plan text when structured output fails"""
        # This is a simple implementation - you might want to make this more robust
        steps = []
        lines = text.strip().split("\n")

        step_id = 1
        for line in lines:
            line = line.strip()
            if line and any(node in line.lower() for node in available_nodes.keys()):
                # Try to extract node name
                node_name = None
                for node in available_nodes.keys():
                    if node.lower() in line.lower():
                        node_name = node
                        break

                if node_name:
                    steps.append(
                        PlanStep(
                            step_id=step_id,
                            node_name=node_name,
                            instructions=line,
                            context="Extracted from text",
                            dependencies=[],
                        )
                    )
                    step_id += 1

        return ExecutionPlan(steps=steps, description="Plan parsed from text")

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

        # Prepare initial state
        initial_state = PlanExecuteState(
            query=query,
            manual_plan=manual_plan,
            available_nodes={
                name: f"Specialized node for {name}"
                for name in self.specialized_nodes.keys()
            },
            include_previous_outputs=include_previous_outputs,
            plan=None,
            current_step=0,
            execution_results=[],
            completed_steps=[],
            final_result=None,
            is_complete=False,
        )

        # Execute the graph
        result = self.graph.invoke(initial_state)
        return result["final_result"]
