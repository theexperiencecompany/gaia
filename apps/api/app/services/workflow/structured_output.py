"""Service for extracting structured output from workflow execution results."""

from datetime import datetime, timezone

from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import PydanticOutputParser
from shared.py.wide_events import log

from app.agents.llm.client import get_free_llm_chain, invoke_with_fallback
from app.agents.prompts.workflow_prompts import WORKFLOW_OUTPUT_EXTRACTION_PROMPT
from app.schemas.workflow.structured_output import WorkflowStructuredOutput

MAX_OUTPUT_LENGTH = 4000
MAX_RETRIES = 2


async def extract_workflow_structured_output(
    complete_message: str,
    workflow_title: str,
    workflow_description: str,
) -> WorkflowStructuredOutput:
    """
    Extract structured notification data from workflow execution output using a free LLM.

    Uses get_free_llm_chain() with PydanticOutputParser for guaranteed schema compliance.
    Falls back to default notification data if extraction fails after retries.

    Args:
        complete_message: The full bot response from workflow execution
        workflow_title: Title of the executed workflow
        workflow_description: Description of the executed workflow

    Returns:
        WorkflowStructuredOutput with extracted notification data
    """
    truncated_output = complete_message[:MAX_OUTPUT_LENGTH] if complete_message else ""

    parser = PydanticOutputParser(pydantic_object=WorkflowStructuredOutput)

    prompt_text = WORKFLOW_OUTPUT_EXTRACTION_PROMPT.format(
        workflow_title=workflow_title,
        workflow_description=workflow_description or "",
        execution_output=truncated_output,
        format_instructions=parser.get_format_instructions(),
    )

    for attempt in range(MAX_RETRIES + 1):
        try:
            llm_chain = get_free_llm_chain()
            result = await invoke_with_fallback(
                llm_chain,
                [HumanMessage(content=prompt_text)],
            )
            raw = result if isinstance(result, str) else result.content
            text = raw if isinstance(raw, str) else str(raw)
            return parser.parse(text)
        except Exception as e:
            if attempt < MAX_RETRIES:
                log.warning(
                    f"Workflow structured output extraction attempt {attempt + 1} failed: {e}"
                )
            else:
                log.error(
                    f"Workflow structured output extraction failed after {MAX_RETRIES + 1} attempts: {e}"
                )

    return _default_structured_output(workflow_title)


def _default_structured_output(workflow_title: str) -> WorkflowStructuredOutput:
    """Return default structured output that mirrors current hardcoded behavior."""
    completed_at = datetime.now(timezone.utc)
    formatted_time = completed_at.strftime("%I:%M %p UTC, %b %d")
    return WorkflowStructuredOutput(
        notification_title=f"Workflow Completed: {workflow_title}",
        notification_body=f"Completed at {formatted_time}",
        notification_type="success",
        notification_channels=["inapp"],
        requires_user_action=False,
        action_items=[],
    )
