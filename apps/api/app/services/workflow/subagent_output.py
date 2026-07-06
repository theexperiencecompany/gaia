"""
Workflow subagent structured output schema and parser.

The workflow subagent can respond in two modes:
1. Clarifying questions - asks user for more information
2. Finalized workflow - ready to create the workflow draft

The expected JSON block format lives in the subagent prompt
(app/agents/prompts/workflow_prompts.py); this module validates it.
"""

import json
import re
from typing import Literal

from pydantic import BaseModel, Field

from app.constants.log_tags import LogTag
from shared.py.wide_events import log

# =============================================================================
# PYDANTIC MODELS FOR STRUCTURED OUTPUT
# =============================================================================


class ClarifyingOutput(BaseModel):
    """Output when subagent needs to ask clarifying questions."""

    type: Literal["clarifying"] = Field(description="Must be 'clarifying' when asking questions")
    message: str = Field(description="The clarifying question to ask the user")


class FinalizedOutput(BaseModel):
    """Output when workflow is ready to be created."""

    type: Literal["finalized"] = Field(description="Must be 'finalized' when workflow is complete")
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
    cron_expression: str | None = Field(
        default=None,
        description="Cron expression for scheduled triggers (in user's local time)",
    )
    trigger_slug: str | None = Field(
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
        message: str | None = None,
        draft: FinalizedOutput | None = None,
        parse_error: str | None = None,
        raw_response: str | None = None,
    ):
        self.mode = mode
        self.message = message
        self.draft = draft
        self.parse_error = parse_error
        self.raw_response = raw_response


# =============================================================================
# PARSER
# =============================================================================


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
                        log.warning(f"{LogTag.WORKFLOW} Failed to parse finalized output: {e}")
                        return ParseResult(
                            mode="parse_error",
                            parse_error=f"Invalid finalized output: {e!s}",
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

                    log.info(
                        f"{LogTag.WORKFLOW} Successfully parsed finalized workflow: {draft.title}"
                    )
                    return ParseResult(
                        mode="finalized",
                        draft=draft,
                        raw_response=response,
                    )

                if output_type == "clarifying":
                    try:
                        clarifying = ClarifyingOutput(**data)
                        log.info(f"{LogTag.WORKFLOW} Successfully parsed clarifying response")
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
    log.debug(
        f"{LogTag.WORKFLOW} No structured JSON found in subagent response, treating as message"
    )
    return ParseResult(
        mode="clarifying",
        message=response,
        raw_response=response,
    )


# Legacy aliases for backwards compatibility
WorkflowDraft = FinalizedOutput
WorkflowSubagentOutput = ParseResult
