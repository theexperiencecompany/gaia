"""
Clean and lean workflow models for GAIA workflow system.
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any
import uuid

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.models.scheduler_models import BaseScheduledTask
from app.models.trigger_configs import TriggerConfigData
from app.utils.cron_utils import (
    get_next_run_time,
    parse_timezone,
    validate_cron_expression,
)
from shared.py.wide_events import log


class TriggerType(str, Enum):
    """Type of workflow trigger.

    - MANUAL: Triggered by user action
    - SCHEDULE: Triggered by cron schedule
    - INTEGRATION: Triggered by external service (calendar, email, github, etc.)
    """

    MANUAL = "manual"
    SCHEDULE = "schedule"
    INTEGRATION = "integration"


class WorkflowStep(BaseModel):
    """A single step in a workflow."""

    id: str = Field(default="", description="Unique identifier for the step")
    title: str = Field(description="Clear, actionable title for the step")
    category: str = Field(
        default="general",
        description="Category for routing (e.g., gmail, notion, todos, reminders)",
    )
    description: str = Field(description="Detailed description of what this step accomplishes")


# LLM Output Models for Workflow Generation
class GeneratedStep(BaseModel):
    """Minimal schema for LLM-generated workflow steps."""

    title: str = Field(description="Human-readable step name")
    category: str = Field(description="Category for routing")
    description: str = Field(description="What this step accomplishes")


class GeneratedWorkflow(BaseModel):
    """Schema for LLM workflow generation output."""

    steps: list[GeneratedStep] = Field(description="List of workflow steps")


class TriggerConfig(BaseModel):
    """Configuration for workflow triggers.

    Uses a discriminated union pattern for type-safe provider configs.
    Provider-specific data is stored in `trigger_data` field.
    """

    # Allow extra fields to be stored (e.g., calendar_ids from frontend)
    model_config = ConfigDict(extra="allow")

    type: TriggerType = Field(description="Type of trigger")
    enabled: bool = Field(default=True, description="Whether the trigger is enabled")

    # Specific trigger slug (e.g., "calendar_event_created", "github_commit_event")
    # Used by frontend to identify which trigger is selected
    trigger_name: str | None = Field(
        default=None,
        description="Specific trigger slug for identification",
    )

    # Type-safe provider config using discriminated union
    trigger_data: TriggerConfigData | None = Field(
        default=None,
        description="Provider-specific trigger configuration",
    )

    # Composio trigger tracking
    composio_trigger_ids: list[str] | None = Field(
        default=None,
        description="List of Composio trigger IDs registered for this workflow",
    )

    # Schedule configuration (generic, not provider-specific)
    cron_expression: str | None = Field(
        default=None, description="Cron expression for scheduled workflows"
    )
    timezone: str | None = Field(default="UTC", description="Timezone for scheduled execution")
    next_run: datetime | None = Field(default=None, description="Next scheduled execution time")

    def calculate_next_run(
        self, base_time: datetime | None = None, user_timezone: str | None = None
    ) -> datetime | None:
        """Calculate the next run time from the cron expression. Returns UTC.

        user_timezone accepts IANA names ("America/New_York") or offset strings ("+05:30").
        """
        if self.type != TriggerType.SCHEDULE or not self.cron_expression:
            return None

        try:
            # Use user_timezone parameter, fallback to trigger config timezone, then UTC
            tz_name = user_timezone or self.timezone or "UTC"

            # Convert timezone name/offset to timezone object using the unified parser
            tz = parse_timezone(tz_name)

            # If base_time is provided, convert it to the user's timezone for cron calculation
            if base_time:
                if base_time.tzinfo is None:
                    base_time = base_time.replace(tzinfo=UTC)
                # Convert to user timezone for cron calculation
                if tz_name != "UTC":
                    base_time = base_time.astimezone(tz)
            else:
                # Current time in user's timezone
                base_time = datetime.now(tz)

            # Calculate next run time using timezone-aware base_time
            next_run = get_next_run_time(self.cron_expression, base_time, tz_name)

            # Ensure result is in UTC for storage
            if next_run.tzinfo != UTC:
                next_run = next_run.astimezone(UTC)

            return next_run
        except Exception as e:
            log.error(f"Error calculating next run time: {e}")
            return None

    def update_next_run(
        self, base_time: datetime | None = None, user_timezone: str | None = None
    ) -> bool:
        """Update the next_run field; return True if it changed."""
        old_next_run = self.next_run
        self.next_run = self.calculate_next_run(base_time, user_timezone)
        return old_next_run != self.next_run

    @field_validator("cron_expression")
    @classmethod
    def validate_cron_expression(cls, v):
        """Validate cron expression if provided."""
        if v is not None:
            if not validate_cron_expression(v):
                raise ValueError(f"Invalid cron expression: {v}")
        return v


class Workflow(BaseScheduledTask):
    """Main workflow model extending BaseScheduledTask for scheduling capabilities."""

    # Override ID generation for workflows - always generate ID
    id: str | None = Field(
        default_factory=lambda: f"wf_{uuid.uuid4().hex[:12]}",
        description="Unique identifier",
    )

    user_id: str = Field(..., description="User ID who owns this workflow")

    title: str = Field(min_length=1, description="Title of the workflow")
    description: str = Field(
        default="",
        description="Short display description for cards/UI (1-2 sentences)",
    )
    prompt: str = Field(
        default="",
        description="Detailed execution instructions for AI. Falls back to description if not set.",
    )
    steps: list[WorkflowStep] = Field(
        description="List of workflow steps to execute", max_length=10
    )

    # Configuration
    trigger_config: TriggerConfig = Field(description="Trigger configuration")

    # Workflow-specific fields
    activated: bool = Field(
        default=True,
        description="Whether the workflow is activated and can be executed",
    )
    last_executed_at: datetime | None = Field(default=None)

    @field_serializer("last_executed_at")
    def serialize_last_executed_at(self, value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    # Community features
    is_public: bool = Field(
        default=False,
        description="Whether this workflow is published to the community marketplace",
    )
    slug: str | None = Field(
        default=None,
        description="Human-readable URL slug derived from title. Unique among public workflows.",
    )
    created_by: str | None = Field(
        default=None,
        description="User ID of the original creator (for public workflows)",
    )

    # Execution tracking
    current_step_index: int = Field(default=0, description="Index of currently executing step")
    execution_logs: list[str] = Field(default_factory=list, description="Execution logs")
    error_message: str | None = Field(default=None, description="Error message if workflow failed")

    # Statistics
    total_executions: int = Field(default=0, description="Total number of executions")
    successful_executions: int = Field(default=0, description="Number of successful executions")

    # Todo workflow flags (for auto-generated workflows linked to todos)
    is_todo_workflow: bool = Field(
        default=False,
        description="Whether this workflow was auto-generated for a todo item",
    )
    source_todo_id: str | None = Field(
        default=None,
        description="ID of the source todo if is_todo_workflow=True",
    )
    # System workflow flags (for auto-provisioned workflows created on integration connect)
    is_system_workflow: bool = Field(
        default=False,
        description="Auto-provisioned by GAIA when an integration is connected.",
    )
    source_integration: str | None = Field(
        default=None,
        description="Which integration provisioned this workflow. e.g. 'gmail', 'googlecalendar'.",
    )
    system_workflow_key: str | None = Field(
        default=None,
        description=(
            "Stable identifier linking this document back to its definition in code. "
            "Used for reset-to-default and idempotency. e.g. 'gmail:email_intelligence'."
        ),
    )

    selected_integrations: list[str] | None = Field(
        default=None,
        description="Integration slugs the user picked to bias step generation.",
    )

    creator: dict[str, Any] | None = Field(
        default=None,
        description="Creator info hydrated for public workflow lookups.",
    )

    def __init__(self, **data):
        """Initialize workflow with mapping from trigger_config to BaseScheduledTask fields."""
        # Ensure user_id is provided (it's required by BaseScheduledTask)
        if "user_id" not in data:
            raise ValueError("user_id is required for workflow creation")

        # Map trigger_config fields to BaseScheduledTask fields if not provided
        if "trigger_config" in data:
            trigger_config = data["trigger_config"]

            # Handle both dict and TriggerConfig object
            if isinstance(trigger_config, dict):
                # Map scheduled_at from trigger_config.next_run if not provided
                if "scheduled_at" not in data and trigger_config.get("next_run"):
                    data["scheduled_at"] = trigger_config["next_run"]

                # Map repeat from trigger_config.cron_expression if not provided
                if "repeat" not in data and trigger_config.get("cron_expression"):
                    data["repeat"] = trigger_config["cron_expression"]
            else:
                # TriggerConfig is already a Pydantic model
                # Map scheduled_at from trigger_config.next_run if not provided
                if (
                    "scheduled_at" not in data
                    and hasattr(trigger_config, "next_run")
                    and trigger_config.next_run
                ):
                    data["scheduled_at"] = trigger_config.next_run

                # Map repeat from trigger_config.cron_expression if not provided
                if (
                    "repeat" not in data
                    and hasattr(trigger_config, "cron_expression")
                    and trigger_config.cron_expression
                ):
                    data["repeat"] = trigger_config.cron_expression

        # A workflow only has a scheduled_at when it is a schedule-triggered (cron)
        # workflow with a next_run (mapped above). Manual / integration / todo
        # workflows have no scheduled run — leave scheduled_at as None rather than
        # fabricating "now", which would make them look due to the recovery scan.
        super().__init__(**data)

    @model_validator(mode="before")
    @classmethod
    def hydrate_legacy_prompt_and_description(cls, data):
        """Ensure legacy records still expose prompt and non-null description."""
        if isinstance(data, dict):
            description = data.get("description") or ""
            prompt = data.get("prompt") or description
            data["description"] = description
            data["prompt"] = prompt
        return data

    @property
    def effective_prompt(self) -> str:
        """Return the execution prompt with backward-compatible fallback."""
        return self.prompt or self.description


# Request/Response models for API


class CreateWorkflowRequest(BaseModel):
    """Request model for creating a new workflow."""

    title: str = Field(min_length=1, description="Title of the workflow")
    description: str | None = Field(
        default=None,
        description="Short optional display description (1-2 sentences)",
    )
    prompt: str = Field(min_length=1, description="Detailed execution instructions for the AI")
    trigger_config: TriggerConfig = Field(description="Trigger configuration")
    steps: list[WorkflowStep] | None = Field(
        default=None,
        description="Optional pre-existing steps (e.g., from explore/community workflows). If provided, step generation will be skipped.",
        max_length=10,
    )
    generate_immediately: bool = Field(
        default=False, description="Generate steps immediately vs background"
    )
    selected_integrations: list[str] | None = Field(
        default=None,
        description="Integration slugs selected by the user to hint step generation.",
    )

    # System workflow fields — set by provisioner, not by regular API users
    is_system_workflow: bool = Field(
        default=False,
        description="Auto-provisioned by GAIA when an integration is connected.",
    )
    source_integration: str | None = Field(
        default=None,
        description="Which integration provisioned this workflow.",
    )
    system_workflow_key: str | None = Field(
        default=None,
        description="Stable key linking to the original definition in code.",
    )

    @field_validator("title", "prompt")
    @classmethod
    def validate_non_empty_strings(cls, v):
        if not v or not v.strip():
            raise ValueError("Field cannot be empty or contain only whitespace")
        return v.strip()

    @field_validator("description")
    @classmethod
    def validate_optional_description(cls, v):
        if v is not None and not v.strip():
            return ""
        return v.strip() if v else None


class UpdateWorkflowRequest(BaseModel):
    """Request model for updating an existing workflow."""

    title: str | None = Field(default=None)
    description: str | None = Field(default=None)
    prompt: str | None = Field(default=None)
    steps: list[WorkflowStep] | None = Field(default=None)
    trigger_config: TriggerConfig | None = Field(default=None)
    activated: bool | None = Field(default=None)
    selected_integrations: list[str] | None = Field(default=None)

    @field_validator("title", "prompt")
    @classmethod
    def validate_optional_non_empty_strings(cls, v):
        if v is not None:
            if not v.strip():
                raise ValueError("Field cannot be empty or contain only whitespace")
            return v.strip()
        return v

    @field_validator("description")
    @classmethod
    def validate_optional_update_description(cls, v):
        if v is None:
            return None
        stripped = v.strip()
        return stripped if stripped else None


class WorkflowResponse(BaseModel):
    """Response model for workflow operations."""

    workflow: Workflow
    message: str = Field(description="Success or status message")


class WorkflowListResponse(BaseModel):
    """Response model for listing workflows."""

    workflows: list[Workflow]


class WorkflowExecutionRequest(BaseModel):
    """Request model for executing a workflow."""

    context: dict[str, Any] | None = Field(
        default=None, description="Additional context for execution"
    )


class WorkflowExecutionResponse(BaseModel):
    """Response model for workflow execution."""

    execution_id: str = Field(description="Unique ID for this execution")
    message: str


class WorkflowStatusResponse(BaseModel):
    """Response model for workflow status checks."""

    workflow_id: str
    activated: bool
    current_step_index: int
    total_steps: int
    progress_percentage: float
    last_updated: datetime
    error_message: str | None = Field(default=None)
    logs: list[str] = Field(default_factory=list)


class RegenerateStepsRequest(BaseModel):
    """Request model for regenerating workflow steps."""

    instruction: str = Field(min_length=1, description="Instruction for how to modify the workflow")
    reason: str | None = Field(default=None, description="Reason for regeneration")
    force_different_tools: bool = Field(
        default=False, description="Force the use of different tools"
    )
    selected_integrations: list[str] | None = Field(
        default=None,
        description="Integration slugs to bias regeneration; falls back to persisted selection.",
    )


class PublicWorkflowsResponse(BaseModel):
    """Response model for listing public workflows."""

    workflows: list[dict[str, Any]] = Field(
        description="List of public workflows with creator info"
    )
    total: int = Field(description="Total number of public workflows")


class PublishWorkflowResponse(BaseModel):
    """Response model for publishing a workflow."""

    message: str = Field(description="Success message")
    workflow_id: str = Field(description="ID of the published workflow")
    slug: str | None = Field(default=None, description="Public URL slug for the workflow")


class GenerateWorkflowPromptRequest(BaseModel):
    """Request model for AI-generated workflow instructions."""

    title: str | None = None
    description: str | None = None
    trigger_config: dict[str, Any] | None = None
    existing_prompt: str | None = None  # non-empty → improve mode
    selected_integrations: list[str] | None = Field(
        default=None,
        description="Integration slugs the user picked, used to bias the suggestion.",
    )


class SuggestedTrigger(BaseModel):
    """AI-suggested trigger configuration returned alongside generated instructions."""

    type: str = Field(description="Trigger type: manual, schedule, or integration")
    cron_expression: str | None = Field(
        default=None, description="Cron expression for scheduled triggers"
    )
    trigger_name: str | None = Field(
        default=None,
        description="Specific integration trigger slug (e.g., gmail_new_message)",
    )


class GeneratedPromptOutput(BaseModel):
    """Structured LLM output for the magic-prompt generator.

    Used by PydanticOutputParser to extract both the prose instructions and
    a trigger suggestion from a single LLM response.
    """

    instructions: str = Field(
        description=(
            "200-400 words of imperative execution instructions written directly to "
            "the AI agent. Use second-person present tense ('Fetch...', 'Search...', "
            "'Send...'). Cover: goal, data gathering, processing, actions, and failure "
            "handling. No scheduling info, no markdown, no bullet points — flowing "
            "prose only."
        )
    )
    trigger_type: str = Field(
        description=(
            "Suggested trigger type based on the user's intent. Must be one of: "
            "'manual' (on-demand/one-off tasks), 'schedule' (recurring cadence), "
            "or 'integration' (external event like email, calendar, webhook)."
        )
    )
    cron_expression: str | None = Field(
        default=None,
        description=(
            "5-field cron expression when trigger_type is 'schedule'. Examples: "
            "daily 9 AM = '0 9 * * *', weekdays 8 AM = '0 8 * * 1-5', "
            "every Monday 10 AM = '0 10 * * 1', every hour = '0 * * * *'. "
            "Must be null when trigger_type is not 'schedule'."
        ),
    )
    trigger_name: str | None = Field(
        default=None,
        description=(
            "When trigger_type is 'integration', the specific trigger slug from the "
            "available integration triggers list. Must be null when trigger_type is "
            "not 'integration'."
        ),
    )


class GenerateWorkflowPromptResponse(BaseModel):
    """Response model for AI-generated workflow instructions."""

    prompt: str
    suggested_trigger: SuggestedTrigger | None = None
