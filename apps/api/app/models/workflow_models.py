"""
Clean and lean workflow models for GAIA workflow system.
"""

from collections.abc import Sequence
from datetime import datetime
from enum import Enum
from typing import Any, TypedDict
import uuid

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializeAsAny,
    field_serializer,
    field_validator,
    model_validator,
)

from app.db.repositories.base import MongoDocument
from app.models.scheduler_models import BaseScheduledTask, ScheduledTaskStatus
from app.models.trigger_configs import TriggerConfigData
from app.utils.cron_utils import get_next_run_time, validate_cron_expression
from app.utils.timezone import Timezone
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


class DeactivationReason(str, Enum):
    """Why a workflow was deactivated by the system, so an automatic resume can tell
    its own pauses apart from a workflow the user deliberately switched off. A
    user-initiated deactivation records no reason at all."""

    USER_DORMANT = "user_dormant"
    INTEGRATION_EXPIRED = "integration_expired"


class IntegrationRef(BaseModel):
    """Lightweight integration reference for workflow responses."""

    id: str
    name: str


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
    # None (not "UTC") is the unset sentinel so callers can distinguish a
    # timezone the user explicitly chose in the UI from one they never set —
    # the former is authoritative, the latter falls back to the resolved user tz.
    timezone: str | None = Field(default=None, description="Timezone for scheduled execution")
    next_run: datetime | None = Field(default=None, description="Next scheduled execution time")

    def calculate_next_run(
        self, base_time: datetime | None = None, user_timezone: str | None = None
    ) -> datetime | None:
        """Calculate the next run time from the cron expression. Returns UTC.

        The schedule runs in ``user_timezone`` if given, else the trigger's own
        stored timezone, else UTC. Both accept IANA names or "+05:30" offsets.
        ``get_next_run_time`` interprets the cron in that zone and returns UTC.
        """
        if self.type != TriggerType.SCHEDULE or not self.cron_expression:
            return None

        try:
            schedule_tz = Timezone.parse(user_timezone or self.timezone)
            next_run = get_next_run_time(self.cron_expression, base_time, schedule_tz)
            # Whole seconds only. The scheduler stamps each ARQ job with
            # ``int(armed_time.timestamp())`` and the stale-fire claim gate pins
            # ``next_run`` by equality against the reconstructed stamp, so a
            # sub-second component anywhere would make fresh fires read as
            # stale. Cron granularity is minutes; drop any stray sub-second.
            return next_run.replace(microsecond=0) if next_run else None
        except Exception as e:
            log.error("Error calculating next run time", error=str(e), error_type=type(e).__name__)
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
    def validate_cron_expression(cls, v: str | None) -> str | None:
        """Validate cron expression if provided."""
        if v is not None:
            if not validate_cron_expression(v):
                raise ValueError(f"Invalid cron expression: {v}")
        return v


class WorkflowCreator(TypedDict):
    """The public-facing creator card built by ``format_creator``.

    A ``TypedDict``, not a model: it rides inside the untyped card dicts of
    ``PublicWorkflowsResponse.workflows`` as well as ``Workflow.creator``, so it
    has to stay a plain dict on the wire for both.
    """

    id: str | None
    name: str
    avatar: str | None


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
    icon: str | None = Field(
        default=None,
        max_length=64,
        description="User-chosen icon slug (gaia-icons component name) shown when the workflow has no integration icons.",
    )
    icon_color: str | None = Field(
        default=None,
        pattern=r"^#[0-9a-fA-F]{6}$",
        description="Hex color for the user-chosen icon.",
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
    deactivated_reason: DeactivationReason | None = Field(
        default=None,
        description=(
            "Why the workflow is not activated. None means the user turned it off "
            "themselves — only system-paused workflows may be resumed automatically."
        ),
    )
    notify_on_completion: bool = Field(
        default=True,
        description=(
            "Whether GAIA sends the automatic completion notification when a run "
            "finishes. When False the run is silent (failures still notify) and the "
            "agent only notifies if the workflow's own instructions ask it to."
        ),
    )
    last_executed_at: datetime | None = Field(default=None)

    @field_serializer("last_executed_at")
    def serialize_last_executed_at(self, value: datetime | None) -> str | None:
        """Serialize the last-executed timestamp to an ISO string (or None)."""
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

    integration_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Integration ids this workflow uses — picked by the user or identified "
            "from intent by the workflow assistant. Scopes the tool palette when "
            "generating steps. Connection state is never stored here: "
            "required/missing integrations are derived from the steps at read time."
        ),
    )

    creator: WorkflowCreator | None = Field(
        default=None,
        description="Creator info hydrated for public workflow lookups.",
    )

    def __init__(self, **data: Any) -> None:  # noqa: ANN401 -- framework contract
        """Initialize workflow with mapping from trigger_config to BaseScheduledTask fields.

        ``**data`` stays ``Any``. Measured, don't re-litigate: ``**data: object``
        produces 4 errors on the ``super().__init__(**data)`` below, because
        BaseScheduledTask's generated ``__init__`` declares per-field types
        (``str``, ``datetime``, ``ScheduledTaskStatus``, ``int``) that a
        ``dict[str, object]`` bag cannot satisfy. The two "before" validators in
        this module were narrowed to ``object`` and did not need it.
        """
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
    def hydrate_legacy_prompt_and_description(cls, data: Any) -> Any:  # noqa: ANN401 -- forwards **data into BaseScheduledTask's typed __init__
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


class WorkflowWithIntegrations(Workflow):
    """Read-time view of a workflow: the persisted `Workflow` plus its computed
    integration requirements. Never persisted — the storage model is `Workflow`;
    these fields are populated by the service on read paths only."""

    required_integrations: list[IntegrationRef] | None = Field(
        default=None,
        description="Integration IDs required by the workflow's steps.",
    )
    missing_integrations: list[IntegrationRef] | None = Field(
        default=None,
        description="Required integrations the user has not connected yet.",
    )


class CreateWorkflowRequest(BaseModel):
    """Request model for creating a new workflow."""

    title: str = Field(min_length=1, description="Title of the workflow")
    description: str | None = Field(
        default=None,
        description="Short optional display description (1-2 sentences)",
    )
    prompt: str = Field(min_length=1, description="Detailed execution instructions for the AI")
    icon: str | None = Field(
        default=None, max_length=64, description="User-chosen icon slug (gaia-icons component name)"
    )
    icon_color: str | None = Field(
        default=None,
        pattern=r"^#[0-9a-fA-F]{6}$",
        description="Hex color for the user-chosen icon",
    )
    trigger_config: TriggerConfig = Field(description="Trigger configuration")
    steps: list[WorkflowStep] | None = Field(
        default=None,
        description="Optional pre-existing steps (e.g., from explore/community workflows). If provided, step generation will be skipped.",
        max_length=10,
    )
    generate_immediately: bool = Field(
        default=False, description="Generate steps immediately vs background"
    )
    notify_on_completion: bool = Field(
        default=True,
        description="Whether GAIA sends the automatic completion notification when a run finishes.",
    )
    integration_ids: list[str] | None = Field(
        default=None,
        description=(
            "Integration ids this workflow uses — picked by the user or identified "
            "from intent. Scopes the tool palette when generating steps."
        ),
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
    def validate_non_empty_strings(cls, v: str) -> str:
        """Require non-blank title/prompt and strip surrounding whitespace."""
        if not v or not v.strip():
            raise ValueError("Field cannot be empty or contain only whitespace")
        return v.strip()

    @field_validator("description")
    @classmethod
    def validate_optional_description(cls, v: str | None) -> str | None:
        """Normalize an optional description, coercing blank values to None/empty."""
        if v is not None and not v.strip():
            return ""
        return v.strip() if v else None


class CreateWorkflowFromTodoRequest(BaseModel):
    """Request model for the todo → workflow migration helper.

    ``todo_id``/``todo_title`` are optional at the schema level on purpose: the
    endpoint rejects a payload missing either with a 400, and declaring them
    required here would turn that into FastAPI's 422 — a change to the contract
    the web client already codes against, not a typing fix.
    """

    todo_id: str | None = None
    todo_title: str | None = None
    todo_description: str | None = None


class UpdateWorkflowRequest(BaseModel):
    """Request model for updating an existing workflow."""

    title: str | None = Field(default=None)
    description: str | None = Field(default=None)
    prompt: str | None = Field(default=None)
    icon: str | None = Field(default=None, max_length=64)
    icon_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    steps: list[WorkflowStep] | None = Field(default=None)
    trigger_config: TriggerConfig | None = Field(default=None)
    activated: bool | None = Field(default=None)
    notify_on_completion: bool | None = Field(default=None)
    integration_ids: list[str] | None = Field(default=None)

    @field_validator("title", "prompt")
    @classmethod
    def validate_optional_non_empty_strings(cls, v: str | None) -> str | None:
        """Strip provided title/prompt updates and reject blank-only values."""
        if v is not None:
            if not v.strip():
                raise ValueError("Field cannot be empty or contain only whitespace")
            return v.strip()
        return v

    @field_validator("description")
    @classmethod
    def validate_optional_update_description(cls, v: str | None) -> str | None:
        """Normalize a description update, coercing blank values to None."""
        if v is None:
            return None
        stripped = v.strip()
        return stripped or None


class WorkflowResponse(BaseModel):
    """Response model for workflow operations."""

    # SerializeAsAny so a WorkflowWithIntegrations (from read paths) serializes
    # its extra integration fields; plain Workflow instances still validate.
    workflow: SerializeAsAny[Workflow]
    message: str = Field(description="Success or status message")


class WorkflowListResponse(BaseModel):
    """Response model for listing workflows."""

    # Sequence (not list) because list is invariant: the read path hands us
    # list[WorkflowWithIntegrations]. SerializeAsAny keeps the subclass's extra
    # integration fields in the payload while still accepting a plain Workflow.
    workflows: Sequence[SerializeAsAny[Workflow]]


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
    integration_ids: list[str] | None = Field(
        default=None,
        description="Integration ids to scope regeneration; falls back to the workflow's own.",
    )


class PublicWorkflowsResponse(BaseModel):
    """Response model for listing public workflows."""

    # Deliberately left as untyped card dicts. Three endpoints build these — the
    # community and explore lists here plus /public/{id}/workflows in
    # integrations/public.py — and each emits a different key set (explore adds
    # categories + total_executions, related adds total_executions). Modelling
    # them as a card base + subclasses means every construction site must hand
    # over a model instead of a dict, or Pydantic silently drops the subclass-only
    # keys from the payload; that reaches outside this flow's files and changes
    # what a frontend consumer receives if it is done partially (Type Safety
    # item 14). Typed together with that endpoint, not before.
    workflows: list[dict[str, Any]] = Field(
        description="List of public workflows with creator info"
    )
    total: int = Field(description="Total number of public workflows")


class ResetWorkflowResponse(BaseModel):
    """Response model for resetting a system workflow to its default definition."""

    success: bool = Field(description="Whether the workflow was reset")
    message: str = Field(description="Success or status message")


class WorkflowMessageResponse(BaseModel):
    """Acknowledgement for a workflow mutation that returns no entity."""

    message: str = Field(description="Human-readable outcome")


class PublishWorkflowResponse(BaseModel):
    """Response model for publishing a workflow."""

    message: str = Field(description="Success message")
    workflow_id: str = Field(description="ID of the published workflow")
    slug: str | None = Field(default=None, description="Public URL slug for the workflow")


class PromptTriggerHint(BaseModel):
    """The subset of a trigger config the magic-prompt generator reads.

    The workflow editor posts whatever it currently holds in the trigger form, so
    every field is optional and unknown keys are ignored — this is a hint for the
    LLM, never a trigger that gets persisted. ``type`` defaults to ``"manual"``
    but is nullable, matching the ``.get("type", "manual")`` this replaced: an
    omitted type means manual, an explicitly null one stays unset.
    """

    type: str | None = "manual"
    cron_expression: str | None = None
    trigger_name: str | None = None


class GenerateWorkflowPromptRequest(BaseModel):
    """Request model for AI-generated workflow instructions."""

    title: str | None = None
    description: str | None = None
    trigger_config: PromptTriggerHint | None = None
    existing_prompt: str | None = None  # non-empty → improve mode
    integration_ids: list[str] | None = Field(
        default=None,
        description="Integration ids the user picked, used to bias the suggestion.",
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


class GeneratedPromptResult(TypedDict):
    """What ``generate_workflow_prompt`` hands back to its two callers.

    A ``TypedDict``, not the response model above (Type Safety item 6): the value
    never crosses a validation boundary — the endpoint builds the response model
    from it, and onboarding's ``_build_one_workflow`` reads the same two keys
    off the dict. Being a plain dict at runtime keeps both call sites working
    untouched while mypy starts checking the keys.
    """

    prompt: str
    suggested_trigger: SuggestedTrigger | None


# Repository persistence models (Wave E migration)


class WorkflowDocument(Workflow, MongoDocument):
    """A workflow as stored in MongoDB.

    Identity is the string business key ``id`` (persisted as ``_id``; the two are
    equal ``wf_…`` UUIDs). Extends ``Workflow`` so it doubles as the read model —
    the service wraps it in ``WorkflowWithIntegrations`` only to attach computed
    integration fields. ``extra="ignore"`` (from ``MongoDocument``) tolerates
    legacy stray fields; the ISO-string ``created_at``/``scheduled_at`` values a
    handful of legacy rows still carry are coerced to tz-aware datetimes by the
    inherited ``BaseScheduledTask`` validators.
    """

    # Resolve the ``Workflow.id`` (``str | None``, alias ``_id``) vs
    # ``MongoDocument.id`` (``str``) diamond: a persisted workflow always has its
    # ``wf_…`` id, so the stored document is non-optional. The repository keys on
    # ``_id`` directly, so no alias is needed here.
    id: str = Field(default_factory=lambda: f"wf_{uuid.uuid4().hex[:12]}")


class WorkflowCreatorInfo(BaseModel):
    """One creator row hydrated by the ``creator_lookup_stage`` ``$lookup`` — the
    projected ``{name, email, picture}`` subset of the joined user document. All
    optional because the join yields no match for a non-user creator (the literal
    ``"system"``) or a legacy row whose user was deleted."""

    name: str | None = None
    email: str | None = None
    picture: str | None = None


class PublicWorkflowRow(WorkflowDocument):
    """A workflow read from a public-marketplace aggregation: the persisted
    ``WorkflowDocument`` plus the joined ``creator_info`` array.

    ``creator_info`` and ``use_case_categories`` are ``exclude``d from
    serialization so a row handed straight back as a ``WorkflowResponse.workflow``
    (the single ``get_public`` path) emits exactly the ``Workflow`` shape — the
    join scaffolding never leaks into the response. The list paths
    (community/explore/related) read these attributes to hand-build their dict
    payloads and never serialize the row itself.
    """

    creator_info: list[WorkflowCreatorInfo] = Field(default_factory=list, exclude=True)
    # Explore-only curation field; absent on community/related rows (defaults to
    # ``["featured"]`` there, matching the legacy ``.get(..., ["featured"])`` read).
    use_case_categories: list[str] = Field(default_factory=lambda: ["featured"], exclude=True)


class WorkflowUpdate(BaseModel):
    """Partial ``$set`` update for a workflow — the flat, top-level fields the
    owned-CRUD paths mutate. Nested (``trigger_config.*``) and operator
    (``$inc`` stats, atomic status claim) writes are named repository methods that
    use the raw-update seam, not this model.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str | None = None
    prompt: str | None = None
    icon: str | None = None
    icon_color: str | None = None
    steps: list[WorkflowStep] | None = None
    trigger_config: TriggerConfig | None = None
    activated: bool | None = None
    notify_on_completion: bool | None = None
    integration_ids: list[str] | None = None
    status: ScheduledTaskStatus | None = None
    scheduled_at: datetime | None = None
    repeat: str | None = None
    error_message: str | None = None
    current_step_index: int | None = None
    is_public: bool | None = None
    slug: str | None = None
    created_by: str | None = None
