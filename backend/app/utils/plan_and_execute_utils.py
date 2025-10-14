"""Utility functions for plan-and-execute framework."""

from typing import Iterable, List

from langchain_core.messages import HumanMessage


def format_previous_results(results: Iterable) -> str:
    """Format execution results for display in context."""
    formatted: List[str] = []
    for result in results:
        status = "Success" if result.success else "Failed"
        output = result.output if result.success else result.error
        formatted.append(f"Step {result.step_id} ({status}): {output}")
    return "\n".join(formatted)


def default_human_message_formatter(context) -> str:
    """Default formatter for human messages in execution context."""
    instructions = context.get("instructions", "").strip()
    additional_context = context.get("context", {})
    context_block = ""
    if additional_context:
        context_block = "\n".join(
            f"{key}: {value}" for key, value in additional_context.items()
        ).strip()

    previous_results = context.get("previous_results", [])
    previous_block = (
        format_previous_results(previous_results) if previous_results else ""
    )

    sections: List[str] = [instructions]
    if context_block:
        sections.append("Context:\n" + context_block)
    if previous_block:
        sections.append("Relevant Previous Results:\n" + previous_block)

    return "\n\n".join(section for section in sections if section).strip()


def default_task_extractor(agent_name: str):
    """Default task extractor that finds the latest human message."""

    def extractor(messages):
        for message in reversed(messages):
            if isinstance(message, HumanMessage):
                return message.text()
        return ""

    return extractor


def default_context_extractor(agent_name: str, history_window: int):
    """Default context extractor that formats recent conversation history."""

    def extractor(messages):
        window = (
            list(messages[-history_window:]) if history_window > 0 else list(messages)
        )
        parts: List[str] = []
        for message in window:
            role = "User" if isinstance(message, HumanMessage) else "Assistant"
            parts.append(f"{role}: {message.text()}")
        return "\n".join(parts)

    return extractor


def default_query_builder(task_description: str, conversation_context: str) -> str:
    """Default query builder that combines task and context."""
    if not task_description:
        return ""
    if not conversation_context:
        return task_description
    return f"{task_description}\n\nContext:\n{conversation_context}"


def default_response_builder(provider_name: str, agent_name: str):
    """Default response builder for plan execution results."""

    def builder(plan_result):
        from langchain_core.messages import AIMessage

        if not plan_result:
            return AIMessage(content=f"{provider_name} agent returned no result.")

        if plan_result.get("error"):
            return AIMessage(
                content=f"{provider_name} agent failed: {plan_result['error']}"
            )

        lines = [
            f"{provider_name} agent executed {plan_result.get('completed_steps', 0)} of {plan_result.get('total_steps', 0)} steps.",
        ]

        for result in plan_result.get("results", []):
            status = "✅" if result.get("success") else "⚠️"
            detail = (
                result.get("output") if result.get("success") else result.get("error")
            )
            lines.append(
                f"{status} Step {result.get('step_id')} ({result.get('node', 'unknown')}): {detail}"
            )

        return AIMessage(content="\n".join(lines))

    return builder


def build_plan_error(provider_name: str, error: str):
    """Build error response for plan execution failures."""
    return {
        "provider": provider_name,
        "plan_description": "",
        "total_steps": 0,
        "completed_steps": 0,
        "successful_steps": 0,
        "failed_steps": 0,
        "results": [],
        "error": error,
    }
