"""
Workflow subagent structured output schema and parser.

Uses Pydantic models with LangChain's PydanticOutputParser for reliable parsing.

The workflow subagent can respond in two modes:
1. Clarifying questions - asks user for more information
2. Finalized workflow - ready to create the workflow draft
"""

import json
import re
from typing import Literal, Optional

from app.config.loggers import general_logger as logger
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field

# =============================================================================
# PYDANTIC MODELS FOR STRUCTURED OUTPUT
# =============================================================================


class ClarifyingOutput(BaseModel):
    """Output when subagent needs to ask clarifying questions."""

    type: Literal["clarifying"] = Field(
        description="Must be 'clarifying' when asking questions"
    )
    message: str = Field(description="The clarifying question to ask the user")


class FinalizedOutput(BaseModel):
    """Output when workflow is ready to be created."""

    type: Literal["finalized"] = Field(
        description="Must be 'finalized' when workflow is complete"
    )
    title: str = Field(description="Workflow title")
    description: str = Field(
        description="Short description for display in cards/UI (1-2 sentences summarizing what the workflow does)"
    )
    prompt: str = Field(
        description="Detailed instructions/prompt for the workflow execution. This should be comprehensive and include all necessary context, specific actions to take, data to use, and expected outcomes."
    )
    trigger_type: Literal["manual", "scheduled", "integration"] = Field(
        description="When the workflow runs"
    )
    cron_expression: Optional[str] = Field(
        default=None,
        description="Cron expression for scheduled triggers (in user's local time)",
    )
    trigger_slug: Optional[str] = Field(
        default=None, description="Trigger slug for integration triggers"
    )
    direct_create: bool = Field(
        default=False,
        description="True only for simple, unambiguous workflows where no user feedback is needed",
    )

    def to_stream_payload(self) -> dict:
        """Convert to the format expected by frontend stream handler."""
        return {
            "workflow_draft": {
                "suggested_title": self.title,
                "suggested_description": self.description,
                "prompt": self.prompt,
                "trigger_type": self.trigger_type,
                "trigger_slug": self.trigger_slug,
                "cron_expression": self.cron_expression,
                "direct_create": self.direct_create,
            }
        }


# =============================================================================
# PARSER RESULT
# =============================================================================


class ParseResult:
    """Result of parsing subagent response."""

    def __init__(
        self,
        mode: Literal["clarifying", "finalized", "parse_error"],
        message: Optional[str] = None,
        draft: Optional[FinalizedOutput] = None,
        parse_error: Optional[str] = None,
        raw_response: Optional[str] = None,
    ):
        self.mode = mode
        self.message = message
        self.draft = draft
        self.parse_error = parse_error
        self.raw_response = raw_response


# =============================================================================
# PARSER
# =============================================================================

# Create parsers for format instructions
clarifying_parser = PydanticOutputParser(pydantic_object=ClarifyingOutput)
finalized_parser = PydanticOutputParser(pydantic_object=FinalizedOutput)


def get_format_instructions() -> str:
    """Get format instructions for the subagent prompt."""
    return """
You MUST include a JSON block in your response. Two formats:

For clarifying questions:
```json
{
    "type": "clarifying",
    "message": "Your question to the user"
}
```

For finalized workflow:
```json
{
    "type": "finalized",
    "title": "Workflow Title",
    "description": "Short 1-2 sentence summary for display in UI cards",
    "prompt": "Detailed step-by-step instructions for the workflow. Include numbered steps (1, 2, 3...), specific integrations to use, what data to gather, actions to take, and expected outputs.",
    "trigger_type": "manual|scheduled|integration",
    "cron_expression": "0 9 * * *",
    "trigger_slug": "GMAIL_NEW_MESSAGE",
    "direct_create": false
}
```

IMPORTANT:
- description: Keep SHORT (1-2 sentences) - just for UI display
- prompt: Be DETAILED and COMPREHENSIVE - this is what the AI uses to execute the workflow
  • Include numbered steps (1, 2, 3...)
  • Mention integrations by name (Gmail, Slack, Calendar, etc.)
  • What data to gather and from where
  • Expected format of outputs
- cron_expression: Required for scheduled, omit for others (use USER'S LOCAL TIME, not UTC)
- trigger_slug: Required for integration, omit for others  
- direct_create: Set true ONLY for simple, unambiguous manual/scheduled workflows
"""


def parse_subagent_response(response: str) -> ParseResult:
    """
    Parse the workflow subagent's response to extract structured output.

    Extracts JSON from markdown code blocks, then validates with Pydantic.

    Args:
        response: The full text response from the subagent

    Returns:
        ParseResult with mode, data, and any errors
    """
    # Simple approach: find content between ```json and ``` (or just ``` and ```)
    # Use raw string to avoid escaping issues
    json_block_pattern = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)

    matches = json_block_pattern.findall(response)

    # Try each match to find valid JSON with "type" field
    for match in matches:
        match = match.strip()
        if not match:
            continue

        try:
            data = json.loads(match)
            if isinstance(data, dict) and "type" in data:
                output_type = data.get("type")

                if output_type == "finalized":
                    try:
                        draft = FinalizedOutput(**data)
                    except Exception as e:
                        logger.warning(f"Failed to parse finalized output: {e}")
                        return ParseResult(
                            mode="parse_error",
                            parse_error=f"Invalid finalized output: {str(e)}",
                            raw_response=response,
                        )

                    # Additional validation
                    if draft.trigger_type == "scheduled" and not draft.cron_expression:
                        return ParseResult(
                            mode="parse_error",
                            parse_error="Scheduled trigger requires 'cron_expression' field",
                            raw_response=response,
                        )

                    if draft.trigger_type == "integration" and not draft.trigger_slug:
                        return ParseResult(
                            mode="parse_error",
                            parse_error="Integration trigger requires 'trigger_slug' field from search_triggers",
                            raw_response=response,
                        )

                    logger.info(
                        f"Successfully parsed finalized workflow: {draft.title}"
                    )
                    return ParseResult(
                        mode="finalized",
                        draft=draft,
                        raw_response=response,
                    )

                elif output_type == "clarifying":
                    try:
                        clarifying = ClarifyingOutput(**data)
                        logger.info("Successfully parsed clarifying response")
                        return ParseResult(
                            mode="clarifying",
                            message=clarifying.message,
                            raw_response=response,
                        )
                    except Exception:
                        # Fall back to raw message from data
                        return ParseResult(
                            mode="clarifying",
                            message=data.get("message", response),
                            raw_response=response,
                        )

        except json.JSONDecodeError:
            # This match wasn't valid JSON, try next one
            continue

    # No structured output found - treat as conversational message
    logger.debug("No structured JSON found in subagent response, treating as message")
    return ParseResult(
        mode="clarifying",
        message=response,
        raw_response=response,
    )


# Legacy aliases for backwards compatibility
WorkflowDraft = FinalizedOutput
WorkflowSubagentOutput = ParseResult
