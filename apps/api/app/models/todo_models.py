from datetime import UTC, datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import UserScopedDocument
from app.models.trigger_subscription_models import TriggerSubscription
from app.models.workflow_models import WorkflowWithIntegrations


class Priority(str, Enum):
    HIGH = "high"  # red
    MEDIUM = "medium"  # yellow
    LOW = "low"  # blue
    NONE = "none"  # no color


class SubTask(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default="", description="Unique identifier for the subtask")
    title: str = Field(..., description="Title of the subtask")
    completed: bool = Field(default=False, description="Whether the subtask is completed")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


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
        description="VFS directory for tracked todos (canvas.md + log.md)",
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
    expires_at: datetime | None = Field(
        default=None,
        description="When this todo becomes irrelevant regardless of completion (LLM-set relevance window)",
    )
    references: list[str] = Field(
        default_factory=list,
        description="IDs of related past tracked todos (institutional memory references)",
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
    trigger_subscriptions: list[TriggerSubscription] = Field(
        default_factory=list,
        description="Read-only; subscriptions are written by trigger registration, not by clients",
    )

    @classmethod
    def from_document(
        cls, doc: "TodoDocument", *, workflow_categories: list[str] | None = None
    ) -> "TodoResponse":
        """Project a stored ``TodoDocument`` onto the API response shape. The
        tracked-only fields (canvas/log content, retry state) are dropped by
        ``extra="ignore"``; ``workflow_categories`` is enrichment, not stored."""
        return cls.model_validate(
            {**doc.model_dump(), "workflow_categories": workflow_categories or []}
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

    @classmethod
    def from_document(cls, doc: "ProjectDocument", *, todo_count: int = 0) -> "ProjectResponse":
        """Project a stored ``ProjectDocument`` onto the API response shape.

        ``ProjectWithCount`` already carries its ``todo_count``; pass it through so
        the aggregation's count is not silently dropped."""
        return cls.model_validate(
            {**doc.model_dump(), "todo_count": getattr(doc, "todo_count", todo_count)}
        )


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


class TodoLabelCount(BaseModel):
    """One label with the number of (incomplete) todos carrying it."""

    name: str
    count: int


class TodoStats(BaseModel):
    total: int = Field(default=0)
    completed: int = Field(default=0)
    pending: int = Field(default=0)
    overdue: int = Field(default=0)
    by_priority: dict[str, int] = Field(default_factory=dict)
    by_project: dict[str, int] = Field(default_factory=dict)
    completion_rate: float = Field(default=0.0)
    labels: list[TodoLabelCount] | None = None


class TodoListResponse(BaseModel):
    data: list[TodoResponse]
    meta: PaginationMeta
    stats: TodoStats | None = None


class TodoCanvasResponse(BaseModel):
    """A tracked todo's canvas markdown. Empty string when the todo has no canvas."""

    content: str


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
    failed: list[dict[str, object]] = Field(default_factory=list)
    total: int
    message: str


# Workflow generation for a todo — the todo-side view of a linked workflow.


class TodoWorkflowGenerationStatus(str, Enum):
    GENERATING = "generating"
    EXISTS = "exists"


class TodoWorkflowStatus(str, Enum):
    NOT_STARTED = "not_started"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class TodoWorkflowGenerationResponse(BaseModel):
    """Result of asking for a todo's workflow to be generated."""

    status: TodoWorkflowGenerationStatus
    message: str
    todo_id: str | None = Field(default=None, description="Set when generation was queued")
    workflow: WorkflowWithIntegrations | None = Field(
        default=None, description="Set when a generated workflow already existed"
    )


class TodoWorkflowStatusResponse(BaseModel):
    """Generation progress and the linked workflow, if any, for one todo."""

    todo_id: str
    has_workflow: bool
    is_generating: bool
    workflow_status: TodoWorkflowStatus
    workflow: WorkflowWithIntegrations | None = None


# Repository layer — persisted documents, typed updates, and aggregation results.
# ``TodoDocument`` is the full stored shape (a superset of ``TodoResponse``): it
# also carries the tracked-todo fields (canvas/log content, scheduling, retry
# state) that the executor and maintenance sweep read and write. Dormant legacy
# fields (goal/offer experiments) are dropped on read via ``extra="ignore"`` and
# preserved on write because updates are ``$set``-only.


class TodoDocument(UserScopedDocument):
    """A todo as stored in MongoDB. Base stamps created_at/updated_at on write."""

    title: str
    description: str | None = None
    labels: list[str] = Field(default_factory=list)
    due_date: datetime | None = None
    due_date_timezone: str | None = None
    priority: Priority = Priority.NONE
    project_id: str | None = None
    completed: bool = False
    subtasks: list[SubTask] = Field(default_factory=list)
    workflow_id: str | None = None
    workflow_activated: bool = False
    vfs_path: str | None = None
    scheduled_at: datetime | None = None
    recurrence: str | None = None
    gaia_retry_count: int = 0
    expires_at: datetime | None = None
    references: list[str] = Field(default_factory=list)
    completed_at: datetime | None = None
    # Canvas + log bodies for tracked todos live on the document itself.
    canvas_content: str | None = None
    log_content: str | None = None
    trigger_subscriptions: list[TriggerSubscription] = Field(default_factory=list)
    # Sender of the email an onboarding-seeded todo was extracted from.
    source_email: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TodoUpdate(BaseModel):
    """Partial ``$set`` update for a todo — every settable field, all optional."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str | None = None
    labels: list[str] | None = None
    due_date: datetime | None = None
    due_date_timezone: str | None = None
    priority: Priority | None = None
    project_id: str | None = None
    completed: bool | None = None
    subtasks: list[SubTask] | None = None
    workflow_id: str | None = None
    workflow_activated: bool | None = None
    vfs_path: str | None = None
    scheduled_at: datetime | None = None
    recurrence: str | None = None
    gaia_retry_count: int | None = None
    expires_at: datetime | None = None
    references: list[str] | None = None
    completed_at: datetime | None = None
    canvas_content: str | None = None
    log_content: str | None = None
    trigger_subscriptions: list[TriggerSubscription] | None = None


class ProjectDocument(UserScopedDocument):
    """A project as stored in MongoDB. Base stamps created_at/updated_at on write."""

    name: str
    description: str | None = None
    color: str | None = None
    is_default: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProjectUpdate(BaseModel):
    """Partial ``$set`` update for a project — user-editable fields, all optional."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    color: str | None = None


class ProjectWithCount(ProjectDocument):
    """A project plus its todo count, produced by the list aggregation."""

    todo_count: int = 0


class TodoCounts(BaseModel):
    """Dashboard/sidebar counts for a user's todos."""

    inbox: int = 0
    today: int = 0
    upcoming: int = 0
    completed: int = 0
    overdue: int = 0


class TodoPage(BaseModel):
    """A page of todos plus the unpaginated total for the same filter."""

    items: list[TodoDocument] = Field(default_factory=list)
    total: int = 0
