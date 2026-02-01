"""
Workflow subagent structured output schema and parser.

Uses Pydantic models with LangChain's PydanticOutputParser for reliable parsing.

The workflow subagent can respond in two modes:
1. Clarifying questions - asks user for more information
2. Finalized workflow - ready to create the workflow draft
"""

from typing import List, Literal, Optional, Union

from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field

from app.config.loggers import general_logger as logger


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
    description: str = Field(description="What this workflow does")
    trigger_type: Literal["manual", "scheduled", "integration"] = Field(
        description="When the workflow runs"
    )
    cron_expression: Optional[str] = Field(
        default=None, description="Cron expression for scheduled triggers"
    )
    trigger_slug: Optional[str] = Field(
        default=None, description="Trigger slug for integration triggers"
    )
    steps: List[str] = Field(
        default_factory=list, description="List of workflow step descriptions"
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
                "trigger_type": self.trigger_type,
                "trigger_slug": self.trigger_slug,
                "cron_expression": self.cron_expression,
                "steps": self.steps,
                "direct_create": self.direct_create,
            }
        }


class WorkflowSubagentResponse(BaseModel):
    """Union type for workflow subagent responses."""

    output: Union[ClarifyingOutput, FinalizedOutput] = Field(
        description="Either a clarifying question or finalized workflow"
    )


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
    "description": "What this workflow does",
    "trigger_type": "manual|scheduled|integration",
    "cron_expression": "0 9 * * *",
    "trigger_slug": "GMAIL_NEW_MESSAGE",
    "steps": ["Step 1", "Step 2"],
    "direct_create": false
}
```

Notes:
- cron_expression: Required for scheduled, omit for others
- trigger_slug: Required for integration, omit for others  
- direct_create: Set true ONLY for simple, unambiguous workflows
"""


def parse_subagent_response(response: str) -> ParseResult:
    """
    Parse the workflow subagent's response to extract structured output.

    Uses regex to find JSON blocks, then Pydantic for validation.

    Args:
        response: The full text response from the subagent

    Returns:
        ParseResult with mode, data, and any errors
    """
    import json
    import re

    # Pattern to find JSON blocks in the response
    json_pattern = re.compile(
        r"```(?:json)?\\s*\\n?\\s*(\\{[^`]*\"type\"\\s*:\\s*\"(?:clarifying|finalized)\"[^`]*\\})\\s*\\n?```",
        re.DOTALL | re.IGNORECASE,
    )

    match = json_pattern.search(response)

    if not match:
        # No structured output found - treat as conversational message
        # This is valid - subagent may be having a natural conversation
        logger.debug(
            "No structured JSON found in subagent response, treating as message"
        )
        return ParseResult(
            mode="clarifying",
            message=response,
            raw_response=response,
        )

    try:
        json_str = match.group(1)
        data = json.loads(json_str)

        output_type = data.get("type", "clarifying")

        if output_type == "finalized":
            # Validate with Pydantic
            try:
                draft = FinalizedOutput(**data)
            except Exception as e:
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

            return ParseResult(
                mode="finalized",
                draft=draft,
                raw_response=response,
            )

        else:
            # Clarifying mode
            try:
                clarifying = ClarifyingOutput(**data)
                return ParseResult(
                    mode="clarifying",
                    message=clarifying.message,
                    raw_response=response,
                )
            except Exception:
                # Fall back to raw message
                return ParseResult(
                    mode="clarifying",
                    message=data.get("message", response),
                    raw_response=response,
                )

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse JSON from subagent response: {e}")
        return ParseResult(
            mode="parse_error",
            parse_error=f"Invalid JSON syntax: {str(e)}",
            raw_response=response,
        )


# Legacy aliases for backwards compatibility
WorkflowDraft = FinalizedOutput
WorkflowSubagentOutput = ParseResult
