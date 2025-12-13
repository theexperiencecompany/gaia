from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, ConfigDict


class Priority(str, Enum):
    HIGH = "high"  # red
    MEDIUM = "medium"  # yellow
    LOW = "low"  # blue
    NONE = "none"  # no color


class SubTask(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default="", description="Unique identifier for the subtask")
    title: str = Field(..., description="Title of the subtask")
    completed: bool = Field(
        default=False, description="Whether the subtask is completed"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# Base model with all shared todo fields
class TodoBase(BaseModel):
    """Base model with shared fields for todos"""

    model_config = ConfigDict(from_attributes=True)

    title: Annotated[
        str, Field(min_length=1, max_length=200, description="Title of the todo item")
    ]
    description: str | None = Field(
        default=None, max_length=2000, description="Description of the todo item"
    )
    labels: list[str] = Field(
        default_factory=list, max_length=10, description="Labels for categorization"
    )
    due_date: datetime | None = Field(
        default=None, description="Due date for the todo item"
    )
    due_date_timezone: str | None = Field(
        default=None, description="Timezone for the due date (e.g., 'America/New_York')"
    )
    priority: Priority = Field(default=Priority.NONE, description="Priority level")
    project_id: str | None = Field(
        default=None, description="Project ID the todo belongs to"
    )
    completed: bool = Field(default=False, description="Whether the todo is completed")
    subtasks: list[SubTask] = Field(
        default_factory=list, max_length=50, description="List of subtasks"
    )
    workflow_id: str | None = Field(
        default=None, description="ID of the associated workflow"
    )


# For creating new todos
class TodoModel(TodoBase):
    """Model for creating todos"""

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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


# For responses with ID and user_id
class TodoResponse(TodoBase):
    """Complete todo response with all fields"""

    id: str = Field(..., description="Unique identifier")
    user_id: str = Field(..., description="User ID who owns the todo")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


# Project models
class ProjectBase(BaseModel):
    """Base model for project fields"""

    model_config = ConfigDict(from_attributes=True)

    name: Annotated[
        str, Field(min_length=1, max_length=100, description="Name of the project")
    ]
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


class ProjectModel(ProjectBase):
    """Model with timestamps"""

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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
    is_default: bool = Field(
        default=False, description="Whether this is the default Inbox project"
    )
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
