"""
Modular Plan-and-Execute Framework for LangGraph Subgraphs.

This module provides a reusable, class-based framework for implementing
plan-and-execute patterns with specialized operation nodes.

Based on LangGraph plan-and-execute tutorial:
https://langchain-ai.github.io/langgraph/tutorials/plan-and-execute/plan-and-execute/
"""

import operator
from abc import ABC, abstractmethod
from typing import Annotated, Any, Dict, List, Union

from app.config.loggers import langchain_logger as logger
from langchain_core.language_models import LanguageModelLike
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


# Base State and Models
class PlanStep(BaseModel):
    """A single step in an execution plan."""

    node_name: str = Field(
        description="Name of the operation node to execute this step"
    )
    action_description: str = Field(description="Description of the action to perform")
    context: Dict[str, Any] = Field(
        default_factory=dict, description="Additional context for the step"
    )


class ExecutionPlan(BaseModel):
    """Execution plan containing sequential steps."""

    steps: List[PlanStep] = Field(description="Sequential steps to execute")


class ExecutionResult(BaseModel):
    """Result of executing a plan step."""

    step: PlanStep = Field(description="The executed step")
    result: str = Field(description="Result description")
    data: Dict[str, Any] = Field(
        default_factory=dict, description="Structured result data"
    )
    success: bool = Field(default=True, description="Whether execution was successful")


class PlanExecuteResponse(BaseModel):
    """Final response to user."""

    response: str = Field(description="Final response message to the user")


class PlanExecuteAction(BaseModel):
    """Next action to perform."""

    action: Union[PlanExecuteResponse, ExecutionPlan] = Field(
        description="Either respond to user or continue with execution plan"
    )


class BasePlanExecuteState(TypedDict):
    """Base state for plan-and-execute subgraphs."""

    input: str  # Original user request
    plan: List[PlanStep]  # Current execution plan steps
    past_steps: Annotated[
        List[ExecutionResult], operator.add
    ]  # Completed steps with results
    response: str  # Final response
    messages: List  # Message history for context
    available_nodes: Dict[str, str]  # Available operation nodes {name: description}


class OperationNode(ABC):
    """Abstract base class for specialized operation nodes."""

    def __init__(
        self, node_name: str, description: str, tools: List[str], llm: LanguageModelLike
    ):
        self.node_name = node_name
        self.description = description
        self.tools = tools
        self.llm = llm

    @abstractmethod
    def get_prompt(self) -> str:
        """Get the system prompt for this operation node."""
        pass

    async def execute(
        self, state: BasePlanExecuteState, config: RunnableConfig, *, store: BaseStore
    ) -> Dict[str, Any]:
        """Execute the operation node."""
        # Initialize variables
        current_step = None
        remaining_steps = []

        try:
            logger.info(f"{self.node_name} node executing")

            # Get current step context with previous results
            current_plan = state.get("plan", [])
            if not current_plan:
                return {"response": f"No steps to execute for {self.node_name}"}

            current_step = current_plan[0]
            remaining_steps = current_plan[1:]
            past_results = state.get("past_steps", [])

            # Build context from previous steps
            context = self._build_context(current_step, past_results)

            # Create messages for this node
            messages = [
                SystemMessage(content=self.get_prompt()),
                HumanMessage(
                    content=self._format_execution_message(current_step, context)
                ),
            ]

            # Add recent message context if available
            if state.get("messages"):
                messages.extend(state["messages"][-3:])

            # Execute with LLM
            response = await self.llm.ainvoke(messages)

            # Extract content from response
            content = self._extract_content(response)

            # Create execution result with enhanced data
            import datetime

            execution_result = ExecutionResult(
                step=current_step,
                result=content,
                data={
                    "node_name": self.node_name,
                    "timestamp": datetime.datetime.now().isoformat(),
                    "tools_used": self.tools,
                    "context_inherited": bool(context["previous_results"]),
                    "step_context": current_step.context,
                },
                success=True,
            )

            logger.info(f"{self.node_name} node completed successfully")

            return {
                "plan": remaining_steps,
                "past_steps": [execution_result],
                "messages": [response]
                if hasattr(response, "content")
                else [HumanMessage(content=content)],
            }

        except Exception as e:
            logger.error(f"{self.node_name} node error: {e}")

            # Create error result - handle case where current_step is None
            if current_step is None:
                current_step = PlanStep(
                    node_name=self.node_name,
                    action_description=f"Execute {self.node_name} operation",
                    context={},
                )

            error_result = ExecutionResult(
                step=current_step,
                result=f"Error in {self.node_name}: {str(e)}",
                data={"node_name": self.node_name, "error": str(e)},
                success=False,
            )

            return {
                "plan": remaining_steps,
                "past_steps": [error_result],
                "response": f"Error in {self.node_name}: {str(e)}",
            }

    def _build_context(
        self, current_step: PlanStep, past_results: List[ExecutionResult]
    ) -> Dict[str, Any]:
        """Build comprehensive context from previous step results."""
        context = {
            "current_action": current_step.action_description,
            "step_context": current_step.context,
            "previous_results": [],
            "relevant_data": {},
            "execution_chain": [],
        }

        # Add results from previous steps with full context
        for i, result in enumerate(past_results):
            step_info = {
                "step_number": i + 1,
                "node_name": result.data.get("node_name", "unknown"),
                "action": result.step.action_description,
                "result": result.result,
                "success": result.success,
                "data": result.data,
                "timestamp": result.data.get("timestamp", ""),
            }
            context["previous_results"].append(step_info)
            context["execution_chain"].append(
                f"Step {i + 1}: {result.step.action_description} -> {result.result}"
            )

            # Extract relevant data for context inheritance
            if result.success and result.data:
                for key, value in result.data.items():
                    if key not in ["node_name", "timestamp", "error"]:
                        context["relevant_data"][
                            f"{result.data.get('node_name', 'step')}_{key}"
                        ] = value

        return context

    def _format_execution_message(self, step: PlanStep, context: Dict[str, Any]) -> str:
        """Format comprehensive execution message with full context."""
        message = f"**Current Task:** {step.action_description}\n\n"

        # Add execution chain for context
        if context["execution_chain"]:
            message += "**Previous Execution Chain:**\n"
            for chain_item in context["execution_chain"][-3:]:  # Last 3 steps
                message += f"- {chain_item}\n"
            message += "\n"

        # Add detailed previous results
        if context["previous_results"]:
            message += "**Previous Step Results (for context):**\n"
            for prev in context["previous_results"][-2:]:  # Last 2 detailed results
                status = "✅ Success" if prev["success"] else "❌ Failed"
                message += f"**{prev['node_name']}** ({status}): {prev['action']}\n"
                message += f"  Result: {prev['result']}\n"
                if prev.get("data") and prev["success"]:
                    message += f"  Available data: {list(prev['data'].keys())}\n"
                message += "\n"

        # Add relevant inherited data
        if context["relevant_data"]:
            message += "**Available Context Data:**\n"
            for key, value in list(context["relevant_data"].items())[
                :5
            ]:  # Limit to 5 items
                message += f"- {key}: {str(value)[:100]}{'...' if len(str(value)) > 100 else ''}\n"
            message += "\n"

        # Add step-specific context
        if step.context:
            message += f"**Step Context:** {step.context}\n\n"

        message += "**Instructions:** Execute the current task using the context from previous steps. "
        message += "Leverage any relevant data or results from previous operations."

        return message.strip()

    def _extract_content(self, response) -> str:
        """Extract content from LLM response."""
        if isinstance(response, str):
            return response
        elif hasattr(response, "content"):
            return response.content
        else:
            return str(response)


class BasePlanAndExecute(ABC):
    """Base class for plan-and-execute subgraphs."""

    def __init__(self, llm: LanguageModelLike, provider_name: str):
        self.llm = llm
        self.provider_name = provider_name
        self.operation_nodes: Dict[str, OperationNode] = {}
        self._initialize_operation_nodes()

    @abstractmethod
    def _initialize_operation_nodes(self):
        """Initialize the operation nodes for this provider."""
        pass

    @abstractmethod
    def get_planner_prompt(self) -> str:
        """Get the planner system prompt."""
        pass

    def register_operation_node(self, node: OperationNode):
        """Register an operation node."""
        self.operation_nodes[node.node_name] = node
        logger.info(f"Registered operation node: {node.node_name}")

    def get_available_nodes(self) -> Dict[str, str]:
        """Get available operation nodes with descriptions."""
        return {name: node.description for name, node in self.operation_nodes.items()}

    async def plan_step(self, state: BasePlanExecuteState) -> Dict[str, Any]:
        """Plan execution steps based on user input."""
        try:
            logger.info(
                f"{self.provider_name} Planner analyzing request: {state['input']}"
            )

            # Create planner messages with available nodes context
            available_nodes_text = "\\n".join(
                [
                    f"- **{name}**: {desc}"
                    for name, desc in self.get_available_nodes().items()
                ]
            )

            planner_prompt = self.get_planner_prompt().format(
                provider_name=self.provider_name, available_nodes=available_nodes_text
            )

            messages = [
                SystemMessage(content=planner_prompt),
                HumanMessage(content=f"User Request: {state['input']}"),
            ]

            # Add memory context if available
            if state.get("messages"):
                messages.extend(state["messages"][-5:])

            # Get plan from LLM
            response = await self.llm.ainvoke(messages)
            content = self._extract_content(response)

            # Parse plan steps
            steps = self._parse_plan_steps(content, state["input"])

            logger.info(f"{self.provider_name} Planner created {len(steps)} steps")
            return {"plan": steps, "available_nodes": self.get_available_nodes()}

        except Exception as e:
            logger.error(f"{self.provider_name} Planner error: {e}")
            # Create fallback plan
            fallback_step = PlanStep(
                node_name=list(self.operation_nodes.keys())[0]
                if self.operation_nodes
                else "default",
                action_description=f"Handle {self.provider_name} request with available operations",
                context={"fallback": True},
            )
            return {
                "plan": [fallback_step],
                "available_nodes": self.get_available_nodes(),
            }

    def _parse_plan_steps(self, content: str, user_input: str) -> List[PlanStep]:
        """Parse plan steps from LLM response."""
        steps = []

        if isinstance(content, str) and ("Step 1:" in content or "1." in content):
            # Parse structured plan
            lines = content.split("\\n")
            for line in lines:
                line = line.strip()
                if any(
                    line.startswith(prefix)
                    for prefix in ["Step ", "1.", "2.", "3.", "4.", "5."]
                ):
                    if ":" in line or "-" in line:
                        # Extract step content
                        step_content = line.split(":", 1)[-1].split("-", 1)[-1].strip()

                        # Determine node from content
                        node_name = self._determine_node_from_content(
                            step_content, user_input
                        )

                        if step_content and node_name:
                            steps.append(
                                PlanStep(
                                    node_name=node_name,
                                    action_description=step_content,
                                    context={},
                                )
                            )

        # If no structured steps found, create intelligent fallback
        if not steps:
            steps = self._create_fallback_plan(user_input)

        return steps

    @abstractmethod
    def _determine_node_from_content(self, content: str, user_input: str) -> str:
        """Determine appropriate operation node from content."""
        pass

    @abstractmethod
    def _create_fallback_plan(self, user_input: str) -> List[PlanStep]:
        """Create fallback plan when parsing fails."""
        pass

    async def replanner_step(self, state: BasePlanExecuteState) -> Dict[str, Any]:
        """Re-evaluate plan and decide next action."""
        try:
            remaining_plan = state.get("plan", [])
            completed_steps = state.get("past_steps", [])

            # Check if we should continue or end
            if not remaining_plan or len(remaining_plan) == 0:
                # Generate summary response
                successful_steps = [step for step in completed_steps if step.success]
                failed_steps = [step for step in completed_steps if not step.success]

                response = f"{self.provider_name} operations completed successfully. "
                response += f"{len(successful_steps)} steps executed successfully."

                if failed_steps:
                    response += f" {len(failed_steps)} steps had errors."

                return {"response": response}

            # Continue with remaining plan
            logger.info(
                f"{self.provider_name} Replanner: {len(remaining_plan)} steps remaining"
            )
            return {"plan": remaining_plan}

        except Exception as e:
            logger.error(f"{self.provider_name} Replanner error: {e}")
            completed_count = len(state.get("past_steps", []))
            return {
                "response": f"{self.provider_name} operations completed. {completed_count} steps executed."
            }

    def should_continue(self, state: BasePlanExecuteState) -> str:
        """Determine next step in execution."""
        # If we have a final response, end execution
        if "response" in state and state["response"]:
            return END

        # If we have remaining plan steps, continue execution
        if state.get("plan") and len(state["plan"]) > 0:
            # Route to the appropriate operation node
            current_step = state["plan"][0]
            target_node = current_step.node_name

            if target_node in self.operation_nodes:
                return target_node
            else:
                logger.warning(f"Unknown node: {target_node}, routing to replanner")
                return "replanner"

        # If no plan steps remain, go to replanner to assess completion
        return "replanner"

    def _extract_content(self, response) -> str:
        """Extract content from LLM response."""
        if isinstance(response, str):
            return response
        elif hasattr(response, "content"):
            return response.content
        else:
            return str(response)

    def create_graph(self) -> StateGraph:
        """Create the plan-and-execute graph."""
        logger.info(f"Creating {self.provider_name} plan-and-execute subgraph")

        # Define state type for this provider
        class ProviderState(BasePlanExecuteState):
            pass

        workflow = StateGraph(ProviderState)

        # Add core planning and execution nodes
        workflow.add_node("planner", self.plan_step)
        workflow.add_node("replanner", self.replanner_step)

        # Add specialized operation nodes
        for node_name, operation_node in self.operation_nodes.items():
            workflow.add_node(node_name, operation_node.execute)

        # Define workflow edges
        workflow.add_edge(START, "planner")

        # After planning, route to appropriate node based on first step
        workflow.add_conditional_edges(
            "planner",
            self.should_continue,
            {
                "replanner": "replanner",
                END: END,
                **{node_name: node_name for node_name in self.operation_nodes.keys()},
            },
        )

        # Conditional edges based on should_continue logic
        # Add conditional edges from replanner to all possible destinations
        workflow.add_conditional_edges(
            "replanner",
            self.should_continue,
            {
                "replanner": "replanner",
                END: END,
                **{node_name: node_name for node_name in self.operation_nodes.keys()},
            },
        )

        # All operation nodes route back to replanner
        for node_name in self.operation_nodes.keys():
            workflow.add_edge(node_name, "replanner")

        logger.info(f"{self.provider_name} subgraph structure created successfully")
        return workflow

    def compile(self):
        """Compile the subgraph for use."""
        from app.langchain.tools.core.store import get_tools_store

        workflow = self.create_graph()
        store = get_tools_store()

        compiled_graph = workflow.compile(
            store=store,
            name=f"{self.provider_name.lower()}_subgraph",
            checkpointer=False,
        )

        logger.info(f"{self.provider_name} subgraph compiled successfully")
        return compiled_graph
