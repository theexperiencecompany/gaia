from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.constants.todos import ASSIGNEE_USER

# Who owns a todo. Replaces the legacy ``gaia-tracked`` label as the
# discriminator for GAIA-owned todos.
Assignee = Literal["user", "gaia"]

# A todo is either a unit of work or a long-lived goal lane (see TodoBase.kind).
TodoKind = Literal["task", "goal"]


class Priority(str, Enum):
    HIGH = "high"  # red
    MEDIUM = "medium"  # yellow
    LOW = "low"  # blue
    NONE = "none"  # no color


class ExecutionStatus(str, Enum):
    """Lifecycle of a GAIA-assigned todo. Only set when ``assignee == "gaia"``.

    Transitions are server-enforced (see ``tracked_todo_service``):
    ``proposed`` → ``queued`` only via Approve; ``proposed`` → ``dismissed`` via
    Dismiss; ``proposed`` → ``expired`` only by the curation pass; and
    ``queued`` → ``running`` → ``done | failed | needs_you`` only by the
    execution worker.
    """

    PROPOSED = "proposed"  # outward-facing work awaiting the user's Approve tap
    QUEUED = "queued"  # approved or internal work, enqueued for execution
    RUNNING = "running"  # execution worker is actively running it
    NEEDS_YOU = "needs_you"  # blocked mid-run on a decision only the user can make
    DONE = "done"  # completed successfully (set alongside completed/completed_at)
    FAILED = "failed"  # execution failed after retries (carries error_message cause)
    EXPIRED = "expired"  # proposal aged out past PROPOSAL_TTL_HOURS
    DISMISSED = "dismissed"  # user declined the proposal


class SubTask(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default="", description="Unique identifier for the subtask")
    title: str = Field(..., description="Title of the subtask")
    completed: bool = Field(default=False, description="Whether the subtask is completed")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# One discrete rich output attached to a tracked todo's ``artifacts`` facet.
ArtifactKind = Literal["markdown", "openui"]


class Artifact(BaseModel):
    """A named, discrete rich output on a tracked todo (rendered in the reader)."""

    model_config = ConfigDict(from_attributes=True)

    name: str = Field(..., description="Human-readable artifact name (also the VFS filename stem)")
    content: str = Field(
        ..., description="Artifact body (markdown, optionally with :::openui fences)"
    )
    kind: ArtifactKind = Field(
        default="markdown",
        description="How the frontend renders the content: plain markdown or OpenUI-aware.",
    )


# Base model with all shared todo fields
class TodoBase(BaseModel):
    """Base model with shared fields for todos"""

    model_config = ConfigDict(from_attributes=True)

    title: Annotated[str, Field(min_length=1, max_length=200, description="Title of the todo item")]
    description: str | None = Field(
        default=None, max_length=2000, description="Description of the todo item"
    )
    labels: list[str] = Field(
        default_factory=list, max_length=10, description="Labels for categorization"
    )
    due_date: datetime | None = Field(default=None, description="Due date for the todo item")
    due_date_timezone: str | None = Field(
        default=None, description="Timezone for the due date (e.g., 'America/New_York')"
    )
    priority: Priority = Field(default=Priority.NONE, description="Priority level")
    project_id: str | None = Field(default=None, description="Project ID the todo belongs to")
    completed: bool = Field(default=False, description="Whether the todo is completed")
    subtasks: list[SubTask] = Field(
        default_factory=list, max_length=50, description="List of subtasks"
    )
    workflow_id: str | None = Field(default=None, description="ID of the associated workflow")
    vfs_path: str | None = Field(
        default=None,
        description="VFS directory label for tracked todos (deliverable.md + notes.md + log.md)",
    )
    # Facet content lives on the todo doc but is served via dedicated facet
    # endpoints, never inlined into list/get responses — hence exclude=True keeps
    # these (potentially large) fields out of the default todo payload while
    # still declaring the document shape. Written through the storage primitives
    # in ``todo_canvas_storage``, not through create/update requests.
    deliverable_content: str | None = Field(
        default=None,
        exclude=True,
        description="Deliverable facet: the polished, send-ready output Approve releases.",
    )
    notes_content: str | None = Field(
        default=None,
        exclude=True,
        description="Notes facet: GAIA's private working memory (plan, key details, state).",
    )
    log_content: str | None = Field(
        default=None,
        exclude=True,
        description="Log facet: the activity/timeline audit trail (code-written).",
    )
    canvas_content: str | None = Field(
        default=None,
        exclude=True,
        description="Legacy combined blob; maps to the notes facet during migration.",
    )
    artifacts: list[Artifact] = Field(
        default_factory=list,
        exclude=True,
        description="Artifacts facet: optional discrete rich outputs.",
    )
    scheduled_at: datetime | None = Field(
        default=None,
        description="When GAIA should execute this tracked todo",
    )
    recurrence: str | None = Field(
        default=None,
        description="Recurrence pattern: 'daily', 'weekly', 'every_4h', or cron expression '0 9 * * 1'. Always evaluated in the user's current timezone (user.timezone).",
    )
    gaia_retry_count: int = Field(
        default=0,
        description="Number of failed execution attempts (managed by system)",
    )
    gaia_user_retry_count: int = Field(
        default=0,
        description="Number of times the user has manually retried this todo after failure (capped by MAX_GAIA_USER_RETRIES)",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="When this todo becomes irrelevant regardless of completion (LLM-set relevance window)",
    )
    references: list[str] = Field(
        default_factory=list,
        description="IDs of related past tracked todos (institutional memory references)",
    )
    assignee: Assignee = Field(
        default=ASSIGNEE_USER,
        description="Who owns this todo: 'user' (default) or 'gaia'. Replaces the gaia-tracked label.",
    )
    kind: TodoKind = Field(
        default="task",
        description=(
            "'task' (default) or 'goal'. A goal is a long-lived lane whose canvas "
            "is its living strategy; the nightly pass advances it and child tasks "
            "link back via goal_id. Goals are exempt from in-flight budgets and "
            "the day timeline."
        ),
    )
    goal_id: str | None = Field(
        default=None,
        description="ID of the goal-todo this task advances (real traceability link).",
    )
    execution_status: ExecutionStatus | None = Field(
        default=None,
        description="GAIA execution lifecycle state. Only set when assignee == 'gaia'.",
    )
    serves: str | None = Field(
        default=None,
        description="The goal, memory item, or explicit user request this GAIA todo advances (traceability).",
    )
    error_message: str | None = Field(
        default=None,
        description="Human-readable failure cause; set when execution_status == 'failed'.",
    )
    blocker_question: str | None = Field(
        default=None,
        description=(
            "The decision the run is blocked on; set when execution_status == 'needs_you'. "
            "Answering it (lifecycle.answer) re-queues the run."
        ),
    )
    last_run_conversation_id: str | None = Field(
        default=None,
        description=(
            "Conversation of the most recent execution run — the dashboard's "
            "click-through into where the work happened/is happening."
        ),
    )
    gaia_offer: str | None = Field(
        default=None,
        description="Silent-classification offer to hand a user todo to GAIA (non-blocking affordance, no notification).",
    )
    gaia_offer_dismissed: bool = Field(
        default=False,
        description="Set when the user dismisses the gaia_offer affordance; suppresses it on every surface.",
    )
    pitch_expires_at: datetime | None = Field(
        default=None,
        description="While set, this proposal is an active tier-upgrade pitch and is exempt from PROPOSAL_TTL expiry.",
    )


# For creating new todos
class TodoModel(TodoBase):
    """Model for creating todos"""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# For updating todos - all fields optional
class TodoUpdateRequest(BaseModel):
    """Model for updating todos - all fields optional for partial updates"""

    model_config = ConfigDict(from_attributes=True)

    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    description: Annotated[str, Field(max_length=2000)] | None = None
    labels: list[str] | None = None
    due_date: datetime | None = None
    due_date_timezone: str | None = None
    priority: Priority | None = None
    project_id: str | None = None
    completed: bool | None = None
    subtasks: list[SubTask] | None = None
    workflow_id: str | None = None
    vfs_path: str | None = None
    scheduled_at: datetime | None = None
    recurrence: str | None = None
    expires_at: datetime | None = None


# For responses with ID and user_id
class TodoResponse(TodoBase):
    """Complete todo response with all fields"""

    id: str = Field(..., description="Unique identifier")
    user_id: str = Field(..., description="User ID who owns the todo")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    completed_at: datetime | None = Field(
        default=None, description="Timestamp when todo was marked complete"
    )
    workflow_categories: list[str] = Field(
        default_factory=list,
        description="Tool categories from linked workflow steps for icon display",
    )


# Project models
class ProjectBase(BaseModel):
    """Base model for project fields"""

    model_config = ConfigDict(from_attributes=True)

    name: Annotated[str, Field(min_length=1, max_length=100, description="Name of the project")]
    description: str | None = Field(
        default=None, max_length=500, description="Description of the project"
    )
    color: str | None = Field(
        default=None,
        pattern="^#[0-9A-Fa-f]{6}$",
        description="Color code for the project in hex format",
    )


class ProjectCreate(ProjectBase):
    """Model for creating projects"""

    pass


class UpdateProjectRequest(BaseModel):
    """Model for updating projects - all fields optional"""

    model_config = ConfigDict(from_attributes=True)

    name: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    description: Annotated[str, Field(max_length=500)] | None = None
    color: Annotated[str, Field(pattern="^#[0-9A-Fa-f]{6}$")] | None = None


class ProjectResponse(ProjectBase):
    """Complete project response"""

    id: str = Field(..., description="Unique identifier")
    user_id: str = Field(..., description="User ID who owns the project")
    is_default: bool = Field(default=False, description="Whether this is the default Inbox project")
    todo_count: int = Field(default=0, description="Number of todos in this project")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


# Subtask operations
class SubtaskCreateRequest(BaseModel):
    title: str


class SubtaskUpdateRequest(BaseModel):
    title: str | None = None
    completed: bool | None = None


# Pagination and stats
class PaginationMeta(BaseModel):
    total: int = Field(..., description="Total number of items")
    page: int = Field(..., description="Current page (1-based)")
    per_page: int = Field(..., description="Items per page")
    pages: int = Field(..., description="Total number of pages")
    has_next: bool = Field(..., description="Whether there's a next page")
    has_prev: bool = Field(..., description="Whether there's a previous page")


class TodoStats(BaseModel):
    total: int = Field(default=0)
    completed: int = Field(default=0)
    pending: int = Field(default=0)
    overdue: int = Field(default=0)
    by_priority: dict[str, int] = Field(default_factory=dict)
    by_project: dict[str, int] = Field(default_factory=dict)
    completion_rate: float = Field(default=0.0)
    labels: list[dict] | None = None


class TodoListResponse(BaseModel):
    data: list[TodoResponse]
    meta: PaginationMeta
    stats: TodoStats | None = None


# Search
class SearchMode(str, Enum):
    TEXT = "text"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


class TodoSearchParams(BaseModel):
    q: str | None = None
    mode: SearchMode = Field(default=SearchMode.HYBRID)
    project_id: str | None = None
    completed: bool | None = None
    priority: Priority | None = None
    has_due_date: bool | None = None
    overdue: bool | None = None
    due_date_start: datetime | None = None
    due_date_end: datetime | None = None
    labels: list[str] | None = None
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=50, ge=1, le=100)
    include_stats: bool = Field(default=False)


# Bulk operations
class BulkOperationRequest(BaseModel):
    todo_ids: Annotated[list[str], Field(min_length=1, max_length=100)]


class BulkUpdateRequest(BulkOperationRequest):
    updates: TodoUpdateRequest


class BulkMoveRequest(BulkOperationRequest):
    project_id: str


class BulkOperationResponse(BaseModel):
    success: list[str] = Field(default_factory=list)
    failed: list[dict] = Field(default_factory=list)
    total: int
    message: str


# Silent classification of a newly created user todo (background step).
class TodoClassificationOutput(BaseModel):
    """LLM verdict on whether GAIA can take over a user-created todo.

    - ``offer``: GAIA can fully do it → surface a dismissible offer on the todo.
    - ``prep``: GAIA can partially help → prep supporting material into the work
      log without changing the assignee.
    - ``silent``: not something GAIA can do → no UI change, no message.
    """

    disposition: Literal["offer", "prep", "silent"] = Field(
        description="offer (fully doable), prep (partially doable), or silent (not doable)."
    )
    offer: str | None = Field(
        default=None,
        description="One short line shown as the 'GAIA can do this' offer. Required when disposition == 'offer'.",
    )
    prep_note: str | None = Field(
        default=None,
        description="Supporting material to prep into the work log. Required when disposition == 'prep'.",
    )
