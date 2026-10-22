"""
Workflow subagent structured output schema and parser.

The workflow subagent can respond in two modes:
1. Clarifying questions - asks user for more information
2. Finalized workflow - ready to create the workflow draft

The expected JSON block format lives in the subagent prompt
(app/agents/prompts/workflow_prompts.py); this module validates it.
"""

from collections.abc import Mapping
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from app.constants.log_tags import LogTag
from app.constants.workflows import WorkflowDelivery
from app.models.workflow_models import TriggerType
from app.utils.markdown_utils import decode_json_blocks
from shared.py.wide_events import log

# The assistant speaks "scheduled"; every other layer (TriggerConfig, the REST
# API, the frontend) speaks TriggerType.SCHEDULE == "schedule". This is the one
# place the two vocabularies meet — translate here, never downstream.
TRIGGER_TYPE_BY_DRAFT_TYPE: dict[str, TriggerType] = {
    "manual": TriggerType.MANUAL,
    "scheduled": TriggerType.SCHEDULE,
    "integration": TriggerType.INTEGRATION,
}

# =============================================================================
# PYDANTIC MODELS FOR STRUCTURED OUTPUT
# =============================================================================


class WorkflowDraftPayload(TypedDict):
    """The workflow_draft frame the frontend's draft card renders."""

    suggested_title: str
    suggested_description: str
    prompt: str
    trigger_type: str
    trigger_slug: str | None
    integration_ids: list[str]
    cron_expression: str | None
    direct_create: bool
    delivery: str


class WorkflowDraftFrame(TypedDict):
    """One streamed frame carrying a workflow draft."""

    workflow_draft: WorkflowDraftPayload


class _PayloadEnvelope(BaseModel):
    """The one key read off a decoded payload before it is validated as its own type."""

    model_config = ConfigDict(extra="ignore")

    type: str | None = None


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
    integration_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Integration ids this workflow depends on (e.g. ['gmail', 'slack']), "
            "including the trigger integration. Used to warn the user about "
            "disconnected dependencies; record them whether connected or not."
        ),
    )
    direct_create: bool = Field(
        default=False,
        description="True only for simple, unambiguous workflows where no user feedback is needed",
    )

    @property
    def backend_trigger_type(self) -> TriggerType:
        """Return this draft's trigger in the vocabulary the rest of the system uses."""
        return TRIGGER_TYPE_BY_DRAFT_TYPE.get(self.trigger_type, TriggerType.MANUAL)

    def to_stream_payload(self, delivery: WorkflowDelivery) -> WorkflowDraftFrame:
        """Convert to the format expected by frontend stream handler.

        delivery is not the assistant's to choose: the calling agent sets it from
        the user's intent, and the draft carries it to the confirming modal.
        """
        return {
            "workflow_draft": {
                "suggested_title": self.title,
                "suggested_description": self.description,
                "prompt": self.prompt,
                "trigger_type": self.backend_trigger_type.value,
                "trigger_slug": self.trigger_slug,
                "integration_ids": self.integration_ids,
                "cron_expression": self.cron_expression,
                "direct_create": self.direct_create,
                "delivery": delivery.value,
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


def _result_from_payload(data: Mapping[str, object], response: str) -> ParseResult | None:
    """Turn one decoded JSON object into a ParseResult, or None if it isn't ours."""
    output_type = _PayloadEnvelope.model_validate(data).type

    if output_type == "finalized":
        try:
            draft = FinalizedOutput.model_validate(data)
        except Exception as e:
            log.warning(
                f"{LogTag.WORKFLOW} Failed to parse finalized output",
                error=str(e),
                error_type=type(e).__name__,
            )
            return ParseResult(
                mode="parse_error",
                parse_error=f"Invalid finalized output: {e!s}",
                raw_response=response,
            )

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

        log.info(f"{LogTag.WORKFLOW} Successfully parsed finalized workflow", title=draft.title)
        return ParseResult(mode="finalized", draft=draft, raw_response=response)

    if output_type == "clarifying":
        try:
            clarifying = ClarifyingOutput.model_validate(data)
            log.info(f"{LogTag.WORKFLOW} Successfully parsed clarifying response")
            return ParseResult(mode="clarifying", message=clarifying.message, raw_response=response)
        except Exception:
            # A clarifying payload without a usable message: the reply itself is the question.
            return ParseResult(mode="clarifying", message=response, raw_response=response)

    return None


def parse_subagent_response(response: str) -> ParseResult:
    """Extract the workflow assistant's structured output from its reply.

    Falls back to treating the whole reply as a clarifying message when it
    carries no recognizable JSON payload.
    """
    for data in decode_json_blocks(response).values:
        if not isinstance(data, dict) or "type" not in data:
            continue
        result = _result_from_payload(data, response)
        if result is not None:
            return result

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
