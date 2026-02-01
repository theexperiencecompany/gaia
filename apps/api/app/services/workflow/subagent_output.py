"""
Workflow subagent structured output schema and parser.

The workflow subagent can respond in two modes:
1. Clarifying questions - asks user for more information
2. Finalized workflow - ready to create the workflow draft

The subagent embeds JSON in its response which we parse to determine the mode.
"""

import json
import re
from dataclasses import dataclass, field
from typing import List, Literal, Optional

from app.config.loggers import general_logger as logger


@dataclass
class WorkflowDraft:
    """Finalized workflow draft ready for streaming to frontend."""

    title: str
    description: str
    trigger_type: Literal["manual", "scheduled", "integration"]
    trigger_slug: Optional[str] = None
    cron_expression: Optional[str] = None
    steps: List[str] = field(default_factory=list)

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
            }
        }


@dataclass
class WorkflowSubagentOutput:
    """Parsed output from workflow subagent."""

    mode: Literal["clarifying", "finalized", "parse_error"]
    # For clarifying mode
    message: Optional[str] = None
    # For finalized mode
    draft: Optional[WorkflowDraft] = None
    # For parse_error mode - indicates JSON was found but invalid
    parse_error: Optional[str] = None
    # Original response for retry context
    raw_response: Optional[str] = None


# JSON block markers that the subagent should use
JSON_START_MARKER = "```json"
JSON_END_MARKER = "```"

# Alternative: look for WORKFLOW_OUTPUT JSON block
OUTPUT_PATTERN = re.compile(
    r"```(?:json)?\s*\n?\s*(\{[^`]*\"type\"\s*:\s*\"(?:clarifying|finalized)\"[^`]*\})\s*\n?```",
    re.DOTALL | re.IGNORECASE,
)


def parse_subagent_response(response: str) -> WorkflowSubagentOutput:
    """
    Parse the workflow subagent's response to extract structured output.

    The subagent should include a JSON block in its response:

    For clarifying questions:
    ```json
    {
        "type": "clarifying",
        "message": "When should this workflow run?"
    }
    ```

    For finalized workflow:
    ```json
    {
        "type": "finalized",
        "title": "Daily Email Summary",
        "description": "Summarize emails every morning",
        "trigger_type": "scheduled",
        "cron_expression": "0 9 * * *",
        "steps": ["Get unread emails", "Summarize content", "Send to Slack"]
    }
    ```

    Args:
        response: The full text response from the subagent

    Returns:
        WorkflowSubagentOutput with parsed data. Mode can be:
        - "clarifying": Subagent is asking user questions
        - "finalized": Workflow is ready to stream
        - "parse_error": JSON was found but invalid (should trigger retry)
    """
    # Try to find JSON block in response
    match = OUTPUT_PATTERN.search(response)

    if not match:
        # No structured output found - treat as clarifying question
        # This is NOT an error - subagent may be having a conversation
        logger.debug(
            "No structured JSON found in subagent response, treating as message"
        )
        return WorkflowSubagentOutput(
            mode="clarifying",
            message=response,
            raw_response=response,
        )

    try:
        json_str = match.group(1)
        data = json.loads(json_str)

        output_type = data.get("type", "clarifying")

        if output_type == "finalized":
            # Validate required fields
            if not data.get("title") or not data.get("description"):
                logger.warning("Finalized output missing title/description")
                return WorkflowSubagentOutput(
                    mode="parse_error",
                    parse_error="Finalized workflow must include 'title' and 'description' fields",
                    raw_response=response,
                )

            trigger_type = data.get("trigger_type", "manual")
            if trigger_type not in ("manual", "scheduled", "integration"):
                return WorkflowSubagentOutput(
                    mode="parse_error",
                    parse_error=f"Invalid trigger_type '{trigger_type}'. Must be 'manual', 'scheduled', or 'integration'",
                    raw_response=response,
                )

            # Validate trigger-specific fields
            if trigger_type == "scheduled" and not data.get("cron_expression"):
                return WorkflowSubagentOutput(
                    mode="parse_error",
                    parse_error="Scheduled trigger requires 'cron_expression' field",
                    raw_response=response,
                )

            if trigger_type == "integration" and not data.get("trigger_slug"):
                return WorkflowSubagentOutput(
                    mode="parse_error",
                    parse_error="Integration trigger requires 'trigger_slug' field from search_triggers",
                    raw_response=response,
                )

            draft = WorkflowDraft(
                title=data["title"],
                description=data["description"],
                trigger_type=trigger_type,
                trigger_slug=data.get("trigger_slug"),
                cron_expression=data.get("cron_expression"),
                steps=data.get("steps", []),
            )

            return WorkflowSubagentOutput(
                mode="finalized",
                draft=draft,
                raw_response=response,
            )

        else:
            # Clarifying mode
            return WorkflowSubagentOutput(
                mode="clarifying",
                message=data.get("message", response),
                raw_response=response,
            )

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse JSON from subagent response: {e}")
        return WorkflowSubagentOutput(
            mode="parse_error",
            parse_error=f"Invalid JSON syntax: {str(e)}",
            raw_response=response,
        )
