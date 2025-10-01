"""
Gmail Subgraph implemented using the standardized Plan-and-Execute framework.

Flow:
1. Main agent hands off to Gmail subagent
2. Gmail subagent creates structured execution plan with specialized operation nodes
3. Execute steps based on dependencies, passing context between steps
4. Return final output to main agent

Uses the FlexiblePlanExecuteGraph for standardized planning and execution.
"""

from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Optional, TypedDict

from app.config.loggers import langchain_logger as logger
from app.langchain.core.framework.plan_and_execute import (
    ExecutionResult,
    FlexiblePlanExecuteGraph,
)
from app.langchain.prompts.gmail_node_prompts import (
    ATTACHMENT_HANDLING_PROMPT,
    COMMUNICATION_PROMPT,
    CONTACT_MANAGEMENT_PROMPT,
    EMAIL_COMPOSITION_PROMPT,
    EMAIL_MANAGEMENT_PROMPT,
    EMAIL_RETRIEVAL_PROMPT,
    GMAIL_PLANNER_PROMPT,
)
from langchain_core.language_models import LanguageModelLike
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph


class GmailNodeEnum(str, Enum):
    """Available Gmail operation nodes."""

    EMAIL_COMPOSITION = "email_composition"
    EMAIL_RETRIEVAL = "email_retrieval"
    EMAIL_MANAGEMENT = "email_management"
    COMMUNICATION = "communication"
    CONTACT_MANAGEMENT = "contact_management"
    ATTACHMENT_HANDLING = "attachment_handling"
    FREE_LLM = "free_llm"  # For brainstorming, structuring, general tasks


# Available nodes description for planner
AVAILABLE_NODES_DESCRIPTION = """
Available Gmail Operation Nodes:

• email_composition - Create, draft, send emails and manage drafts
• email_retrieval - Search, fetch, list emails and conversation threads  
• email_management - Organize, label, delete, archive emails
• communication - Reply to threads, forward messages, manage conversations
• contact_management - Search people, contacts, profiles in Gmail
• attachment_handling - Download and process email attachments
• free_llm - General reasoning, brainstorming, structuring tasks
"""


class GmailAgentState(TypedDict, total=False):
    messages: List[BaseMessage]
    metadata: Dict[str, Any]
    _gmail_task_description: str
    _gmail_query: str
    _gmail_context: str
    _gmail_plan_result: Dict[str, Any]


class GmailPlanExecuteGraph(FlexiblePlanExecuteGraph):
    """Gmail plan-and-execute framework implementation."""

    def __init__(self, llm: Optional[LanguageModelLike] = None):
        super().__init__(provider_name="Gmail", llm=llm)

    def _initialize_operation_nodes(self):
        logger.info("Initializing Gmail operation nodes")

        node_configurations = [
            (
                GmailNodeEnum.EMAIL_COMPOSITION.value,
                "Create, draft, send emails and manage drafts",
                EMAIL_COMPOSITION_PROMPT,
            ),
            (
                GmailNodeEnum.EMAIL_RETRIEVAL.value,
                "Search, fetch, list emails and conversation threads",
                EMAIL_RETRIEVAL_PROMPT,
            ),
            (
                GmailNodeEnum.EMAIL_MANAGEMENT.value,
                "Organize, label, delete, archive emails",
                EMAIL_MANAGEMENT_PROMPT,
            ),
            (
                GmailNodeEnum.COMMUNICATION.value,
                "Reply to threads, forward messages, manage conversations",
                COMMUNICATION_PROMPT,
            ),
            (
                GmailNodeEnum.CONTACT_MANAGEMENT.value,
                "Search people, contacts, profiles in Gmail",
                CONTACT_MANAGEMENT_PROMPT,
            ),
            (
                GmailNodeEnum.ATTACHMENT_HANDLING.value,
                "Download and process email attachments",
                ATTACHMENT_HANDLING_PROMPT,
            ),
        ]

        for node_name, description, prompt in node_configurations:
            self.register_operation_node(
                name=node_name,
                func=self._create_prompt_node(node_name, prompt),
                description=description,
            )

        self.register_operation_node(
            name=GmailNodeEnum.FREE_LLM.value,
            func=self._create_prompt_node(
                GmailNodeEnum.FREE_LLM.value,
                "You are a helpful Gmail assistant. Execute the given instruction using your knowledge and reasoning abilities. Be thorough and provide clear, actionable responses.",
            ),
            description="General reasoning, brainstorming, structuring tasks",
        )

    def get_planner_prompt(self) -> str:
        return GMAIL_PLANNER_PROMPT + "\n\n" + AVAILABLE_NODES_DESCRIPTION

    def _create_prompt_node(
        self, node_name: str, system_prompt: str
    ) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
        def node(execution_context: Dict[str, Any]) -> Dict[str, Any]:
            instruction = execution_context.get("instructions", "").strip()
            contextual_notes = execution_context.get("context", "").strip()
            previous_results = execution_context.get("previous_results", [])

            human_sections: List[str] = []
            if instruction:
                human_sections.append(f"Instruction: {instruction}")
            if contextual_notes:
                human_sections.append(f"Additional context: {contextual_notes}")
            if previous_results:
                formatted_results = self._format_previous_results(previous_results)
                if formatted_results:
                    human_sections.append(
                        "Relevant previous results:\n" + formatted_results
                    )

            human_content = "\n\n".join(
                section for section in human_sections if section
            )
            if not human_content:
                human_content = "Execute the requested Gmail operation."

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=human_content),
            ]

            try:
                response = self.llm.invoke(messages)
                result_text = self._coerce_response_content(response)
                logger.info("%s node executed successfully", node_name)
                return {"output": result_text, "success": True}
            except Exception as exc:  # pragma: no cover - relies on external LLMs
                logger.error("Error in %s node: %s", node_name, exc)
                error_text = str(exc)
                return {"output": error_text, "success": False, "error": error_text}

        return node

    @staticmethod
    def _coerce_response_content(response: Any) -> str:
        if isinstance(response, str):
            return response
        if hasattr(response, "content"):
            content = response.content
            if isinstance(content, list):
                return "\n".join(str(item) for item in content)
            return str(content)
        return str(response)

    @staticmethod
    def _format_previous_results(results: Iterable[ExecutionResult]) -> str:
        lines: List[str] = []
        for result in results:
            payload: Dict[str, Any]
            if hasattr(result, "model_dump"):
                payload = result.model_dump()
            elif isinstance(result, dict):
                payload = result
            else:
                payload = {"output": str(result)}

            step_id = payload.get("step_id", "unknown")
            success = payload.get("success", True)
            output_text = GmailPlanExecuteGraph._shorten_text(payload.get("output", ""))
            lines.append(
                f"- Step {step_id} [{'success' if success else 'failed'}] {output_text}"
            )

        return "\n".join(lines)

    @staticmethod
    def _shorten_text(value: Any, max_length: int = 500) -> str:
        text = str(value).strip()
        if len(text) <= max_length:
            return text
        return text[: max_length - 3].rstrip() + "..."


def _coerce_message_content(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and "text" in part:
                parts.append(str(part["text"]))
            else:
                parts.append(str(part))
        return "\n".join(parts).strip()
    return str(content).strip()


def _extract_latest_instruction(messages: List[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage) and (
            message.name == "gmail_agent" or message.name is None
        ):
            instruction = _coerce_message_content(message)
            if instruction:
                return instruction
    return ""


def _collect_conversation_context(
    messages: List[BaseMessage], *, limit: int = 6
) -> str:
    if not messages:
        return ""

    context_entries: List[str] = []
    for message in messages[-limit:]:
        if isinstance(message, ToolMessage):
            continue
        if isinstance(message, HumanMessage) and message.name == "gmail_agent":
            continue
        if isinstance(message, SystemMessage) and message.name == "gmail_agent":
            continue

        content = _coerce_message_content(message)
        if not content:
            continue

        speaker = (
            message.name or message.__class__.__name__.replace("Message", "").lower()
        )
        context_entries.append(f"{speaker}: {content}")

    return "\n".join(context_entries).strip()


def _compose_gmail_query(task_description: str, context: str) -> str:
    task = task_description.strip()
    if not task:
        return context.strip()
    if context:
        return f"Task:\n{task}\n\nConversation Context:\n{context}"
    return task


def _build_plan_error(error_message: str) -> Dict[str, Any]:
    return {
        "provider": "Gmail",
        "plan_description": "Plan execution failed",
        "total_steps": 0,
        "completed_steps": 0,
        "successful_steps": 0,
        "failed_steps": 0,
        "results": [],
        "error": error_message,
    }


def _format_step_lines(results: Iterable[Any]) -> List[str]:
    formatted: List[str] = []
    for entry in results:
        if hasattr(entry, "model_dump"):
            data = entry.model_dump()
        elif isinstance(entry, dict):
            data = entry
        else:
            data = {"output": str(entry)}

        step_id = data.get("step_id", "?")
        node = data.get("node", "unknown")
        success = data.get("success", True)
        output = GmailPlanExecuteGraph._shorten_text(data.get("output", ""), 350)
        status = "success" if success else "failed"
        formatted.append(f"- Step {step_id} ({node}) [{status}]: {output}")

    return formatted


def _build_gmail_agent_message(plan_result: Dict[str, Any]) -> AIMessage:
    if not plan_result:
        content = "The Gmail subagent did not return any results."
        return AIMessage(
            content=content,
            name="gmail_agent",
            additional_kwargs={"plan_result": plan_result},
        )

    description = plan_result.get("plan_description", "Gmail plan results")
    successful = plan_result.get("successful_steps", 0)
    failed = plan_result.get("failed_steps", 0)
    total = plan_result.get("total_steps", successful + failed)
    results_section = _format_step_lines(plan_result.get("results", []))
    error_text = plan_result.get("error")

    lines = [description.strip()]
    lines.append(f"Steps: {successful} succeeded, {failed} failed, {total} total")

    if results_section:
        lines.append("Step results:")
        lines.extend(results_section)

    if error_text:
        lines.append(f"Error: {error_text}")

    content = "\n".join(line for line in lines if line).strip()
    if not content:
        content = "Gmail subagent completed without additional details."

    return AIMessage(
        content=content,
        name="gmail_agent",
        additional_kwargs={"plan_result": plan_result},
    )


def create_gmail_subgraph(llm: LanguageModelLike) -> CompiledStateGraph:
    """Factory function to create and compile the Gmail sub-agent subgraph."""
    logger.info("Creating Gmail subgraph using plan-and-execute framework")

    gmail_graph = GmailPlanExecuteGraph(llm=llm)

    def prepare_state(state: GmailAgentState) -> GmailAgentState:
        messages = list(state.get("messages", []))
        task_description = _extract_latest_instruction(messages)
        conversation_context = _collect_conversation_context(messages)
        query = _compose_gmail_query(task_description, conversation_context)

        state["_gmail_task_description"] = task_description
        state["_gmail_query"] = query
        state["_gmail_context"] = conversation_context
        return state

    def execute_plan(state: GmailAgentState) -> GmailAgentState:
        query = state.get("_gmail_query", "").strip()
        if not query:
            plan_result = _build_plan_error(
                "Missing task description for Gmail subagent"
            )
        else:
            try:
                plan_result = gmail_graph.execute(
                    query=query,
                    include_previous_outputs=True,
                )
            except Exception as exc:  # pragma: no cover - external dependencies
                logger.error("Gmail plan execution failed: %s", exc)
                plan_result = _build_plan_error(str(exc))

        state["_gmail_plan_result"] = plan_result
        return state

    def finalize(state: GmailAgentState) -> GmailAgentState:
        plan_result = state.get("_gmail_plan_result", {})
        response_message = _build_gmail_agent_message(plan_result)

        existing_messages = list(state.get("messages", []))
        existing_messages.append(response_message)
        state["messages"] = existing_messages

        for key in (
            "_gmail_task_description",
            "_gmail_query",
            "_gmail_context",
            "_gmail_plan_result",
        ):
            state.pop(key, None)

        return state

    builder = StateGraph(GmailAgentState)
    builder.add_node("prepare", prepare_state)
    builder.add_node("plan_execute", execute_plan)
    builder.add_node("finalize", finalize)

    builder.set_entry_point("prepare")
    builder.add_edge("prepare", "plan_execute")
    builder.add_edge("plan_execute", "finalize")

    compiled_graph = builder.compile(checkpointer=False, name="gmail_agent")

    logger.info("Gmail subgraph created successfully")
    return compiled_graph